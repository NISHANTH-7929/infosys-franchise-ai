"""Copilot evaluation: answer rate before / after fine-tuning (Franchise).
Replays a fixed question list through the same layers the web app uses (copilot_pro.prepare -> analyst.py -> qa.py, no GPU, no LLM) and scores each reply:
  answered  the Copilot returned an exact SQL answer that is on topic (not 'unanswered', not a weak/unrelated match)
  correct   answered AND the SQL/the numbers shown match an independent ground-truth query on the live database
  idk       for questions the data cannot answer: the Copilot declined ('I do not know') instead of inventing a number
Two question sets: TUNE (used while adding intents/synonyms) and HOLD (paraphrases written beforehand and never used for tuning, so it measures generalisation).
Run from the notebook (it starts one process on the ORIGINAL code for 'before' and one on the tuned code for 'after'); results go to tables copilot_eval_runs / copilot_eval_items and show in Admin > Copilot insights."""
import os, re, sys, json, time, sqlite3, datetime

# (id, set, category, question, expect, checks)   expect: 'answer' | 'idk'     checks: sql=[regex all found in the SQL], truth=SQL whose first value must appear in the reply, empty=True when 'none found' is the right answer
def _b(i, s, cat, q, expect="answer", **chk): return dict(id=i, set=s, cat=cat, q=q, expect=expect, chk=chk)
TODAY, YEST, W7 = "substr(ts,1,10)=date('now','localtime')", "substr(ts,1,10)=date('now','localtime','-1 day')", "substr(ts,1,10)>=date('now','localtime','-6 day')"
OPEN = "status IN ('open','proposed')"
BENCH = [
 # ---- profit and cost
 _b("t01", "TUNE", "Profit & cost", "Which outlets are making a loss?", sql=[r"operating_costs"], empty=True),
 _b("t02", "TUNE", "Profit & cost", "Which outlet has the highest profit margin?", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY (revenue-operating_costs)/revenue DESC LIMIT 1"),
 _b("t03", "TUNE", "Profit & cost", "What is the profit of OUT-005?", sql=[r"operating_costs"], truth="SELECT CAST(ROUND(revenue-operating_costs,0) AS INT) FROM outlets WHERE outlet_id='OUT-005'"),
 _b("t04", "TUNE", "Profit & cost", "Show the top 5 most profitable outlets", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY revenue-operating_costs DESC LIMIT 1"),
 _b("t05", "TUNE", "Profit & cost", "What is the profit margin of OUT-012?", sql=[r"operating_costs"], truth="SELECT ROUND(100.0*(revenue-operating_costs)/revenue,1) FROM outlets WHERE outlet_id='OUT-012'"),
 _b("t06", "TUNE", "Profit & cost", "Which outlets have the highest operating costs?", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY operating_costs DESC LIMIT 1"),
 # ---- sales and transactions
 _b("t07", "TUNE", "Sales", "How much did we sell today?", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {TODAY}"),
 _b("t08", "TUNE", "Sales", "What were total sales yesterday?", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {YEST}"),
 _b("t09", "TUNE", "Sales", "How many transactions were there yesterday?", sql=[r"tx_count"], truth=f"SELECT SUM(tx_count) FROM sales WHERE {YEST}"),
 _b("t10", "TUNE", "Sales", "What is the average order value?", sql=[r"tx_count"], truth="SELECT ROUND(SUM(amount)/SUM(tx_count),2) FROM sales WHERE tx_count>0"),
 _b("t11", "TUNE", "Sales", "Total sales in the last 7 days", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {W7}"),
 _b("t12", "TUNE", "Sales", "Which outlet sold the most today?", sql=[r"\bsales\b"], truth=f"SELECT outlet_id FROM sales WHERE {TODAY} GROUP BY outlet_id ORDER BY SUM(amount) DESC LIMIT 1"),
 _b("t13", "TUNE", "Sales", "Which outlets make the most revenue per employee?", sql=[r"staff_headcount"], truth="SELECT outlet_id FROM outlets ORDER BY revenue*1.0/staff_headcount DESC LIMIT 1"),
 # ---- stock
 _b("t14", "TUNE", "Stock", "Which items are out of stock?", sql=[r"current_stock\s*<=?\s*0"], truth="SELECT outlet_id FROM inventory WHERE current_stock<=0 ORDER BY weekly_demand DESC LIMIT 1"),
 _b("t15", "TUNE", "Stock", "Which outlets have the most items below reorder level?", sql=[r"reorder_threshold"], truth="SELECT outlet_id FROM inventory WHERE current_stock<=reorder_threshold GROUP BY outlet_id ORDER BY COUNT(*) DESC, outlet_id LIMIT 1"),
 _b("t16", "TUNE", "Stock", "Show inventory by category", sql=[r"category"], truth="SELECT category FROM inventory GROUP BY category ORDER BY SUM(current_stock) DESC LIMIT 1"),
 _b("t17", "TUNE", "Stock", "Which SKUs have the highest weekly demand?", sql=[r"weekly_demand"], truth="SELECT sku_name FROM inventory ORDER BY weekly_demand DESC LIMIT 1"),
 # ---- campaigns
 _b("t18", "TUNE", "Campaigns", "Which campaigns are active right now?", sql=[r"end_date"], truth="SELECT campaign_id FROM marketing WHERE start_date<=date('now','localtime') AND end_date>=date('now','localtime') ORDER BY end_date, campaign_id LIMIT 1"),
 _b("t19", "TUNE", "Campaigns", "How many campaigns are running?", sql=[r"end_date"], truth="SELECT COUNT(*) FROM marketing WHERE start_date<=date('now','localtime') AND end_date>=date('now','localtime')"),
 _b("t20", "TUNE", "Campaigns", "Which marketing channel gives the best ROI?", sql=[r"GROUP BY channel"], truth="SELECT channel FROM marketing GROUP BY channel ORDER BY AVG(actual_roi) DESC LIMIT 1"),
 _b("t21", "TUNE", "Campaigns", "Which campaigns have already ended?", sql=[r"end_date"], truth="SELECT campaign_id FROM marketing WHERE end_date<date('now','localtime') ORDER BY end_date DESC, campaign_id LIMIT 1"),
 _b("t22", "TUNE", "Campaigns", "What is the total marketing budget?", sql=[r"budget"], truth="SELECT CAST(ROUND(SUM(budget),0) AS INT) FROM marketing"),
 # ---- audits
 _b("t23", "TUNE", "Audits", "Which outlets failed their audit?", sql=[r"audits"], truth="SELECT outlet_id FROM audits WHERE status IN ('Fail','Action Required') ORDER BY audit_date DESC, score, audit_id LIMIT 1"),
 _b("t24", "TUNE", "Audits", "What is the audit pass rate?", sql=[r"audits"], truth="SELECT ROUND(100.0*SUM(status='Pass')/COUNT(*),1) FROM audits"),
 _b("t25", "TUNE", "Audits", "Which outlets have the lowest average audit score?", sql=[r"audits"], truth="SELECT outlet_id FROM audits GROUP BY outlet_id ORDER BY AVG(score), outlet_id LIMIT 1"),
 _b("t26", "TUNE", "Audits", "Show audit violations by category", sql=[r"GROUP BY category"], truth="SELECT category FROM audits GROUP BY category ORDER BY SUM(violations) DESC, category LIMIT 1"),
 # ---- staff
 _b("t27", "TUNE", "Staff", "How many staff are absent today?", sql=[r"attendance"], truth=f"SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE status='Absent' AND {TODAY}"),
 _b("t28", "TUNE", "Staff", "Which outlet has the most staff?", sql=[r"staff_headcount"], truth="SELECT outlet_id FROM outlets ORDER BY staff_headcount DESC, outlet_id LIMIT 1"),
 _b("t29", "TUNE", "Staff", "Which staff have the lowest job satisfaction?", sql=[r"job_satisfaction"]),
 _b("t30", "TUNE", "Staff", "Which outlets are short of staff?", sql=[r"staffing_shortage"]),
 _b("t31", "TUNE", "Staff", "What is the average salary by role?", sql=[r"GROUP BY role"], truth="SELECT role FROM staff GROUP BY role ORDER BY AVG(salary) DESC LIMIT 1"),
 _b("t32", "TUNE", "Staff", "Who has the longest tenure?", sql=[r"tenure_years"]),
 _b("t33", "TUNE", "Staff", "How many cooks do we have?", sql=[r"role"], truth="SELECT COUNT(*) FROM staff WHERE role='Cook'"),
 _b("t34", "TUNE", "Staff", "Staff with more than 30 overtime hours", sql=[r"overtime_hrs\s*>"], ),
 _b("t35", "TUNE", "Staff", "Which staff are most likely to quit?", sql=[r"predicted_attrition_prob"], truth="SELECT staff_id FROM staff ORDER BY predicted_attrition_prob DESC LIMIT 1"),
 # ---- customers
 _b("t36", "TUNE", "Customers", "How many customers have not visited in over 30 days?", sql=[r"customers_fr"], truth="SELECT COUNT(*) FROM customers_fr WHERE days_since_last_visit>30"),
 _b("t37", "TUNE", "Customers", "Which outlets have the most lapsed customers?", sql=[r"customers_fr"], truth="SELECT outlet_id FROM customers_fr WHERE days_since_last_visit>30 GROUP BY outlet_id ORDER BY COUNT(*) DESC, outlet_id LIMIT 1"),
 _b("t38", "TUNE", "Customers", "Who are our top spending customers?", sql=[r"total_spend_90d"], truth="SELECT customer_id FROM customers_fr ORDER BY total_spend_90d DESC, customer_id LIMIT 1"),
 _b("t39", "TUNE", "Customers", "What is the average customer spend?", sql=[r"total_spend_90d"], truth="SELECT ROUND(AVG(total_spend_90d),2) FROM customers_fr"),
 _b("t40", "TUNE", "Customers", "How many customers do we have?", sql=[r"customers_fr"], truth="SELECT COUNT(*) FROM customers_fr"),
 # ---- feedback
 _b("t41", "TUNE", "Feedback", "Show reviews by star rating", sql=[r"GROUP BY rating"], truth="SELECT COUNT(*) FROM feedback WHERE rating=5"),
 _b("t42", "TUNE", "Feedback", "Which outlets have the lowest customer ratings?", sql=[r"feedback"], truth="SELECT outlet_id FROM feedback GROUP BY outlet_id HAVING COUNT(*)>=3 ORDER BY AVG(rating), outlet_id LIMIT 1"),
 _b("t43", "TUNE", "Feedback", "What are customers complaining about the most?", sql=[r"feedback"]),
 _b("t44", "TUNE", "Feedback", "Which outlets are below 3.5 customer satisfaction?", sql=[r"customer_satisfaction\s*<"], truth="SELECT COUNT(*) FROM outlets WHERE customer_satisfaction<3.5"),
 # ---- tickets
 _b("t45", "TUNE", "Tickets", "Open tickets by severity", sql=[r"GROUP BY severity"], truth=f"SELECT COUNT(*) FROM agent_actions WHERE {OPEN} AND severity='Critical'"),
 _b("t46", "TUNE", "Tickets", "Which tickets are overdue?", sql=[r"\bdue\b"], truth=f"SELECT action_id FROM agent_actions WHERE {OPEN} AND due<strftime('%Y-%m-%dT%H:%M:%S','now','localtime') ORDER BY due, action_id LIMIT 1"),
 _b("t47", "TUNE", "Tickets", "What is awaiting approval?", sql=[r"proposed"]),
 _b("t48", "TUNE", "Tickets", "How many critical tickets are open?", sql=[r"agent_actions"], truth=f"SELECT COUNT(*) FROM agent_actions WHERE {OPEN} AND severity='Critical'"),
 _b("t49", "TUNE", "Tickets", "Tickets by type", sql=[r"GROUP BY type"], truth=f"SELECT type FROM agent_actions WHERE {OPEN} GROUP BY type ORDER BY COUNT(*) DESC, type LIMIT 1"),
 # ---- outlets
 _b("t50", "TUNE", "Outlets", "Which city has the highest revenue?", sql=[r"GROUP BY location"], truth="SELECT location FROM outlets GROUP BY location ORDER BY SUM(revenue) DESC LIMIT 1"),
 _b("t51", "TUNE", "Outlets", "Which tier performs best?", sql=[r"GROUP BY tier"], truth="SELECT tier FROM outlets GROUP BY tier ORDER BY SUM(revenue) DESC LIMIT 1"),
 _b("t52", "TUNE", "Outlets", "How many outlets are in Mumbai?", sql=[r"outlets"], truth="SELECT COUNT(*) FROM outlets WHERE location='Mumbai'"),
 _b("t53", "TUNE", "Outlets", "Top 5 outlets by revenue", sql=[r"revenue"], truth="SELECT outlet_id FROM outlets ORDER BY revenue DESC LIMIT 1"),
 _b("t54", "TUNE", "Outlets", "Which outlets have the lowest customer satisfaction?", sql=[r"customer_satisfaction"], truth="SELECT outlet_id FROM outlets ORDER BY customer_satisfaction LIMIT 1"),
 _b("t55", "TUNE", "Outlets", "Which outlets have the most open tickets?", sql=[r"agent_actions"], truth=f"SELECT target FROM agent_actions WHERE {OPEN} AND target LIKE 'OUT-%' GROUP BY target ORDER BY COUNT(*) DESC, SUM(severity='Critical') DESC LIMIT 1"),
 _b("t56", "TUNE", "Outlets", "Overtime hours by outlet", sql=[r"overtime"], truth="SELECT outlet_id FROM staff GROUP BY outlet_id ORDER BY SUM(overtime_hrs) DESC LIMIT 1"),
 # ---- out of scope: the data cannot answer, the right reply is 'I do not know'
 _b("i01", "TUNE", "I do not know", "What is the weather in Delhi today?", "idk"),
 _b("i02", "TUNE", "I do not know", "What are our competitors charging?", "idk"),
 _b("i03", "TUNE", "I do not know", "Who is our cheapest supplier?", "idk"),
 _b("i04", "TUNE", "I do not know", "What is the best selling menu item?", "idk"),
 _b("i05", "TUNE", "I do not know", "What is the gender ratio of our staff?", "idk"),
 _b("i06", "TUNE", "I do not know", "What is the expiry date of milk?", "idk"),
 _b("i07", "TUNE", "I do not know", "How much GST did we pay last month?", "idk"),
 _b("i08", "TUNE", "I do not know", "What will our revenue be next year?", "idk"),
 _b("i09", "TUNE", "I do not know", "What is the phone number of STF-0012?", "idk"),
 _b("i10", "TUNE", "I do not know", "How much rent does OUT-004 pay?", "idk"),
 _b("i11", "TUNE", "I do not know", "How many Zomato orders did we get?", "idk"),
 _b("i12", "TUNE", "I do not know", "Which employees deserve a promotion?", "idk"),
 _b("i13", "TUNE", "I do not know", "How many units of chicken did we sell yesterday?", "idk"),
 _b("i14", "TUNE", "I do not know", "Which outlet has the best parking space?", "idk"),
 _b("i15", "TUNE", "I do not know", "How many chairs are there in OUT-010?", "idk"),
 # ================= held-out set: written before any tuning, paraphrases of the same needs, never used to design a pattern =================
 _b("h01", "HOLD", "Profit & cost", "Are any of our outlets operating at a loss?", sql=[r"operating_costs"], empty=True),
 _b("h02", "HOLD", "Profit & cost", "Rank the outlets by profit", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY revenue-operating_costs DESC LIMIT 1"),
 _b("h03", "HOLD", "Profit & cost", "What is the profit for OUT-020?", sql=[r"operating_costs"], truth="SELECT CAST(ROUND(revenue-operating_costs,0) AS INT) FROM outlets WHERE outlet_id='OUT-020'"),
 _b("h04", "HOLD", "Sales", "How much revenue did we make today?", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {TODAY}"),
 _b("h05", "HOLD", "Sales", "How much did we earn in the past 7 days?", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {W7}"),
 _b("h06", "HOLD", "Sales", "How many bills were generated yesterday?", sql=[r"tx_count"], truth=f"SELECT SUM(tx_count) FROM sales WHERE {YEST}"),
 _b("h07", "HOLD", "Sales", "What is the typical basket size?", sql=[r"tx_count"], truth="SELECT ROUND(SUM(amount)/SUM(tx_count),2) FROM sales WHERE tx_count>0"),
 _b("h08", "HOLD", "Stock", "Show me the SKUs that have sold out", sql=[r"current_stock\s*<=?\s*0"], truth="SELECT outlet_id FROM inventory WHERE current_stock<=0 ORDER BY weekly_demand DESC LIMIT 1"),
 _b("h09", "HOLD", "Stock", "Which branches have the most low-stock items?", sql=[r"reorder_threshold"], truth="SELECT outlet_id FROM inventory WHERE current_stock<=reorder_threshold GROUP BY outlet_id ORDER BY COUNT(*) DESC, outlet_id LIMIT 1"),
 _b("h10", "HOLD", "Campaigns", "Show me the promotions running at the moment", sql=[r"end_date"], truth="SELECT campaign_id FROM marketing WHERE start_date<=date('now','localtime') AND end_date>=date('now','localtime') ORDER BY end_date, campaign_id LIMIT 1"),
 _b("h11", "HOLD", "Campaigns", "Which promotions have expired?", sql=[r"end_date"], truth="SELECT campaign_id FROM marketing WHERE end_date<date('now','localtime') ORDER BY end_date DESC, campaign_id LIMIT 1"),
 _b("h12", "HOLD", "Campaigns", "Which advertising platform performs best on return?", sql=[r"GROUP BY channel"], truth="SELECT channel FROM marketing GROUP BY channel ORDER BY AVG(actual_roi) DESC LIMIT 1"),
 _b("h13", "HOLD", "Audits", "Which branches did not pass their inspection?", sql=[r"audits"], truth="SELECT outlet_id FROM audits WHERE status IN ('Fail','Action Required') ORDER BY audit_date DESC, score, audit_id LIMIT 1"),
 _b("h14", "HOLD", "Audits", "What percentage of audits passed?", sql=[r"audits"], truth="SELECT ROUND(100.0*SUM(status='Pass')/COUNT(*),1) FROM audits"),
 _b("h15", "HOLD", "Staff", "How many employees were absent today?", sql=[r"attendance"], truth=f"SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE status='Absent' AND {TODAY}"),
 _b("h16", "HOLD", "Staff", "Which outlet employs the most people?", sql=[r"staff_headcount"], truth="SELECT outlet_id FROM outlets ORDER BY staff_headcount DESC, outlet_id LIMIT 1"),
 _b("h17", "HOLD", "Staff", "Which employees seem unhappy at work?", sql=[r"job_satisfaction"]),
 _b("h18", "HOLD", "Staff", "Which outlets are understaffed?", sql=[r"staffing_shortage"]),
 _b("h19", "HOLD", "Customers", "How many guests have not come back in a month?", sql=[r"customers_fr"], truth="SELECT COUNT(*) FROM customers_fr WHERE days_since_last_visit>30"),
 _b("h20", "HOLD", "Customers", "Which outlets have the most inactive customers?", sql=[r"customers_fr"], truth="SELECT outlet_id FROM customers_fr WHERE days_since_last_visit>30 GROUP BY outlet_id ORDER BY COUNT(*) DESC, outlet_id LIMIT 1"),
 _b("h21", "HOLD", "Customers", "Who are the highest spending shoppers?", sql=[r"total_spend_90d"], truth="SELECT customer_id FROM customers_fr ORDER BY total_spend_90d DESC, customer_id LIMIT 1"),
 _b("h22", "HOLD", "Feedback", "Which stores have the best average star rating?", sql=[r"feedback"], truth="SELECT outlet_id FROM feedback GROUP BY outlet_id HAVING COUNT(*)>=3 ORDER BY AVG(rating) DESC, outlet_id LIMIT 1"),
 _b("h23", "HOLD", "Tickets", "Break down the open tickets by severity please", sql=[r"GROUP BY severity"], truth=f"SELECT COUNT(*) FROM agent_actions WHERE {OPEN} AND severity='Critical'"),
 _b("h24", "HOLD", "Tickets", "Any overdue tasks?", sql=[r"\bdue\b"], truth=f"SELECT action_id FROM agent_actions WHERE {OPEN} AND due<strftime('%Y-%m-%dT%H:%M:%S','now','localtime') ORDER BY due, action_id LIMIT 1"),
 _b("h25", "HOLD", "Tickets", "Which actions need my approval?", sql=[r"proposed"]),
 _b("h26", "HOLD", "Outlets", "Which town has the highest sales?", sql=[r"GROUP BY location"], truth="SELECT location FROM outlets GROUP BY location ORDER BY SUM(revenue) DESC LIMIT 1"),
 _b("h27", "HOLD", "Outlets", "Which format of store performs worst?", sql=[r"GROUP BY tier"], truth="SELECT tier FROM outlets GROUP BY tier ORDER BY SUM(revenue) LIMIT 1"),
 _b("h28", "HOLD", "Typos", "Which outlets are makin a loss?", sql=[r"operating_costs"], empty=True),
 _b("h29", "HOLD", "Typos", "Show the profit by outlte", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY revenue-operating_costs DESC LIMIT 1"),
 _b("h30", "HOLD", "Typos", "How many staf were absent today?", sql=[r"attendance"], truth=f"SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE status='Absent' AND {TODAY}"),
 _b("hi1", "HOLD", "I do not know", "What's the temperature in Mumbai right now?", "idk"),
 _b("hi2", "HOLD", "I do not know", "How do our prices compare with rival chains?", "idk"),
 _b("hi3", "HOLD", "I do not know", "What is our most popular dish?", "idk"),
 _b("hi4", "HOLD", "I do not know", "Which vendor delivers late the most?", "idk"),
 _b("hi5", "HOLD", "I do not know", "What is the average age of our customers?", "idk"),
 _b("hi6", "HOLD", "I do not know", "What is the monthly electricity bill of OUT-003?", "idk"),
 _b("hi7", "HOLD", "I do not know", "Which outlet has the best view from the dining area?", "idk"),
 _b("hi8", "HOLD", "I do not know", "How many tables does OUT-010 have?", "idk"),
 # ================= BLIND set: written AFTER the tuning was frozen and run once, with no changes made afterwards =================
 _b("b01", "BLIND", "Profit & cost", "Which stores lost money?", sql=[r"operating_costs"], empty=True),
 _b("b02", "BLIND", "Outlets", "What is the total revenue across all outlets?", sql=[r"SUM\(revenue\)"], truth="SELECT CAST(ROUND(SUM(revenue),0) AS INT) FROM outlets"),
 _b("b03", "BLIND", "Sales", "How much did the stores bring in yesterday?", sql=[r"\bsales\b"], truth=f"SELECT CAST(ROUND(SUM(amount),0) AS INT) FROM sales WHERE {YEST}"),
 _b("b04", "BLIND", "Sales", "Number of transactions today", sql=[r"tx_count"], truth=f"SELECT SUM(tx_count) FROM sales WHERE {TODAY}"),
 _b("b05", "BLIND", "Profit & cost", "Which branch has the lowest profit?", sql=[r"operating_costs"], truth="SELECT outlet_id FROM outlets ORDER BY revenue-operating_costs LIMIT 1"),
 _b("b06", "BLIND", "Stock", "Give me the SKUs with zero stock", sql=[r"current_stock\s*<=?\s*0"], truth="SELECT outlet_id FROM inventory WHERE current_stock<=0 ORDER BY weekly_demand DESC LIMIT 1"),
 _b("b07", "BLIND", "Campaigns", "Campaigns that are currently live", sql=[r"end_date"], truth="SELECT campaign_id FROM marketing WHERE start_date<=date('now','localtime') AND end_date>=date('now','localtime') ORDER BY end_date, campaign_id LIMIT 1"),
 _b("b08", "BLIND", "Campaigns", "Which marketing channel has the weakest return?", sql=[r"GROUP BY channel"], truth="SELECT channel FROM marketing GROUP BY channel ORDER BY AVG(actual_roi) LIMIT 1"),
 _b("b09", "BLIND", "Audits", "List the audits that failed", sql=[r"audits"], truth="SELECT audit_id FROM audits WHERE status IN ('Fail','Action Required') ORDER BY audit_date DESC, score, audit_id LIMIT 1"),
 _b("b10", "BLIND", "Audits", "How many audits did we do?", sql=[r"audits"], truth="SELECT COUNT(*) FROM audits"),
 _b("b11", "BLIND", "Staff", "Which employees are absent today?", sql=[r"attendance"]),
 _b("b12", "BLIND", "Staff", "Which outlet has the fewest employees?", sql=[r"staff_headcount"], truth="SELECT outlet_id FROM outlets ORDER BY staff_headcount, outlet_id LIMIT 1"),
 _b("b13", "BLIND", "Staff", "Which staff have the highest attrition risk?", sql=[r"predicted_attrition_prob"], truth="SELECT staff_id FROM staff ORDER BY predicted_attrition_prob DESC LIMIT 1"),
 _b("b14", "BLIND", "Feedback", "What is the average review rating?", sql=[r"AVG\(rating\)"], truth="SELECT ROUND(AVG(rating),2) FROM feedback"),
 _b("b15", "BLIND", "Feedback", "Which outlet got the best reviews?", sql=[r"feedback"], truth="SELECT outlet_id FROM feedback GROUP BY outlet_id HAVING COUNT(*)>=3 ORDER BY AVG(rating) DESC, outlet_id LIMIT 1"),
 _b("b16", "BLIND", "Tickets", "How many critical alerts are open right now?", sql=[r"agent_actions"], truth=f"SELECT COUNT(*) FROM agent_actions WHERE {OPEN} AND severity='Critical'"),
 _b("b17", "BLIND", "Tickets", "Show open tickets by outlet", sql=[r"agent_actions"], truth=f"SELECT target FROM agent_actions WHERE {OPEN} AND target LIKE 'OUT-%' GROUP BY target ORDER BY COUNT(*) DESC, SUM(severity='Critical') DESC LIMIT 1"),
 _b("b18", "BLIND", "Outlets", "Which city has the lowest revenue?", sql=[r"GROUP BY location"], truth="SELECT location FROM outlets GROUP BY location ORDER BY SUM(revenue) LIMIT 1"),
 _b("b19", "BLIND", "Staff", "Average salary of store managers", sql=[r"salary"], truth="SELECT ROUND(AVG(salary),0) FROM staff WHERE role='Store Manager'"),
 _b("b20", "BLIND", "Outlets", "How many outlets does Pune have?", sql=[r"outlets"], truth="SELECT COUNT(*) FROM outlets WHERE location='Pune'"),
 _b("b21", "BLIND", "Outlets", "Tell me about OUT-010", sql=[r"outlets"], truth="SELECT outlet_name FROM outlets WHERE outlet_id='OUT-010'"),
 _b("b22", "BLIND", "Outlets", "Compare OUT-001 and OUT-002", sql=[r"outlets"]),
 _b("b23", "BLIND", "Outlets", "Top 10 outlets by customer satisfaction", sql=[r"customer_satisfaction"], truth="SELECT outlet_id FROM outlets ORDER BY customer_satisfaction DESC LIMIT 1"),
 _b("bi1", "BLIND", "I do not know", "How many parking spots does OUT-005 have?", "idk"),
 _b("bi2", "BLIND", "I do not know", "What is the CEO's name?", "idk"),
 _b("bi3", "BLIND", "I do not know", "Which outlets sell vegan food?", "idk"),
 _b("bi4", "BLIND", "I do not know", "How did our stock price move today?", "idk"),
 _b("bi5", "BLIND", "I do not know", "What is the annual salary budget for next year?", "idk"),
 _b("bi6", "BLIND", "I do not know", "Which staff member is the most hardworking?", "idk"),
 _b("bi7", "BLIND", "I do not know", "How many complaints did Zomato customers raise?", "idk"),
 _b("bi8", "BLIND", "I do not know", "What colour are the uniforms at OUT-020?", "idk"),
]

EX = ["Which outlets are at highest risk?", "Why is OUT-007 flagged?", "How is inventory holding up?", "Top 5 outlets by revenue"]

def _boot(app_dir):
    sys.path.insert(0, app_dir); os.chdir(app_dir)
    global QA, AN, CP, dom, Q
    import qa as QA, analyst as AN, copilot_pro as CP, domain_franchise as dom
    from blocks import Q
    CP._log_unanswered = lambda q: None                  # the test questions must not land in the admin's unanswered backlog
def _run(q, sid):
    """Same order the server uses: copilot_pro.prepare -> exact intent result, else analyst.py, else qa.py. Returns (route, text, sql, df)."""
    direct, q2, res, notes, ids = CP.prepare("Franchise", q, sid, dom, lambda: None, EX)
    if direct: return (direct.get("route") if direct.get("route") in ("idk", "unanswered") else "chat"), direct.get("text", ""), direct.get("sql", ""), None
    try:
        if res is None: res = CP.goods_duty("Franchise", q2) or AN.answer("Franchise", q2, None, None, dom) or QA.answer("Franchise", q2, None, None)
    except Exception as e: return "error", repr(e)[:120], "", None
    if not res or not res.get("answer"): return "unanswered", "", "", None
    df = res.get("df")
    if res.get("idk") or (not res.get("sql") and df is None): return "idk", res["answer"], res.get("sql", ""), None      # a reply that runs no query and gives no table is a decline
    if CP.weak_match(q, res): return "weak", res["answer"], res.get("sql", ""), df
    return "exact", res["answer"], res.get("sql", ""), df
def _cands(v):
    try: x = float(v)
    except Exception: return [str(v)]
    out = {f"{x:,.0f}", f"{x:,.2f}", f"{x:.2f}", f"{x:.1f}", f"{x:.0f}", f"{x:,.1f}", f"{x:.1f}".rstrip("0").rstrip("."), f"{x:.2f}".rstrip("0").rstrip(".")}
    return [c for c in out if c]
def _hay(text, df):
    h = text or ""
    if df is not None:
        try: h += "\n" + QA.md(df) + "\n" + df.to_csv(index=False)
        except Exception: pass
    return h
def _check(item, route, text, sql, df):
    c = item["chk"]; hay = _hay(text, df)
    if route != "exact": return False, "route=" + route
    for rx in c.get("sql", []):
        if not re.search(rx, sql or "", re.I): return False, "SQL does not use " + rx
    if c.get("empty"):
        return (bool(re.search(r"\b(no |none|zero|0 )", hay.lower())) or df is None or not len(df)), "expected an empty result"
    if c.get("truth"):
        try: t = Q(c["truth"])
        except Exception as e: return False, "truth query failed: " + repr(e)[:60]
        if t is None or not len(t): return (bool(re.search(r"\b(no |none|nothing)", hay.lower())), "truth is empty: the reply should say none")
        v = t.iloc[0, 0]
        if v is None: return False, "truth is NULL"
        for cand in _cands(v):
            if re.search(r"(?<![\d.,])" + re.escape(cand) + r"(?![\d])", hay): return True, ""
        return False, f"expected {_cands(v)[0]} in the reply"
    return True, ""
def _db():
    import config; c = sqlite3.connect(config.DB_PATH, timeout=30); c.execute("PRAGMA journal_mode=WAL;")
    c.execute("CREATE TABLE IF NOT EXISTS copilot_eval_runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, label TEXT, set_name TEXT, n_answerable INT, answered INT, correct INT, n_idk INT, idk_ok INT, wrong_confident INT, ms REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS copilot_eval_items(run_id INT, set_name TEXT, category TEXT, q TEXT, expect TEXT, route TEXT, ok INT, why TEXT, reply TEXT)")
    return c
def evaluate(label, app_dir):
    _boot(app_dir); import hashlib
    rows = []
    for k, it in enumerate(BENCH):
        t0 = time.time(); route, text, sql, df = _run(it["q"], f"eval-{label}-{k}")
        if it["expect"] == "idk": ok, why = (route in ("idk", "unanswered")), ("" if route in ("idk", "unanswered") else f"answered with route={route} instead of declining")
        else: ok, why = _check(it, route, text, sql, df)
        rows.append((it, route, ok, why, (text or "").replace("\n", " ")[:160], (time.time() - t0) * 1000))
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with _db() as c:
        for s in ("TUNE", "HOLD", "BLIND", "ALL"):
            R = [r for r in rows if s == "ALL" or r[0]["set"] == s]; A = [r for r in R if r[0]["expect"] == "answer"]; I = [r for r in R if r[0]["expect"] == "idk"]
            rid = c.execute("INSERT INTO copilot_eval_runs(ts,label,set_name,n_answerable,answered,correct,n_idk,idk_ok,wrong_confident,ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, label, s, len(A), sum(1 for r in A if r[1] == "exact"), sum(1 for r in A if r[2]), len(I), sum(1 for r in I if r[2]), sum(1 for r in I if r[1] in ("exact", "weak")), round(sum(r[5] for r in R) / max(1, len(R)), 1))).lastrowid
            if s == "ALL":
                for it, route, ok, why, reply, ms in rows: c.execute("INSERT INTO copilot_eval_items VALUES(?,?,?,?,?,?,?,?,?)", (rid, it["set"], it["cat"], it["q"], it["expect"], route, int(ok), why, reply))
    return rows
def summary():
    """For Admin > Copilot insights: the latest 'before' and 'after' run, per question set, plus the questions that still fail."""
    try:
        with _db() as c:
            def latest(label, s):
                r = c.execute("SELECT run_id, ts, n_answerable, answered, correct, n_idk, idk_ok, wrong_confident FROM copilot_eval_runs WHERE label=? AND set_name=? ORDER BY run_id DESC LIMIT 1", (label, s)).fetchone()
                return dict(zip(("run_id", "ts", "n_answerable", "answered", "correct", "n_idk", "idk_ok", "wrong_confident"), r)) if r else None
            out = {"before": {s: latest("before", s) for s in ("TUNE", "HOLD", "BLIND", "ALL")}, "after": {s: latest("after", s) for s in ("TUNE", "HOLD", "BLIND", "ALL")}}
            a = out["after"]["ALL"]; b = out["before"]["ALL"]
            out["items"] = []
            if a and b:
                for cat, q, ex, rb, okb, ra, oka, why, rep in c.execute("SELECT a.category, a.q, a.expect, b.route, b.ok, a.route, a.ok, a.why, a.reply FROM copilot_eval_items a JOIN copilot_eval_items b ON a.q=b.q AND b.run_id=? WHERE a.run_id=? ORDER BY a.rowid", (b["run_id"], a["run_id"])).fetchall():
                    out["items"].append({"category": cat, "question": q, "expect": ex, "before": rb + (" ✓" if okb else " ✗"), "after": ra + (" ✓" if oka else " ✗"), "why_after": why, "reply": rep})
            return out
    except Exception: return {"before": {}, "after": {}, "items": []}
if __name__ == "__main__":
    lab, app = sys.argv[1], sys.argv[2]
    R = evaluate(lab, app)
    for s in ("TUNE", "HOLD", "BLIND"):
        A = [r for r in R if r[0]["set"] == s and r[0]["expect"] == "answer"]; I = [r for r in R if r[0]["set"] == s and r[0]["expect"] == "idk"]
        print(f"{lab:6} {s}: answered {sum(1 for r in A if r[1]=='exact')}/{len(A)}  correct {sum(1 for r in A if r[2])}/{len(A)}  idk-ok {sum(1 for r in I if r[2])}/{len(I)}")
    if "-v" in sys.argv:
        for it, route, ok, why, reply, ms in R:
            if not ok and (len(sys.argv) < 5 or it["set"] in sys.argv[4:]): print(f"  X {it['id']} [{route}] {it['q']}  -> {why} | {reply[:90]}")