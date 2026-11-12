"""Hybrid RAG: BM25 (own implementation) + dense embeddings (GPU) fused with Reciprocal Rank Fusion, then a cross-encoder reranker. Persistent chunk store in SQLite,\nsample policy pack per app (kb_pack.py), live-data retrieval over tickets and feedback, import/export and a recall@k evaluator."""
import re, io, os, json, math, base64, sqlite3, threading, time, collections
import numpy as np
import gpu
BUILTIN_KB = [
    {
        "title": "FSSAI Food Safety Compliance & Licensing Guidelines 2024",
        "source": "FSSAI Guidelines 2024",
        "text": "FSSAI (Food Safety and Standards Authority of India) is the statutory body under the Ministry of Health & Family Welfare, Government of India. All food business operators (FBOs), franchise outlets, and commercial kitchens must hold a valid FSSAI license/registration. Outlets must maintain strict hygiene ratings, display FSSAI license numbers on billing receipts, conduct biannual food sample testing, adhere to temperature controls (cold storage <= 5°C, hot display >= 60°C), and maintain staff hygiene records and FOSTAC certified safety supervisors."
    },
    {
        "title": "SOP-001: Customer Service & CSAT Standards",
        "source": "Franchise SOP Manual",
        "text": "All franchise outlets must maintain a minimum CSAT score of 4.0/5.0. Staff must greet customers within 30 seconds of entry. Customer complaints must be resolved within 24 hours. Mystery shopping audits are conducted monthly."
    },
    {
        "title": "SOP-002: Store Operations & Temperature Hygiene",
        "source": "Franchise SOP Manual",
        "text": "Food items must strictly follow FEFO (First-Expired, First-Out) rotation. Cold storage units must maintain temperature between 1°C and 4°C. Deep freezers must stay below -18°C. Oil TPC (Total Polar Compounds) must not exceed 25%."
    },
    {
        "title": "Maritime Shipping Industry & Port Congestion Guide 2024",
        "source": "Global Maritime Logistics Report",
        "text": "Compounding challenges in the Indian shipping industry include port infrastructure bottlenecks, high dwell times at JNPT/Mumbai ports, monsoon storm surges, and tariff adjustments. Shipping lines must optimize vessel speeds and leverage real-time AIS telemetry for route planning."
    }
]

import config
_LOCK = threading.RLock(); _C = {"ver": -1, "rows": [], "bm25": None, "emb": None, "emb_n": -1}; _VER = [0]
_STOP = set("a an the of to in on for and or is are was were be been it this that these those with as at by from how what when which who whom do does did can could should would will may might must not no if then than so we you i they he she them their our your its into about over under per each any all more most such via".split())
def _stem(w):
    for suf in ("ations", "ation", "ingly", "ings", "ing", "edly", "ed", "ies", "es", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf): return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w
def tok(t): return [_stem(w) for w in re.findall(r"[a-z0-9]+|[^\x00-\x7f\s]+", (t or "").lower()) if w not in _STOP]

class BM25:
    """Okapi BM25 (k1=1.5, b=0.75) over pre-tokenised documents; score() returns a numpy vector over all docs."""
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b; self.n = len(docs); self.tf = [collections.Counter(d) for d in docs]; self.len = np.array([len(d) for d in docs], dtype="float32"); self.avg = float(self.len.mean()) if self.n else 1.0
        df = collections.Counter(); self.post = collections.defaultdict(list)
        for i, c in enumerate(self.tf):
            for w, f in c.items(): df[w] += 1; self.post[w].append((i, f))
        self.idf = {w: math.log(1 + (self.n - d + .5) / (d + .5)) for w, d in df.items()}
    def score(self, q):
        s = np.zeros(self.n, dtype="float32")
        for w in set(q):
            if w not in self.idf: continue
            idf = self.idf[w]
            for i, f in self.post[w]: s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s

def _db():
    c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    c.execute("CREATE TABLE IF NOT EXISTS kb_chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source TEXT, owner TEXT, text TEXT, emb BLOB, builtin INT DEFAULT 0, ts TEXT DEFAULT CURRENT_TIMESTAMP)"); return c
def _chunks(text, size=700, overlap=90):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= size: return [text] if text else []
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(s) + 1 <= size: cur = (cur + " " + s).strip()
        else:
            if cur: out.append(cur)
            cur = (cur[-overlap:] + " " + s).strip()
    if cur: out.append(cur)
    return out
def drive_dir():
    """Where the user's earlier RAG builder wrote its output (MyDrive/<App>_AI). Override with KB_DRIVE_DIR."""
    k = os.environ.get("APP_KIND", "Franchise"); return os.environ.get("KB_DRIVE_DIR") or f"/content/drive/MyDrive/{'FranchiseOps_AI' if k == 'Franchise' else 'FreightQuote_AI'}"
def _drive_chunks():
    """Chunks produced by the earlier RAG builder notebooks (synthetic_kb/all_chunks.jsonl, else faiss_indexes/*_chunks_meta.json). Returns [(title, source, text)]."""
    d = drive_dir(); out = []
    p = os.path.join(d, "synthetic_kb", "all_chunks.jsonl")
    try:
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                try: c = json.loads(line); out.append((c.get("title", "doc"), "your RAG builder (" + str(c.get("source", "kb")) + ")", c["text"]))
                except Exception: pass
        else:
            for f in os.listdir(os.path.join(d, "faiss_indexes")) if os.path.isdir(os.path.join(d, "faiss_indexes")) else []:
                if f.endswith("_chunks_meta.json"):
                    for c in json.load(open(os.path.join(d, "faiss_indexes", f), encoding="utf-8")): out.append((c.get("title", "doc"), "your RAG builder (" + str(c.get("source", "kb")) + ")", c["text"]))
    except Exception: pass
    return out
def import_drive():
    """(Re)load the Drive chunks as built-in knowledge (builtin=2). Returns the number loaded."""
    _seed(); rows = _drive_chunks(); c = _db()
    try:
        c.execute("DELETE FROM kb_chunks WHERE builtin=2")
        seen = set(); ins = []
        for t, s_, x in rows:
            k = hash((t, x))
            if k in seen or len(x) < 20: continue
            seen.add(k); ins.append((t, s_, None, x, 2))
        c.executemany("INSERT INTO kb_chunks(title,source,owner,text,builtin) VALUES(?,?,?,?,?)", ins); c.commit()
    finally: c.close()
    _VER[0] += 1; return len(ins)
def _seed():
    import kb_pack
    kind = os.environ.get("APP_KIND", "Franchise"); pack = kb_pack.FRANCHISE if kind == "Franchise" else kb_pack.FREIGHT
    c = _db()
    try:
        if c.execute("SELECT COUNT(*) FROM kb_chunks WHERE builtin=1").fetchone()[0] == 0:
            rows = []
            try:
                for d in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_docs.json"), encoding="utf-8")).get(kind, []): rows += [(d["title"], "Knowledge pack (your RAG builder)", None, ch, 1) for ch in _chunks(d["content"])]
            except Exception: pass
            rows += [(t, s + " (sample)", None, ch, 1) for t, s, x in pack for ch in _chunks(x)]
            c.executemany("INSERT INTO kb_chunks(title,source,owner,text,builtin) VALUES(?,?,?,?,?)", rows); c.commit()
        have_drive = c.execute("SELECT COUNT(*) FROM kb_chunks WHERE builtin=2").fetchone()[0]
    finally: c.close()
    if not have_drive and os.path.isdir(drive_dir()):
        rows = _drive_chunks()
        if rows:
            c = _db()
            try:
                seen = set(); ins = []
                for t, s_, x in rows:
                    k = hash((t, x))
                    if k in seen or len(x) < 20: continue
                    seen.add(k); ins.append((t, s_, None, x, 2))
                c.executemany("INSERT INTO kb_chunks(title,source,owner,text,builtin) VALUES(?,?,?,?,?)", ins); c.commit()
            finally: c.close()
def _load():
    """(Re)build the in-memory view: rows, BM25 index and the embedding matrix. Embeddings are computed on the GPU once and stored in SQLite."""
    with _LOCK:
        if _C["ver"] == _VER[0] and _C["rows"]: return _C
        _seed(); c = _db()
        try:
            rows = [{"id": r[0], "title": r[1], "source": r[2], "owner": r[3], "text": r[4], "emb": r[5]} for r in c.execute("SELECT id,title,source,owner,text,emb FROM kb_chunks ORDER BY id")]
        finally: c.close()
        _C.update(ver=_VER[0], rows=rows, bm25=BM25([tok(r["title"] + " " + r["text"]) for r in rows]), emb=None, emb_n=-1); return _C
def _embeddings():
    C = _load()
    if gpu.S["models"]["embed"]["state"] != "ready": return None
    with _LOCK:
        if _C["emb"] is not None and _C["emb_n"] == len(_C["rows"]): return _C["emb"]
        need = [i for i, r in enumerate(_C["rows"]) if r["emb"] is None]
        if need:
            v = gpu.embed([_C["rows"][i]["text"] for i in need])
            if v is None: return None
            c = _db()
            try:
                for i, e in zip(need, v): _C["rows"][i]["emb"] = e.astype("float32").tobytes(); c.execute("UPDATE kb_chunks SET emb=? WHERE id=?", (_C["rows"][i]["emb"], _C["rows"][i]["id"]))
                c.commit()
            finally: c.close()
        dim = len(np.frombuffer(_C["rows"][0]["emb"], dtype="float32")); mat = np.stack([np.frombuffer(r["emb"], dtype="float32") if r["emb"] and len(r["emb"]) == dim * 4 else np.zeros(dim, "float32") for r in _C["rows"]])
        _C["emb"], _C["emb_n"] = mat, len(_C["rows"]); return mat
def warm():
    """Called once the embedder is ready: index everything so the first question is fast."""
    try: _embeddings()
    except Exception: pass

def add(title, source, text, owner, embs=None):
    _load(); parts = [c for c in _chunks(text) if len(c) >= 20]
    if not parts: return 0
    c = _db()
    try:
        c.executemany("INSERT INTO kb_chunks(title,source,owner,text,emb,builtin) VALUES(?,?,?,?,?,0)", [(title, source, owner, p, (embs[i] if embs else None)) for i, p in enumerate(parts)]); c.commit()
    finally: c.close()
    _VER[0] += 1; return len(parts)
def delete_doc(title, owner):
    c = _db()
    try: n = c.execute("DELETE FROM kb_chunks WHERE title=? AND owner=? AND builtin=0", (title, owner)).rowcount; c.commit()
    finally: c.close()
    _VER[0] += 1; return n
def read_pdf(name, data):
    if name.lower().endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf: return "\n".join((p.extract_text() or "") for p in pdf.pages)
    return data.decode("utf-8", errors="ignore")
def docs(owner): C = _load(); return [{k: v for k, v in r.items() if k != "emb"} for r in C["rows"] if r["owner"] in (None, owner)]

def _rank(v, mask, n=30):
    idx = np.where(mask)[0]
    if not len(idx): return []
    o = idx[np.argsort(-v[idx])][:n]; return [int(i) for i in o if v[i] > 0]
_SC = collections.OrderedDict(); _MASK = {}
def search(q, owner, k=4, mode="hybrid", rerank=True):
    """Cached front door: identical queries are answered from memory until the corpus changes (a few ms instead of an embedding + rerank pass)."""
    key = (_VER[0], q.strip().lower(), owner, k, mode, bool(rerank) and gpu.S["models"]["rerank"]["state"] == "ready", gpu.S["models"]["embed"]["state"])
    if key in _SC: _SC.move_to_end(key); return _SC[key]
    r = _search(q, owner, k, mode, rerank); _SC[key] = r
    while len(_SC) > 300: _SC.popitem(last=False)
    return r
def _search(q, owner, k=4, mode="hybrid", rerank=True):
    """mode: bm25 | dense | hybrid (BM25 + dense, RRF) ; hybrid then cross-encoder rerank when loaded. Returns hits with the score breakdown."""
    C = _load(); rows = C["rows"]
    if not rows or not q.strip(): return []
    mk = (C["ver"], owner); mask = _MASK.get(mk)
    if mask is None: _MASK.clear(); mask = _MASK[mk] = np.array([r["owner"] in (None, owner) for r in rows])
    bm = C["bm25"].score(tok(q)); dn = None; used = []
    if mode in ("dense", "hybrid"):
        try:
            mat = _embeddings(); qv = gpu.embed([q]) if mat is not None else None
            if mat is not None and qv is not None: dn = mat @ qv[0]
        except Exception: dn = None
    if mode == "dense" and dn is None: mode = "bm25"
    lists = []
    if mode in ("bm25", "hybrid"): lists.append(("bm25", _rank(bm, mask))); used.append("BM25")
    if dn is not None and mode in ("dense", "hybrid"): lists.append(("dense", _rank(dn + 1, mask))); used.append("dense")
    rrf = collections.defaultdict(float); pos = collections.defaultdict(dict)
    for nm, lst in lists:
        for r, i in enumerate(lst): rrf[i] += 1 / (60 + r + 1); pos[i][nm] = r + 1
    order = sorted(rrf, key=lambda i: -rrf[i])[:8]; rr = None
    if rerank and mode != "bm25" and order: rr = gpu.rerank(q, [rows[i]["text"] for i in order])
    if rr is not None:
        used.append("rerank"); ix = np.argsort(-rr); z = 1 / (1 + np.exp(-rr[ix])); order = [order[j] for j in ix]; sc = {i: float(zz) for i, zz in zip(order, z)}
    else:
        top = max(rrf.values()) if rrf else 1; sc = {i: rrf[i] / top for i in order}
        if mode == "bm25": mx = float(bm[mask].max()) or 1.0; sc = {i: float(bm[i]) / mx for i in order}
        elif mode == "dense" and dn is not None: sc = {i: float(dn[i]) for i in order}
    out = []
    for i in order[: max(k, 1)]:
        if bm[i] <= 0 and (dn is None or dn[i] < 0.3): continue
        r = rows[i]; why = " · ".join([f"{n} #{pos[i][n]}" for n in ("bm25", "dense") if n in pos[i]] + ([f"rerank {sc[i]:.2f}"] if rr is not None else []))
        out.append({"title": r["title"], "source": r["source"], "text": r["text"], "score": round(sc[i], 3), "why": why, "via": "+".join(used), "owner": r["owner"], "id": r["id"]})
    return out

_LH = {"t": 0, "b": None, "meta": None}
def live_hits(q, k=4):
    """BM25 over the live operational records: open tickets and (Franchise) customer feedback. Fresh on every call."""
    import live_engine as LE
    import time as _t
    if _LH["b"] is not None and _t.time() - _LH["t"] < 20:
        s = _LH["b"].score(tok(q)); o = np.argsort(-s)[:k]; meta = _LH["meta"]
        return [{"title": meta[i][0], "source": "live data", "text": meta[i][1], "score": round(float(s[i]), 2), "why": "BM25 on live records", "via": "live"} for i in o if s[i] > 0]
    docs_, meta = [], []
    try:
        for r in LE.conn().execute("SELECT action_id, type, target, detail, severity, status FROM agent_actions ORDER BY action_id DESC LIMIT 600").fetchall():
            docs_.append(f"{r[1]} {r[2]} {r[3]} {r[4]}"); meta.append((f"Ticket #{r[0]} · {r[1]} · {r[2]} · {r[4]} · {r[5]}", f"{r[3]}"))
        if os.environ.get("APP_KIND", "Franchise") == "Franchise":
            for r in LE.conn().execute("SELECT outlet_id, rating, comment FROM feedback ORDER BY rowid DESC LIMIT 800").fetchall():
                docs_.append(f"{r[0]} {r[2]}"); meta.append((f"Review · {r[0]} · {r[1]}★", str(r[2])))
    except Exception: return []
    if not docs_: return []
    b = BM25([tok(d) for d in docs_]); _LH.update(t=_t.time(), b=b, meta=meta); s = b.score(tok(q)); o = np.argsort(-s)[:k]
    return [{"title": meta[i][0], "source": "live data", "text": meta[i][1], "score": round(float(s[i]), 2), "why": "BM25 on live records", "via": "live"} for i in o if s[i] > 0]

def export_json(owner):
    C = _load(); mine = [r for r in C["rows"] if r["owner"] == owner]
    return {"format": "kb-v1", "emb_model": gpu.S["models"]["embed"]["name"], "chunks": [{"title": r["title"], "source": r["source"], "text": r["text"], "emb": base64.b64encode(r["emb"]).decode() if r["emb"] else None} for r in mine]}
def import_json(data, owner):
    if not isinstance(data, dict) or data.get("format") != "kb-v1": raise ValueError("not a kb-v1 export")
    same = data.get("emb_model") == gpu.S["models"]["embed"]["name"]; n = 0; c = _db()
    try:
        for ch in data.get("chunks", [])[:20000]:
            e = base64.b64decode(ch["emb"]) if same and ch.get("emb") else None
            c.execute("INSERT INTO kb_chunks(title,source,owner,text,emb,builtin) VALUES(?,?,?,?,?,0)", (str(ch["title"])[:200], str(ch.get("source", "imported"))[:200], owner, str(ch["text"])[:4000], e)); n += 1
        c.commit()
    finally: c.close()
    _VER[0] += 1; return n, same

def evaluate(kind, owner="eval"):
    """recall@1 / recall@3 / MRR on the built-in question set, for each retrieval mode, so the benefit of hybrid + rerank is measured, not assumed."""
    import kb_pack
    pairs = kb_pack.EVAL[kind]; rows = []
    for name, mode, rr in (("BM25 only", "bm25", False), ("Dense only", "dense", False), ("Hybrid (BM25+dense, RRF)", "hybrid", False), ("Hybrid + cross-encoder rerank", "hybrid", True)):
        r1 = r3 = mrr = 0; ok = True
        for q, want in pairs:
            hits = search(q, owner, 5, mode, rr)
            if (mode in ("dense", "hybrid") and "dense" not in (hits[0]["via"] if hits else "dense")) or (rr and hits and "rerank" not in hits[0]["via"]): ok = False
            titles = []
            for h in hits:
                if h["title"] not in titles: titles.append(h["title"])
            if want in titles: p = titles.index(want) + 1; r1 += p == 1; r3 += p <= 3; mrr += 1 / p
        n = len(pairs); rows.append({"method": name, "recall@1": round(r1 / n, 2) if ok else None, "recall@3": round(r3 / n, 2) if ok else None, "MRR": round(mrr / n, 2) if ok else None, "note": "" if ok else "model not loaded yet"})
    return rows
