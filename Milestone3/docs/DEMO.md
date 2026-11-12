# Live demo script (10 minutes)

Start the notebook 15 minutes early, keep the ngrok link and the demo logins ready, and record a 2-minute backup video.

| Min | Show | How |
|---|---|---|
| 2.0 | Sign in as two roles, show a denied (403) action | Sign in as `admin`, then as the Staff demo login. Staff sees only AI Copilot and My Profile. Open `#admin` as Staff: the server answers 403 and the app redirects. |
| 1.5 | Admin dashboard and System check | Admin → Users & access (add, promote, lock), then Admin → System check: "Knowledge base (RAG)" shows the chunks. |
| 1.5 | Agents: one cycle, then one simulator | Command Center → Run agent cycle. Then Inventory → Simulator: change the seed, run twice, show the P10–P90 range and the three reorder rules. |
| 2.0 | Copilot SQL: typo, follow-up, chart | "which outlet has the lowst customer satisfaction", then "and the highest?", then "top 5 outlets by revenue" (chart). |
| 2.0 | Copilot RAG: sources, a taught question, "I do not know" | "What are the FSSAI licence requirements?" (numbered sources), one question from `taught_questions.csv`, then "What is the weather in Delhi?". |
| 1.0 | Evaluator questions and code Q&A | Admin → Copilot insights (answer rate before and after), `copilot_pro.py` `TUNED_INTENTS`, `sim_fr.py`, `rbac.py`. |
