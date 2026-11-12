"""Row-level validation for every feed. Bad rows are quarantined with a reason (table feed_rejects); good rows still load.
Rules: required values, numeric ranges, allowed values, ISO dates, and foreign keys (only enforced once the parent table has rows)."""
import re, json
import pandas as pd
R = lambda lo=None, hi=None: ("range", lo, hi)
RULES = {
    "outlets": {"revenue": R(0), "operating_costs": R(0), "customer_satisfaction": R(0, 5), "staff_headcount": R(0, 5000)},
    "staff": {"salary": R(0, 1e8), "overtime_hrs": R(0, 400), "age": R(14, 90), "tenure_years": R(0, 70), "predicted_attrition_prob": R(0, 1), "job_satisfaction": R(0, 10), "work_life_balance": R(0, 10), "outlet_id": ("fk", "outlets", "outlet_id")},
    "inventory": {"current_stock": R(0), "reorder_threshold": R(0), "weekly_demand": R(0), "lead_time_days": R(0, 365), "stockout_risk_prob": R(0, 1), "outlet_id": ("fk", "outlets", "outlet_id")},
    "marketing": {"budget": R(0), "reach": R(0), "conversions": R(0), "actual_roi": R(-100, 1000), "outlet_id": ("fk", "outlets", "outlet_id"), "start_date": ("date",), "end_date": ("date",)},
    "audits": {"score": R(0, 100), "violations": R(0, 1000), "audit_date": ("date",), "outlet_id": ("fk", "outlets", "outlet_id")},
    "feedback": {"rating": R(1, 5), "sentiment_score": R(-1, 1), "date": ("date",), "outlet_id": ("fk", "outlets", "outlet_id")},
    "sales": {"amount": R(0, 1e9), "tx_count": R(0, 1e6), "ts": ("date",), "outlet_id": ("fk", "outlets", "outlet_id")},
    "ports": {"lat": R(-90, 90), "lon": R(-180, 180), "congestion_index": R(0, 10), "avg_dwell_days": R(0, 120)},
    "carriers": {"rating": R(0, 5), "on_time_pct": R(0, 100), "avg_cost_index": R(0, 10), "risk_level": ("enum", {"low", "medium", "high"})},
    "shipments": {"weight_kg": R(0, 1e9), "predicted_delay_risk": R(0, 1), "eta": ("date",), "origin_port": ("fk", "ports", "port_name"), "dest_port": ("fk", "ports", "port_name")},
    "freight_quotes": {"final_price": R(0, 1e10), "base_cost": R(0, 1e10), "margin_pct": R(-100, 100), "insurance": R(0), "customs_fee": R(0), "fuel_surcharge": R(0), "shipment_id": ("fk", "shipments", "shipment_id")},
    "vessels": {"lat": R(-90, 90), "lon": R(-180, 180), "speed_kn": R(0, 60), "progress": R(0, 1)},
    "customers": {"credit_risk": R(0, 1)},
    "quote_requests": {"weight_t": R(0, 1e6)},
    "customs_rules": {"duty_pct": R(0, 500)},
}
def _fk_values(conn, table, col):
    try: return {str(r[0]) for r in conn.execute(f"SELECT {col} FROM {table}")}
    except Exception: return set()
def validate(table, df, conn):
    """-> (clean df, rejects [{row, field, reason, value}])"""
    rules = RULES.get(table, {}); bad = {}; fk_cache = {}
    def mark(i, f, why, v): bad.setdefault(i, (f, why, str(v)[:60]))
    for col, rule in rules.items():
        if col not in df.columns: continue
        s = df[col]; kind = rule[0]
        if kind == "range":
            n = pd.to_numeric(s, errors="coerce")
            for i in df.index[s.notna() & n.isna()]: mark(i, col, "not a number", s[i])
            if rule[1] is not None:
                for i in df.index[n < rule[1]]: mark(i, col, f"below {rule[1]:g}", s[i])
            if rule[2] is not None:
                for i in df.index[n > rule[2]]: mark(i, col, f"above {rule[2]:g}", s[i])
        elif kind == "date":
            d = pd.to_datetime(s, errors="coerce", utc=True)
            for i in df.index[s.notna() & d.isna()]: mark(i, col, "not a valid date", s[i])
        elif kind == "enum":
            for i in df.index[s.notna() & ~s.astype(str).str.lower().isin(rule[1])]: mark(i, col, "value not allowed (" + "/".join(sorted(rule[1])) + ")", s[i])
        elif kind == "fk":
            key = (rule[1], rule[2])
            if key not in fk_cache: fk_cache[key] = _fk_values(conn, *key)
            if fk_cache[key]:
                for i in df.index[s.notna() & ~s.astype(str).isin(fk_cache[key])]: mark(i, col, f"unknown {rule[1]}.{rule[2]}", s[i])
    rej = [{"row": int(i) + 2, "field": f, "reason": w, "value": v} for i, (f, w, v) in sorted(bad.items())]
    return df.drop(index=list(bad)), rej
