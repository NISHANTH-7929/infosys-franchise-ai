# infosys-franchise-ai

Infosys Springboard Internship 7.0 (Batch 4) project.

| Milestone | Description |
| :--- | :--- |
| [Milestone 1](Milestone1/README.md) | User authentication portal (Streamlit, SQLite, bcrypt, JWT) |
| [Milestone 2](Milestone2/README.md) | FranchiseOps AI: FastAPI multi-user product with the Milestone 1 login, five roles (RBAC), Admin dashboard, Profile page, SQL Copilot and a redesigned front end |
| [Milestone 3](Milestone3/README.md) | The finished FranchiseOps AI: RAG knowledge base crawled from public sites, Copilot with SQL and RAG answers and numbered sources, 50 taught questions, tuned intents, upgraded agent simulators, and the Milestone 2 login, roles and Admin dashboard inside it |

**Building on Milestone 1:** Milestone 2 brings the Milestone 1 login into FastAPI (same e-mail and password validation rules, bcrypt, JWT; sign-in now locks after 5 wrong passwords; password recovery by an e-mailed 6-digit code). Secrets (`JWT_SECRET`, `ADMIN_PASSWORD`, Gmail and ngrok keys) live in Colab Secrets only; see `Milestone2/README.md`, section 1.
