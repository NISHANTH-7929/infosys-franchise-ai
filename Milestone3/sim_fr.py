import random
import math
import statistics


# ============================================================
# COMMON HELPER FUNCTIONS
# ============================================================

def percentile(values, p):
    """Calculate a percentile."""
    if not values:
        return 0

    values = sorted(values)
    index = (len(values) - 1) * p / 100
    lower = math.floor(index)
    upper = math.ceil(index)

    if lower == upper:
        return values[int(index)]

    return values[lower] + (
        values[upper] - values[lower]
    ) * (index - lower)


def percentile_range(values):
    """Return P10, P50 and P90."""
    return {
        "P10": round(percentile(values, 10), 2),
        "P50": round(percentile(values, 50), 2),
        "P90": round(percentile(values, 90), 2)
    }


# ============================================================
# 1. INVENTORY SIMULATOR
# Demand seasonality + stock-out probability
# ============================================================

def simulate_inventory(
    current_stock=500,
    avg_daily_demand=50,
    demand_variation=0.20,
    days=30,
    simulations=1000,
    seasonality_strength=0.20,
    seed=42
):

    random.seed(seed)

    ending_stocks = []
    stockout_days_list = []
    stockout_count = 0

    for _ in range(simulations):

        stock = current_stock
        stockout_days = 0

        for day in range(days):

            # Seasonal demand pattern
            seasonal_factor = 1 + seasonality_strength * math.sin(
                2 * math.pi * day / days
            )

            demand = random.gauss(
                avg_daily_demand * seasonal_factor,
                avg_daily_demand * demand_variation
            )

            demand = max(0, demand)

            if demand > stock:
                stockout_days += 1
                stock = 0
            else:
                stock -= demand

        ending_stocks.append(stock)
        stockout_days_list.append(stockout_days)

        if stockout_days > 0:
            stockout_count += 1

    return {
        "simulator": "Inventory",
        "seed": seed,

        "assumptions": [
            "Demand follows a normal distribution",
            "Demand changes due to seasonality",
            "Demand cannot be negative",
            "No replenishment occurs during the simulation"
        ],

        "stockout_probability_percent": round(
            stockout_count / simulations * 100,
            2
        ),

        "ending_stock_range": percentile_range(
            ending_stocks
        ),

        "stockout_days_range": percentile_range(
            stockout_days_list
        )
    }


# ============================================================
# 2. WORKFORCE SIMULATOR
# Attrition by tenure + Hiring vs Overtime
# ============================================================

def simulate_workforce(
    employees=20,
    avg_tenure_years=2,
    hourly_wage=200,
    hiring_cost=30000,
    overtime_multiplier=1.5,
    monthly_hours_needed=3500,
    simulations=1000,
    seed=42
):

    random.seed(seed)

    hiring_costs = []
    overtime_costs = []
    attrition_counts = []

    for _ in range(simulations):

        attrition = 0

        for _ in range(employees):

            tenure = max(
                0.1,
                random.gauss(avg_tenure_years, 1)
            )

            # Attrition probability based on tenure
            if tenure < 1:
                attrition_probability = 0.25

            elif tenure < 3:
                attrition_probability = 0.12

            else:
                attrition_probability = 0.05

            if random.random() < attrition_probability:
                attrition += 1

        attrition_counts.append(attrition)

        # Strategy 1: Hire replacements
        hiring_strategy_cost = attrition * hiring_cost

        # Strategy 2: Use overtime
        remaining_employees = max(
            1,
            employees - attrition
        )

        normal_capacity = remaining_employees * 160

        overtime_hours = max(
            0,
            monthly_hours_needed - normal_capacity
        )

        overtime_strategy_cost = (
            overtime_hours
            * hourly_wage
            * overtime_multiplier
        )

        hiring_costs.append(hiring_strategy_cost)
        overtime_costs.append(overtime_strategy_cost)

    hiring_median = statistics.median(hiring_costs)
    overtime_median = statistics.median(overtime_costs)

    return {
        "simulator": "Workforce",
        "seed": seed,

        "assumptions": [
            "Employees with lower tenure have higher attrition risk",
            "Each employee provides 160 normal hours per month",
            "Hiring cost is charged for each replacement",
            "Overtime is paid using the overtime multiplier"
        ],

        "expected_attrition_range": percentile_range(
            attrition_counts
        ),

        "hiring_strategy_cost_range": percentile_range(
            hiring_costs
        ),

        "overtime_strategy_cost_range": percentile_range(
            overtime_costs
        ),

        "recommended_strategy": (
            "Hiring"
            if hiring_median < overtime_median
            else "Overtime"
        )
    }


# ============================================================
# 3. P&L SIMULATOR
# Price elasticity + Wage inflation band
# ============================================================

def simulate_pnl(
    base_price=100,
    base_units=10000,
    variable_cost_per_unit=40,
    base_wages=500000,
    price_change_percent=5,
    price_elasticity=-1.2,
    wage_inflation_low=0.03,
    wage_inflation_high=0.10,
    simulations=1000,
    seed=42
):

    random.seed(seed)

    profits = []
    revenues = []
    wage_inflation_values = []

    for _ in range(simulations):

        wage_inflation = random.uniform(
            wage_inflation_low,
            wage_inflation_high
        )

        wage_inflation_values.append(
            wage_inflation * 100
        )

        # New price
        price = base_price * (
            1 + price_change_percent / 100
        )

        # Price elasticity affects demand
        demand_change_percent = (
            price_elasticity * price_change_percent
        )

        units = base_units * (
            1 + demand_change_percent / 100
        )

        units = max(0, units)

        # Wage inflation
        wages = base_wages * (
            1 + wage_inflation
        )

        revenue = price * units
        variable_cost = variable_cost_per_unit * units

        profit = (
            revenue
            - variable_cost
            - wages
        )

        revenues.append(revenue)
        profits.append(profit)

    return {
        "simulator": "P&L",
        "seed": seed,

        "assumptions": [
            "Demand responds to price using price elasticity",
            "Wage inflation varies within the selected band",
            "Variable cost per unit remains constant",
            "Other operating costs remain constant"
        ],

        "revenue_range": percentile_range(
            revenues
        ),

        "profit_range": percentile_range(
            profits
        ),

        "wage_inflation_percent_range": percentile_range(
            wage_inflation_values
        )
    }


# ============================================================
# 4. MARKETING SIMULATOR
# Diminishing returns + Campaign fatigue
# ============================================================

def simulate_marketing(
    monthly_budget=100000,
    base_roi=3.0,
    campaigns=12,
    fatigue_rate=0.05,
    simulations=1000,
    seed=42
):

    random.seed(seed)

    revenues = []
    rois = []

    for _ in range(simulations):

        total_revenue = 0

        for campaign in range(campaigns):

            # Diminishing returns
            diminishing_factor = 1 / (
                1 + campaign * 0.15
            )

            # Campaign fatigue
            fatigue_factor = max(
                0.20,
                1 - campaign * fatigue_rate
            )

            # Random performance variation
            performance_noise = random.uniform(
                0.85,
                1.15
            )

            campaign_revenue = (
                monthly_budget
                * base_roi
                * diminishing_factor
                * fatigue_factor
                * performance_noise
                / campaigns
            )

            total_revenue += campaign_revenue

        revenues.append(total_revenue)

        rois.append(
            total_revenue / monthly_budget
        )

    return {
        "simulator": "Marketing",
        "seed": seed,

        "assumptions": [
            "Returns decrease as marketing exposure increases",
            "Repeated campaigns create audience fatigue",
            "Campaign performance contains random variation"
        ],

        "revenue_range": percentile_range(
            revenues
        ),

        "roi_range": percentile_range(
            rois
        )
    }


# ============================================================
# 5. SENTIMENT SIMULATOR
# Top complaint fix impact on CSAT
# ============================================================

def simulate_sentiment(
    complaints=None,
    base_csat=75,
    fix_effectiveness=0.70,
    simulations=1000,
    seed=42
):

    random.seed(seed)

    if complaints is None:

        complaints = {
            "Slow service": 120,
            "Product quality": 90,
            "Staff behaviour": 60,
            "Pricing": 40
        }

    # Find most frequent complaint
    top_complaint = max(
        complaints,
        key=complaints.get
    )

    total_complaints = sum(
        complaints.values()
    )

    top_complaint_share = (
        complaints[top_complaint]
        / total_complaints
    )

    csat_before = []
    csat_after = []
    improvements = []

    for _ in range(simulations):

        effectiveness = random.gauss(
            fix_effectiveness,
            0.10
        )

        effectiveness = max(
            0,
            min(1, effectiveness)
        )

        before = random.gauss(
            base_csat,
            2
        )

        improvement = (
            top_complaint_share
            * effectiveness
            * 20
        )

        after = min(
            100,
            before + improvement
        )

        csat_before.append(before)
        csat_after.append(after)
        improvements.append(improvement)

    return {
        "simulator": "Sentiment",
        "seed": seed,

        "assumptions": [
            "The most frequent complaint has the biggest improvement opportunity",
            "Fix effectiveness varies between simulations",
            "CSAT cannot exceed 100"
        ],

        "top_complaint": top_complaint,

        "top_complaint_count": complaints[
            top_complaint
        ],

        "csat_before_range": percentile_range(
            csat_before
        ),

        "csat_after_fix_range": percentile_range(
            csat_after
        ),

        "csat_improvement_range": percentile_range(
            improvements
        )
    }


# ============================================================
# 6. AUDIT SIMULATOR
# Failure risk from open findings
# ============================================================

def simulate_audit(
    critical_findings=2,
    high_findings=3,
    medium_findings=5,
    simulations=1000,
    seed=42
):

    random.seed(seed)

    failure_risks = []

    open_findings = (
        critical_findings
        + high_findings
        + medium_findings
    )

    for _ in range(simulations):

        # Different severity levels have different impact
        critical_factor = random.uniform(
            0.18,
            0.30
        )

        high_factor = random.uniform(
            0.06,
            0.12
        )

        medium_factor = random.uniform(
            0.01,
            0.05
        )

        risk = (
            critical_findings * critical_factor
            + high_findings * high_factor
            + medium_findings * medium_factor
        )

        risk = min(1, risk)

        failure_risks.append(
            risk * 100
        )

    median_risk = statistics.median(
        failure_risks
    )

    if median_risk >= 60:
        risk_level = "Critical"

    elif median_risk >= 35:
        risk_level = "High"

    elif median_risk >= 15:
        risk_level = "Medium"

    else:
        risk_level = "Low"

    return {
        "simulator": "Audit",
        "seed": seed,

        "assumptions": [
            "Critical findings have the highest impact",
            "Open findings increase operational failure risk",
            "Finding impact varies across simulation runs"
        ],

        "open_findings": open_findings,

        "failure_risk_percent_range": percentile_range(
            failure_risks
        ),

        "risk_level": risk_level
    }


# ============================================================
# RUN ALL SIMULATORS
# ============================================================

def run_all_simulators(seed=42):

    return {

        "INVENTORY": simulate_inventory(
            seed=seed
        ),

        "WORKFORCE": simulate_workforce(
            seed=seed
        ),

        "P&L": simulate_pnl(
            seed=seed
        ),

        "MARKETING": simulate_marketing(
            seed=seed
        ),

        "SENTIMENT": simulate_sentiment(
            seed=seed
        ),

        "AUDIT": simulate_audit(
            seed=seed
        )
    }


# ============================================================
# DISPLAY RESULTS
# ============================================================

results = run_all_simulators(seed=42)

for simulator, result in results.items():

    print("\n" + "=" * 65)
    print(simulator)
    print("=" * 65)

    for key, value in result.items():
        print(f"{key}: {value}")
