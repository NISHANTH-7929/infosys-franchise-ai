"""GPU layer: Qwen2.5 (LLM), Facebook NLLB-200 (translation, the only translator) and a sentence embedder (RAG), all loaded on the GPU at startup in a background thread.
status() powers the GPU panel in the app so you can see what is on which device. Everything degrades loudly (never silently) when CUDA or a model is missing."""
import os, re, json, time, threading, sqlite3, hashlib
from config import DB_PATH, NLLB_MODEL, MODEL_NAME, HF_TOKEN
try: from lang_pack import EXTRA_LANGS, extra_detect
except Exception: EXTRA_LANGS, extra_detect = {}, (lambda t: None)

NLLB_LANGS = {"English": "eng_Latn", "Hindi (हिंदी)": "hin_Deva", "Tamil (தமிழ்)": "tam_Taml", "Telugu (తెలుగు)": "tel_Telu", "Kannada (ಕನ್ನಡ)": "kan_Knda", "Malayalam (മലയാളം)": "mal_Mlym",
    "Marathi (मराठी)": "mar_Deva", "Bengali (বাংলা)": "ben_Beng", "Gujarati (ગુજરાતી)": "guj_Gujr", "Punjabi (ਪੰਜਾਬੀ)": "pan_Guru", "Odia (ଓଡ଼ିଆ)": "ory_Orya", "Assamese (অসমীয়া)": "asm_Beng",
    "Urdu (اردو)": "urd_Arab", "Sanskrit (संस्कृतम्)": "san_Deva", "Nepali (नेपाली)": "npi_Deva", "Sindhi (سنڌي)": "snd_Arab", "Sinhala (සිංහල)": "sin_Sinh", "French (Français)": "fra_Latn",
    "German (Deutsch)": "deu_Latn", "Spanish (Español)": "spa_Latn", "Chinese (中文)": "zho_Hans", "Japanese (日本語)": "jpn_Jpan", "Arabic (العربية)": "arb_Arab"}
NLLB_LANGS.update(EXTRA_LANGS)

S = {"cuda": False, "gpu": None, "vram_gb": 0, "torch": None, "started": None,
     "models": {"llm": {"name": None, "state": "pending", "device": None, "sec": None, "err": None}, "nllb": {"name": NLLB_MODEL, "state": "pending", "device": None, "sec": None, "err": None},
                "embed": {"name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "state": "pending", "device": None, "sec": None, "err": None},
                "rerank": {"name": "cross-encoder/ms-marco-MiniLM-L-6-v2", "state": "pending", "device": None, "sec": None, "err": None}},
     "stats": {"tok_s": None, "translate_ms": None, "translations": 0, "llm_calls": 0}}
_M = {"llm": None, "tok": None, "nllb": None, "nllb_tok": None, "embed": None, "rerank": None}
_LOCK = threading.Lock(); _GEN = threading.Lock()

def _cache_db():
    c = sqlite3.connect(DB_PATH, timeout=30); c.execute("PRAGMA journal_mode=WAL;"); c.execute("CREATE TABLE IF NOT EXISTS tr_cache(k TEXT PRIMARY KEY, v TEXT)"); return c
_TC = {}

def _probe():
    try:
        import torch
        S["torch"] = torch.__version__; S["cuda"] = bool(torch.cuda.is_available())
        if S["cuda"]: p = torch.cuda.get_device_properties(0); S["gpu"] = p.name; S["vram_gb"] = round(p.total_memory / 2**30, 1)
    except Exception as e: S["torch"] = f"unavailable: {e}"

def vram_used():
    try:
        import torch
        if S["cuda"]: return round(torch.cuda.memory_allocated() / 2**30, 2), round(torch.cuda.memory_reserved() / 2**30, 2)
    except Exception: pass
    return 0, 0

def status():
    u, r = vram_used(); return {**{k: S[k] for k in ("cuda", "gpu", "vram_gb", "torch")}, "vram_used_gb": u, "vram_reserved_gb": r, "models": S["models"], "stats": S["stats"], "uptime_s": round(time.time() - (S["started"] or time.time()))}

def _load_nllb():
    m = S["models"]["nllb"]; t = time.time()
    try:
        import torch; from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        m["state"] = "loading"; tok = AutoTokenizer.from_pretrained(NLLB_MODEL, token=HF_TOKEN or None)
        mdl = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL, torch_dtype=torch.float16 if S["cuda"] else torch.float32, token=HF_TOKEN or None)
        dev = "cuda" if S["cuda"] else "cpu"; mdl = mdl.to(dev).eval(); _M["nllb"], _M["nllb_tok"] = mdl, tok; m.update(state="ready", device=dev, sec=round(time.time() - t, 1), err=None)
    except Exception as e: m.update(state="failed", err=str(e)[:300])

def _load_embed():
    m = S["models"]["embed"]; t = time.time()
    try:
        from sentence_transformers import SentenceTransformer
        m["state"] = "loading"; dev = "cuda" if S["cuda"] else "cpu"; _M["embed"] = SentenceTransformer(m["name"], device=dev); m.update(state="ready", device=dev, sec=round(time.time() - t, 1), err=None)
        try:
            import rag; rag.warm()
        except Exception: pass
    except Exception as e: m.update(state="failed", err=str(e)[:300])

def _load_rerank():
    m = S["models"]["rerank"]; t = time.time()
    try:
        from sentence_transformers import CrossEncoder
        m["state"] = "loading"; dev = "cuda" if S["cuda"] else "cpu"; _M["rerank"] = CrossEncoder(m["name"], device=dev, max_length=384); m.update(state="ready", device=dev, sec=round(time.time() - t, 1), err=None)
    except Exception as e: m.update(state="failed", err=str(e)[:300])
def rerank(q, passages):
    """Cross-encoder relevance scores (higher = better) or None when the reranker is not loaded."""
    import numpy as np
    if _M["rerank"] is None or not passages: return None
    return np.asarray(_M["rerank"].predict([(q, p) for p in passages], batch_size=32, show_progress_bar=False), dtype="float32")

def _download(name, m):
    """Download the weights first (with visible progress) so 'loading' never hides a 15 GB download."""
    from huggingface_hub import snapshot_download, HfApi, constants
    try: import hf_transfer; os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    except Exception: pass
    pats = ["*.json", "*.safetensors", "*.txt", "*.model", "tokenizer*"]
    try: info = HfApi().model_info(name, files_metadata=True, token=HF_TOKEN or None); m["total_gb"] = round(sum((x.size or 0) for x in info.siblings if x.rfilename.endswith((".safetensors", ".json", ".txt", ".model"))) / 2**30, 2)
    except Exception: m["total_gb"] = None
    root = os.path.join(constants.HF_HUB_CACHE, "models--" + name.replace("/", "--")); stop = threading.Event()
    def poll():
        while not stop.is_set():
            try: m["done_gb"] = round(sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(root) for f in fs) / 2**30, 2)
            except Exception: pass
            stop.wait(1.5)
    threading.Thread(target=poll, daemon=True).start(); m.update(state="downloading", done_gb=0)
    try: return snapshot_download(name, allow_patterns=pats, token=HF_TOKEN or None, max_workers=8)
    finally: stop.set()

def _load_llm():
    m = S["models"]["llm"]; t = time.time()
    try:
        import torch; from transformers import AutoTokenizer, AutoModelForCausalLM
        if not S["cuda"]: raise RuntimeError("No CUDA GPU in this runtime. In Colab: Runtime > Change runtime type > T4 GPU, then restart.")
        vram = S["vram_gb"]
        ladder = [MODEL_NAME] if MODEL_NAME else (["Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-3B-Instruct"] if vram >= 22 else ["Qwen/Qwen2.5-3B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct"] if vram >= 8 else ["Qwen/Qwen2.5-1.5B-Instruct", "Qwen/Qwen2.5-0.5B-Instruct"])
        last = None; dt = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16      # T4 (7.5) has no real bf16: is_bf16_supported() says True by emulation, which is slow and can produce garbage
        for name in ladder:
            try:
                m.update(state="downloading", name=name, err=None); path = _download(name, m)
                m.update(state="loading"); tok = AutoTokenizer.from_pretrained(path)
                mdl = AutoModelForCausalLM.from_pretrained(path, torch_dtype=dt, device_map={"": 0}, low_cpu_mem_usage=True).eval(); _M["llm"], _M["tok"] = mdl, tok
                m.update(state="warming")
                def _ok(mm):
                    pr = tok.apply_chat_template([{"role": "user", "content": "Reply in one short sentence: what is the capital of France?"}], tokenize=False, add_generation_prompt=True); e = tok(pr, return_tensors="pt").to("cuda:0")
                    with torch.inference_mode(): o = mm.generate(**e, max_new_tokens=14, do_sample=False)
                    return "paris" in tok.decode(o[0][e["input_ids"].shape[1]:], skip_special_tokens=True).lower()
                if not _ok(mdl) and dt != torch.float32:          # the half-precision output was not sane: reload in float32 (slower but correct)
                    m.update(state="loading", err="half precision gave bad text; reloading in float32"); del mdl; torch.cuda.empty_cache(); dt = torch.float32
                    mdl = AutoModelForCausalLM.from_pretrained(path, torch_dtype=dt, device_map={"": 0}, low_cpu_mem_usage=True).eval(); _M["llm"] = mdl; m.update(state="warming", err=None)
                m.update(state="ready", device="cuda:0", sec=round(time.time() - t, 1), err=None, quant=str(dt).replace("torch.", ""))
                threading.Thread(target=_load_draft, args=(name, path, tok, dt), daemon=True).start(); return
            except Exception as e:
                last = e; _M["llm"] = None; m.update(err=f"{name}: {str(e)[:200]}")
                try: torch.cuda.empty_cache()
                except Exception: pass
        raise last or RuntimeError("no model loaded")
    except Exception as e: m.update(state="failed", err=str(e)[:300])

def _load_draft(name, path, tok, dt):
    """Speculative decoding: a 0.5B Qwen drafts tokens and the main model checks them in one pass. Kept only when it measures faster (>= 1.15x) and gives sane text."""
    import torch
    D = S.setdefault("draft", {"state": "off", "name": None, "speedup": None, "err": None})
    try:
        if not ("Qwen2.5-3B" in name and S["vram_gb"] >= 8): D.update(state="off", err="only used with the 3B model"); return
        from transformers import AutoModelForCausalLM
        dn = "Qwen/Qwen2.5-0.5B-Instruct"; D.update(state="loading", name=dn); dp = _download(dn, {})
        dm = AutoModelForCausalLM.from_pretrained(dp, torch_dtype=dt, device_map={"": 0}, low_cpu_mem_usage=True).eval(); mdl = _M["llm"]
        pr = tok.apply_chat_template([{"role": "user", "content": "List three tips for keeping stock levels healthy in a retail outlet."}], tokenize=False, add_generation_prompt=True); e = tok(pr, return_tensors="pt").to("cuda:0")
        def run(**kw):
            torch.cuda.synchronize(); t0 = time.time()
            with _GEN, torch.inference_mode(): o = mdl.generate(**e, max_new_tokens=48, do_sample=False, pad_token_id=tok.eos_token_id, **kw)
            torch.cuda.synchronize(); return time.time() - t0, tok.decode(o[0][e["input_ids"].shape[1]:], skip_special_tokens=True)
        run(); run(assistant_model=dm)                                   # warm both paths
        t1, a1 = run(); t2, a2 = run(assistant_model=dm); sp = t1 / max(t2, 1e-3)
        if sp >= 1.15 and len(a2.strip()) > 20 and a2.strip()[:30] == a1.strip()[:30]: _M["draft"] = dm; D.update(state="ready", speedup=round(sp, 2), err=None)
        else: del dm; torch.cuda.empty_cache(); D.update(state="off", speedup=round(sp, 2), err="not faster on this GPU, so it is not used")
    except Exception as ex: _M["draft"] = None; D.update(state="off", err=str(ex)[:200])
def start():
    """Called once at server start. NLLB + embeddings load in one thread, the LLM download/load runs in parallel, so the UI is usable immediately."""
    if S["started"]: return
    S["started"] = time.time(); _probe()
    threading.Thread(target=lambda: (_load_nllb(), _load_embed(), _load_rerank()), daemon=True).start(); threading.Thread(target=_load_llm, daemon=True).start()

# ---------------------------------------------------------------- translation (NLLB-200 only)
def code_of(lang): return lang if lang in NLLB_LANGS.values() else NLLB_LANGS.get(lang, "eng_Latn")
def detect(text):
    if not text: return "eng_Latn"
    ex = extra_detect(text)
    if ex: return ex
    for ch in text:
        for lo, hi, c in (("஀", "௿", "tam_Taml"), ("ऀ", "ॿ", "hin_Deva"), ("ఀ", "౿", "tel_Telu"), ("ಀ", "೿", "kan_Knda"), ("ഀ", "ൿ", "mal_Mlym"), ("ঀ", "৿", "ben_Beng"), ("઀", "૿", "guj_Gujr"), ("਀", "੿", "pan_Guru"), ("଀", "୿", "ory_Orya"), ("؀", "ۿ", "arb_Arab")):
            if lo <= ch <= hi: return c
    return "eng_Latn"
def _split(text, limit=300):
    parts = re.split(r"(?<=[.!?।。؟])\s+", str(text).strip()); out, cur = [], ""
    for x in parts:
        if cur and len(cur) + len(x) + 1 > limit: out.append(cur); cur = x
        else: cur = (cur + " " + x).strip()
    if cur: out.append(cur)
    return out or [str(text)[:limit]]
def _tid(tok, code):
    try:
        i = tok.convert_tokens_to_ids(code)
        if i is not None and i != tok.unk_token_id: return i
    except Exception: pass
    try: return tok.lang_code_to_id[code]
    except Exception: return None
def _gen_batch(segs, src, tgt, bs=32, beams=2):
    import torch
    mdl, tok = _M["nllb"], _M["nllb_tok"]; tok.src_lang = src; fid = _tid(tok, tgt); out = [None] * len(segs); order = sorted(range(len(segs)), key=lambda i: len(segs[i]))
    for b in range(0, len(order), bs):
        idx = order[b:b + bs]; enc = tok([segs[i] for i in idx], return_tensors="pt", padding=True, truncation=True, max_length=200).to(mdl.device)
        with torch.inference_mode():
            g = mdl.generate(**enc, forced_bos_token_id=fid, max_new_tokens=int(min(256, enc["input_ids"].shape[1] * 1.5 + 12)), num_beams=beams, do_sample=False,
                             no_repeat_ngram_size=4, repetition_penalty=1.12, early_stopping=True)
        for i, o in zip(idx, tok.batch_decode(g, skip_special_tokens=True)): out[i] = o.strip()
    return out
def ready(): return S["models"]["nllb"]["state"] == "ready"

# ---- protected tokens: ids, numbers, units, money, urls and code are never sent through the model (it garbles them) and are put back afterwards
_PROT = re.compile(r"`[^`]+`|https?://\S+|[\w.+-]+@[\w-]+\.[\w.]+|\b[A-Z]{2,6}-[A-Z]?\d{2,}\b|#\d+|[$€£₹]\s?\d[\d,]*(?:\.\d+)?[kKmM]?|\d[\d,]*(?:\.\d+)?\s?(?:%|nm|NM|kn|kg|km/h|km|TEU|USD|INR|mm|h|d)?(?![\w])")
_TOK = "Q{}Z"
def _protect(t):
    keep = []
    def rep(m): keep.append(m.group(0)); return _TOK.format(len(keep) - 1)
    return _PROT.sub(rep, t), keep
def _restore(t, keep):
    ok = True
    for i, v in enumerate(keep):
        tk = _TOK.format(i)
        if tk not in t:
            m = re.search(r"Q\s?" + str(i) + r"\s?Z", t)
            if m: t = t[:m.start()] + tk + t[m.end():]
            else: ok = False
        t = t.replace(tk, v.strip("`") if v.startswith("`") else v)
    return t, ok
def _loops(o, src):
    """True when the output looks like a hallucination: far longer than the source, or a repeating phrase."""
    if len(o) > 3.2 * len(src) + 30: return True
    w = o.split()
    return len(w) > 8 and len(set(w)) < len(w) * 0.35
def _script_ok(o, code):
    blocks = {"hin_Deva": ("ऀ", "ॿ"), "tam_Taml": ("஀", "௿"), "tel_Telu": ("ఀ", "౿"), "kan_Knda": ("ಀ", "೿"), "mal_Mlym": ("ഀ", "ൿ"), "ben_Beng": ("ঀ", "৿"), "guj_Gujr": ("઀", "૿"), "pan_Guru": ("਀", "੿"), "arb_Arab": ("؀", "ۿ"), "urd_Arab": ("؀", "ۿ"), "rus_Cyrl": ("Ѐ", "ӿ"), "ell_Grek": ("Ͱ", "Ͽ"), "heb_Hebr": ("֐", "׿"), "tha_Thai": ("฀", "๿"), "kor_Hang": ("가", "힣"), "jpn_Jpan": ("぀", "ヿ"), "zho_Hans": ("一", "鿿"), "zho_Hant": ("一", "鿿")}
    r = blocks.get(code)
    if not r: return True
    letters = [ch for ch in o if ch.isalpha()]
    return not letters or sum(1 for ch in letters if r[0] <= ch <= r[1]) / len(letters) > 0.3
_MD = re.compile(r"^(\s*(?:[-*•]\s+|\d+[.)]\s+|#{1,6}\s+|>\s+)?)(.*?)(\s*)$")
def _units(text):
    """Split markdown/plain text into [(prefix, body, suffix, kind)] translation units. Tables are split per cell, bold markers are kept around the unit."""
    units = []
    for line in str(text).split("\n"):
        if not line.strip(): units.append(("", "", "", "blank")); continue
        if line.strip().startswith("|") and line.count("|") >= 2:
            if re.fullmatch(r"[\s|:-]+", line): units.append((line, "", "", "raw")); continue
            cells = line.strip().strip("|").split("|"); units.append(("|", [c.strip() for c in cells], "|", "row")); continue
        m = _MD.match(line); pre, body, suf = m.group(1), m.group(2), m.group(3); wrap = ""
        if body.startswith("**") and body.endswith("**") and body.count("**") == 2: wrap = "**"; body = body[2:-2]
        body = body.replace("**", "")
        units.append((pre + wrap, body, wrap + suf, "line"))
    return units
def _translate_segments(segs, src, tgt):
    """segs: raw English segments. Returns translated, with protected tokens, quality gates and retries."""
    prot = [_protect(x) for x in segs]; out = _gen_batch([p[0] for p in prot], src, tgt); final = [None] * len(segs); retry = []
    for i, ((p, keep), o) in enumerate(zip(prot, out)):
        if not o or _loops(o, p) or not _script_ok(o, tgt): retry.append(i); continue
        r, ok = _restore(o, keep)
        if not ok: retry.append(i); continue
        final[i] = r
    if retry:    # second pass: greedy, no protection (the model sees the digits itself); still gated
        o2 = _gen_batch([segs[i] for i in retry], src, tgt, bs=16, beams=1)
        for i, o in zip(retry, o2):
            final[i] = o if o and not _loops(o, segs[i]) and _script_ok(o, tgt) else segs[i]
    return final
_CV = "v3"
def translate_many(texts, tgt="eng_Latn", src="eng_Latn"):
    """Batch translate with a persistent cache. Markdown-aware, protects ids/numbers/units, gates the model output. Returns (list, error|None)."""
    src, tgt = code_of(src), code_of(tgt)
    if src == tgt: return list(texts), None
    if not ready(): return list(texts), f"NLLB-200 is {S['models']['nllb']['state']}" + (f": {S['models']['nllb']['err']}" if S["models"]["nllb"]["err"] else "")
    res = [None] * len(texts); need = {}; t0 = time.time()
    for i, tx in enumerate(texts):
        if not tx or not str(tx).strip(): res[i] = tx; continue
        k = hashlib.md5(f"{_CV}|{src}|{tgt}|{tx}".encode()).hexdigest(); hit = _TC.get(k)
        if hit is None:
            try:
                with _LOCK: r = _cache_db().execute("SELECT v FROM tr_cache WHERE k=?", (k,)).fetchone()
                hit = r[0] if r else None
            except Exception: hit = None
        if hit is not None: res[i] = hit; _TC[k] = hit
        else: need.setdefault(k, []).append(i)
    if need:
        keys = list(need); plans = {}; segs = []
        for k in keys:
            units = _units(texts[need[k][0]]); plan = []
            for pre, body, suf, kind in units:
                if kind == "row":
                    ids = []
                    for c in body:
                        ss = [x for x in _split(c)] if re.search(r"[A-Za-z]{3}", c) else []
                        ids.append((c, [len(segs) + j for j in range(len(ss))])); segs.extend(ss)
                    plan.append((pre, ids, suf, kind))
                elif kind == "line" and re.search(r"[A-Za-z]{3}", body):
                    ss = _split(body); plan.append((pre, (body, [len(segs) + j for j in range(len(ss))]), suf, kind)); segs.extend(ss)
                else: plan.append((pre, body, suf, "keep" if kind != "row" else kind))
            plans[k] = plan
        with _GEN:
            try: outs = _translate_segments(segs, src, tgt) if segs else []
            except Exception as e: return [t if r is None else r for t, r in zip(texts, res)], f"NLLB error: {str(e)[:160]}"
        def cell(c, idx): return " ".join(outs[j] for j in idx) if idx else c
        try:
            cdb = _cache_db()
            for k in keys:
                lines = []
                for pre, body, suf, kind in plans[k]:
                    if kind == "blank": lines.append("")
                    elif kind == "raw": lines.append(pre)
                    elif kind == "row": lines.append("| " + " | ".join(cell(c, idx) for c, idx in body) + " |")
                    elif kind == "line": lines.append(pre + cell(*body) + suf)
                    else: lines.append(pre + (body if isinstance(body, str) else "") + suf)
                v = "\n".join(lines).strip() or texts[need[k][0]]; _TC[k] = v
                for i in need[k]: res[i] = v
                cdb.execute("INSERT OR REPLACE INTO tr_cache VALUES(?,?)", (k, v))
            cdb.commit(); cdb.close()
        except Exception as e:
            return [t if r is None else r for t, r in zip(texts, res)], f"cache error: {str(e)[:120]}"
        S["stats"]["translate_ms"] = round((time.time() - t0) * 1000); S["stats"]["translations"] += len(segs)
    return [t if r is None else r for t, r in zip(texts, res)], None
def translate(text, tgt="eng_Latn", src=None):
    r, e = translate_many([text], tgt, src or detect(text)); return r[0], e

# ---------------------------------------------------------------- LLM
def llm_ready(): return S["models"]["llm"]["state"] == "ready"
class _Deg:
    """Stops generation when the model starts looping (the last 24 tokens use 3 or fewer distinct ids)."""
    def __init__(self, n0): self.n0 = n0
    def __call__(self, input_ids, scores, **kw):
        import torch; g = input_ids[0, self.n0:]; bad = g.shape[0] >= 24 and len(set(g[-24:].tolist())) <= 3
        return torch.full((input_ids.shape[0],), bool(bad), dtype=torch.bool, device=input_ids.device)
def llm_stream(messages, max_new_tokens=260, temperature=0.2):
    """Yields text pieces as they are generated on the GPU. Returns immediately (empty) when the model is not loaded."""
    if not llm_ready(): return
    import torch; from transformers import TextIteratorStreamer
    tok, mdl = _M["tok"], _M["llm"]; prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True); enc = tok(prompt, return_tensors="pt", truncation=True, max_length=3500).to(mdl.device)
    st = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=120); _dr = _M.get("draft") if temperature <= 0.01 else None; kw = dict(**enc, streamer=st, max_new_tokens=max_new_tokens, do_sample=temperature > 0.01, temperature=max(temperature, 0.01), top_p=.9, repetition_penalty=1.1, pad_token_id=tok.eos_token_id, stopping_criteria=__import__('transformers').StoppingCriteriaList([_Deg(enc['input_ids'].shape[1])]))
    if _dr is not None: kw["assistant_model"] = _dr
    def run():
        try:
            with _GEN, torch.inference_mode(): mdl.generate(**kw)
        except Exception as ex:
            if "assistant_model" in kw:                                  # speculative decoding failed: switch it off, answer normally
                _M["draft"] = None; S.setdefault("draft", {}).update(state="off", err=str(ex)[:160]); kw.pop("assistant_model")
                try:
                    with _GEN, torch.inference_mode(): mdl.generate(**kw)
                except Exception: st.on_finalized_text("", stream_end=True)
            else: st.on_finalized_text("", stream_end=True)
    th = threading.Thread(target=run, daemon=True); th.start(); t0 = time.time(); n = 0
    for piece in st:
        n += 1; yield piece
    th.join(); S["stats"]["llm_calls"] += 1; S["stats"]["tok_s"] = round(n / max(time.time() - t0, 1e-3), 1)
def llm_text(messages, **kw): return "".join(llm_stream(messages, **kw)).strip()

# ---------------------------------------------------------------- embeddings + RAG store
def embed(texts):
    import numpy as np
    if _M["embed"] is None: return None
    return np.asarray(_M["embed"].encode(list(texts), batch_size=64, normalize_embeddings=True, show_progress_bar=False), dtype="float32")
