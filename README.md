# infosys-franchise-ai

Infosys Springboard Internship 7.0 (Batch 4) project.

| Milestone | Description |
| :--- | :--- |
| [Milestone 1](Milestone1/README.md) | User authentication portal (Streamlit, SQLite, bcrypt, JWT) |
| [Milestone 2](Milestone2/README.md) | FranchiseOps AI: FastAPI multi-user product with the Milestone 1 login, five roles (RBAC), Admin dashboard, Profile page, SQL Copilot and a redesigned front end |

**Building on Milestone 1:** Milestone 2 brings the Milestone 1 login into FastAPI (same validation rules, bcrypt, JWT, 15-minute-style lockout became a 5-attempt lock, e-mail code recovery). Secrets (`JWT_SECRET`, `ADMIN_PASSWORD`, Gmail and ngrok keys) live in Colab Secrets only; see `Milestone2/README.md`, section 1.
