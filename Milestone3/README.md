# FranchiseOps AI: Milestone 3

Infosys Springboard Internship 7.0, Batch 4. Mentor: Mohamedsipli M.
**Evaluation:** Wed 18 and Thu 19 Nov 2026, 06:30 to 07:30 PM IST (5 min presentation + 10 min demo per team).

**Stack:** FastAPI, SQLite, RAG (FAISS + BM25), JWT, Google Colab, ngrok.

## Team and tasks

| Member | Task | Files they touch |
|---|---|---|
| **Nishanth** | 150+ websites and PDFs into the RAG; Milestone 2 integration | `FranchiseOpsAI_RAG_Builder.ipynb`, `FranchiseOps_AI_v5.ipynb` |
| **Ayush** | Find 50+ questions the Copilot cannot answer and teach them (counter 50 / 50) | `taught_questions.csv` |
| **Akshita** | Fine-tune Copilot intents and synonyms; answer rate before / after | `copilot_pro.py` (`INTENTS`), `qa.py` (synonyms) |
| **Madhavi** | Improve every agent simulator | `sim_fr.py` |
| **Sidesh** | Authentication (JWT login, profile, RBAC, 403) and integration | auth / RBAC parts of the app |

## Folder contents

| Item | Purpose |
|---|---|
| `FranchiseOpsAI_RAG_Builder.ipynb` | Crawls websites and PDFs, saves them to `MyDrive/FranchiseOps_AI/rag_pdfs/`, builds FAISS and BM25 indexes. **Run first.** |
| `FranchiseOps_AI_v5.ipynb` | The finished app (agents, Copilot SQL + RAG, Admin). Run second. |
| `taught_questions.csv` | Taught questions: `question,answer,keywords` |
| `slides/` | Presentation (`.pptx` + `.pdf`, max 6 slides, text at least 24 pt) |
| `screenshots/` | Evidence images listed below |

## How to run

1. Colab: open the RAG notebook, T4 GPU, Runtime -> Run all, allow Drive access.
2. Open `FranchiseOps_AI_v5.ipynb` (T4 GPU, `USE_DRIVE = True`, `PERSIST = True`), Run all, open the printed link.
3. Secrets go in Colab **Secrets** (`JWT_SECRET`, `ADMIN_PASSWORD`, `NGROK_AUTHTOKEN`, ...). Never type a key into a cell.
4. Admin -> System check must show the knowledge-base chunks.

## Roles
_TODO (Sidesh): roles, privileges and the 403 demo action._

## How the Copilot uses SQL and RAG
_TODO: every number comes from SQL; knowledge questions use RAG with numbered sources [1] [2]; unsure -> "I do not know"._

## Knowledge base
_TODO (Nishanth): sources collected: **__**, chunks: **__**._

## Taught questions
_TODO (Ayush): **__ / 50** taught, see `taught_questions.csv`._

## Copilot fine-tuning
_TODO (Akshita): intents and synonyms added; answer rate before **__%** -> after **__%**._

## Simulator improvements
_TODO (Madhavi): per agent, what changed, assumptions, 10th-90th percentile, seed._

| Agent | Before | After |
|---|---|---|
| Inventory | | |
| Workforce | | |
| P&L | | |
| Marketing | | |
| Sentiment | | |
| Audit | | |

## Required screenshots (in `screenshots/`)
1. RAG notebook: 150+ sources and chunk count
2. Teach Copilot showing 50 / 50
3. Copilot answer with numbered sources [1] [2]
4. Each agent simulator, before and after
5. Admin -> Copilot insights
