"""Builds Milestone3/FranchiseOps_AI_v5.ipynb (the final Colab notebook) from the files in Milestone3/app.

The notebook is a GENERATED file: edit the source files, then run

    python Milestone3/tools/build_notebook.py

Every file becomes one `%%writefile` cell (so Colab re-creates the project), the vendor JavaScript travels as one base64 archive, taught_questions.csv is
written next to the server, and the last cells start the server, print the demo logins and the link. Outputs are empty and no secret is written:
secrets are read from Colab Secrets at run time."""
import base64, io, json, os, sys, tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
APP = os.path.join(ROOT, "app")
OUT = os.path.join(ROOT, "FranchiseOps_AI_v5.ipynb")
SKIP_DIRS = {"__pycache__", "runtime_data", "vendor"}
SKIP_FILES = {"server.log", ".env"}

def lines(s): return s.splitlines(keepends=True)
def code(src): return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": lines(src)}
def md(src): return {"cell_type": "markdown", "metadata": {}, "source": lines(src)}

def project_files():
    out = []
    for root, dirs, files in os.walk(APP):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f in SKIP_FILES or f.endswith((".pyc", ".db", ".log")): continue
            out.append(os.path.relpath(os.path.join(root, f), APP).replace(os.sep, "/"))
    return sorted(out, key=lambda r: (r.startswith("static/"), r))          # Python modules first, then the front end

def vendor_bundle():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t: t.add(os.path.join(APP, "static", "vendor"), arcname="vendor")
    b = base64.b64encode(buf.getvalue()).decode()
    return "\n".join("'" + b[i:i + 100] + "'" for i in range(0, len(b), 100))

INTRO = """# FranchiseOps AI - Milestone 3 (final application)

FastAPI + SQLite + JWT login with role-based access, six agents with upgraded simulators, and an AI Copilot that answers from **SQL** (every number) and **RAG** (FAISS + BM25 documents with numbered sources), plus Admin tools: Teach Copilot, Copilot insights, System check.

**Run order**
1. Run `FranchiseOpsAI_RAG_Builder.ipynb` first (it saves the PDFs and the chunk index to `MyDrive/FranchiseOps_AI/`).
2. Here: **Runtime -> Change runtime type -> T4 GPU**, add the Colab secrets below (key icon, *Notebook access* ON), then **Runtime -> Run all** and allow Google Drive access.
3. The last cells print the **demo logins** (one account per role) and the **Open the app** link.

| Secret | Used for |
|---|---|
| `JWT_SECRET` | signing login tokens (recommended; a random one is created if missing) |
| `ADMIN_PASSWORD` | password of the Admin account (recommended; a random one is printed in the log if missing) |
| `ADMIN_EMAIL_ID` | e-mail of the Admin (optional, default `admin@infosys.com`) |
| `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | Gmail sender and app password for recovery codes, reports and digests (optional) |
| `NGROK_AUTHTOKEN` | public link (recommended) |
| `HF_TOKEN` | faster model downloads (optional) |

Never type a password or token into a cell. All times are India Standard Time (IST)."""

SECRETS = '''# Colab Secrets -> environment variables (the server runs as a separate process and cannot read Colab Secrets itself)
import os
NAMES = ["JWT_SECRET", "ADMIN_PASSWORD", "ADMIN_EMAIL_ID", "EMAIL_ADDRESS", "EMAIL_PASSWORD", "NGROK_AUTHTOKEN", "HF_TOKEN", "SLACK_WEBHOOK_URL", "TEAMS_WEBHOOK_URL"]
try:
    from google.colab import userdata
    for n in NAMES:
        try: v = userdata.get(n)
        except Exception: v = None
        if v: os.environ[n] = str(v).strip(); print(f"[OK]      secret {n} is set")
        else: print(f"[missing] secret {n}")
except ImportError:
    print("Not running in Colab: using the environment variables that are already set.")
if not os.environ.get("ADMIN_PASSWORD"):
    print("\\nNo ADMIN_PASSWORD secret: the server creates a random Admin password and prints it below when it starts.")'''

START = '''# Start the app (server + background worker). The models load on the GPU inside the server process. All times are India Standard Time (IST).
import os, sys, subprocess, time, urllib.request, secrets, json
os.environ["TZ"] = "Asia/Kolkata"; time.tzset()
PERSIST = True      # True = the database (users, tickets, taught questions, saved chats) is backed up to MyDrive/franchise_ops_data every few minutes and restored after a runtime reset
USE_DRIVE = True    # mounts Google Drive so the app loads the chunks your RAG Builder notebook saved in MyDrive/FranchiseOps_AI. False = built-in knowledge pack only
DEMO_USERS = True   # True = one demo account per role with a RANDOM password printed below (nothing is stored in the code). False = only the Admin exists
os.environ["APP_KIND"] = "Franchise"; os.environ["RATE_LIMIT_OFF"] = "1"; os.environ["DEMO_USERS"] = "1" if DEMO_USERS else "0"
if PERSIST or USE_DRIVE:
    try: from google.colab import drive; drive.mount("/content/drive")
    except Exception as e: print("Drive not mounted:", e)
if PERSIST and os.path.isdir("/content/drive/MyDrive"): os.environ["DRIVE_DB_DIR"] = "/content/drive/MyDrive/franchise_ops_data/db"
os.environ.setdefault("INGEST_KEY", secrets.token_urlsafe(12))
if os.path.exists("/content/srv.pid"):
    try: os.kill(int(open("/content/srv.pid").read()), 9)
    except Exception: pass
subprocess.run("fuser -k 8000/tcp", shell=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"], cwd="/content/app", stdout=open("/content/server.log", "w"), stderr=subprocess.STDOUT)
open("/content/srv.pid", "w").write(str(srv.pid))
for _ in range(120):
    try: urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2); break
    except Exception: time.sleep(1)
else: print(open("/content/server.log").read()[-3000:]); raise SystemExit("server did not start")
print("Server is up (IST clock:", time.strftime("%d %b %Y %I:%M %p"), ")")
log = open("/content/server.log").read()
for ln in log.splitlines():
    if "initial admin password" in ln: print(ln)
p = "/content/app_data/.demo_logins.json"
if DEMO_USERS and os.path.exists(p):
    print("\\nDemo logins (one per role; the Admin uses your ADMIN_EMAIL_ID and ADMIN_PASSWORD):")
    for e, pw in json.load(open(p)).items(): print("  ", e.ljust(24), pw)'''

OPEN = '''import os
from IPython.display import HTML, display
links = []
# 1) ngrok: a normal public https link that works in any browser
try:
    from pyngrok import ngrok, conf
    token = (os.environ.get('NGROK_AUTHTOKEN') or '').strip()
    ngrok.kill(); conf.get_default().auth_token = token
    try: ngrok.set_auth_token(token)
    except Exception as e: print('ngrok token note (usually harmless):', str(e)[:90])
    links.append(("Open the app", ngrok.connect(8000).public_url, "ngrok link. If ngrok shows a notice page, click Visit Site."))
except Exception as e:
    print('ngrok link unavailable (add the NGROK_AUTHTOKEN secret):', e)
# 2) Colab's own proxy link as a backup
try:
    from google.colab import output
    links.append(("Backup: Colab link", output.eval_js("google.colab.kernel.proxyPort(8000, {'cache': false})"), "Works only in a browser signed in to the same Google account."))
except Exception as e:
    print('Colab proxy link unavailable:', e)
for label, url, note in links:
    display(HTML(f'<p><a href="{url}" target="_blank" style="font-size:18px">{label}</a><br><small>{url}<br>{note}</small></p>'))'''

STATUS = '''# Live GPU / model status (same data as Admin > GPU & models in the app)
import json, urllib.request
print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health")), indent=1))
!nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv'''

EVAL = '''# Optional, run once after the app is up: measures the Copilot's answer rate BEFORE and AFTER the intent and synonym fine-tune on the same live database.
# The result appears in the app under Admin > Copilot insights (reload that tab).
import os, sys, shutil, subprocess
APP, BEFORE = "/content/app", "/content/app_before"
shutil.rmtree(BEFORE, ignore_errors=True)
shutil.copytree(APP, BEFORE, ignore=shutil.ignore_patterns("static", "_orig", "__pycache__"))
for f in ("qa.py", "copilot_pro.py"): shutil.copy(f"{APP}/_orig/{f}", f"{BEFORE}/{f}")
shutil.copy(f"{APP}/copilot_eval.py", f"{BEFORE}/copilot_eval.py")
env = dict(os.environ, APP_KIND="Franchise")
for label, d in (("before", BEFORE), ("after", APP)):
    r = subprocess.run([sys.executable, "copilot_eval.py", label, d, "-v"], cwd=d, env=env, capture_output=True, text=True)
    print(r.stdout[-4000:]); print(r.stderr[-1000:])'''

def build():
    cells = [md(INTRO),
             code("!nvidia-smi -L || echo 'NO GPU: choose Runtime > Change runtime type > T4 GPU'"),
             code("!pip -q install fastapi 'uvicorn[standard]' python-multipart pyjwt bcrypt pandas numpy scikit-learn scipy vaderSentiment pdfplumber reportlab langgraph langdetect requests httpx transformers accelerate bitsandbytes sentence-transformers sentencepiece hf_transfer matplotlib huggingface_hub pyngrok\n!pip -q install prophet 2>/dev/null || echo 'prophet not installed (trend forecast will be used)'"),
             code("import os\nos.makedirs('/content/app/static', exist_ok=True)\nos.chdir('/content/app')"),
             code(SECRETS)]
    for rel in project_files():
        with open(os.path.join(APP, rel), encoding="utf-8", newline="") as f: body = f.read().replace("\r\n", "\n")
        if not body.endswith("\n"): body += "\n"
        cells.append(code(f"%%writefile /content/app/{rel}\n{body}"))
    csv_path = os.path.join(ROOT, "taught_questions.csv")
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig", newline="") as f: body = f.read().replace("\r\n", "\n")
        if not body.endswith("\n"): body += "\n"
        cells.append(code("%%writefile /content/app/taught_questions.csv\n" + body))
    cells.append(code("import base64, io, tarfile\nB64 = (\n" + vendor_bundle() + "\n)\ntarfile.open(fileobj=io.BytesIO(base64.b64decode(B64)), mode='r:gz').extractall('/content/app/static')\nprint('vendor files ready')"))
    cells += [code(START), code(OPEN), code(STATUS), code(EVAL)]
    nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4", "provenance": []}, "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f: json.dump(nb, f, indent=1, ensure_ascii=False); f.write("\n")
    print(f"wrote {os.path.normpath(OUT)}: {len(cells)} cells, {len(project_files())} files, {os.path.getsize(OUT) // 1024} KB")

if __name__ == "__main__":
    build()
