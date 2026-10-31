# FranchiseOps AI – Copilot Fine-tuning & Agents
## Milestone 2 – Step 7

### 1. Overview

This module enhances the FranchiseOps AI Copilot to understand natural-language
questions and retrieve accurate information from the application's live SQL
database.

The implementation focuses on:
- SQL-based question answering.
- Intent recognition for common franchise operations questions.
- Spelling correction and alternate terminology.
- Outlet-level data filtering.
- Read-only, parameterized SQL execution.
- Clear responses with SQL query information and row counts.

The Copilot uses SQL queries rather than relying on an LLM to generate
unsupported numerical answers.

### 2. Files Modified

| File | Responsibility |
|---|---|
| analyst.py | Custom question patterns, intent recognition, SQL handlers and scope filtering |
| qa.py | Generic SQL question-answering engine and outlet scope checks |
| intent_router.py | Existing centralized intent routing and orchestration |

### 3. Implemented SQL Intents

The following 17 question patterns have been implemented and tested:

| No. | Intent | Example question |
|---:|---|---|
| 1 | lowest_csat | Which outlet has the lowest customer satisfaction? |
| 2 | highest_revenue | Which outlet has the highest revenue? |
| 3 | staff_count | How many staff members are in outlet OUT-001? |
| 4 | highest_staff_count | Which outlet has the highest number of employees? |
| 5 | high_attrition | Which employees have a high attrition risk? |
| 6 | below_reorder | Show inventory items below reorder level. |
| 7 | stockout_risk | Which inventory items have high stockout risk? |
| 8 | reorder_count | How many inventory items need reordering? |
| 9 | best_campaign_roi | Which campaign has the best ROI? |
| 10 | average_campaign_roi | What is the average campaign ROI? |
| 11 | negative_reviews | Show negative customer reviews. |
| 12 | most_negative_reviews | Which outlet has the most negative reviews? |
| 13 | average_rating | What is the average customer rating? |
| 14 | failed_audits | Show failed audits. |
| 15 | highest_violations | Which outlet has the highest number of audit violations? |
| 16 | total_outlets | How many outlets are there? |
| 17 | highest_operating_cost | Which outlet has the highest operating costs? |

### 4. Spelling Correction and Alternate Wording

A centralized question normalizer was implemented to improve recognition
of spelling mistakes and alternate terminology.

Examples of spelling corrections:

| Incorrect input | Normalized term |
|---|---|
| custmer | customer |
| satisfation | satisfaction |
| revanue | revenue |
| employes | employees |
| campain | campaign |
| reoder | reorder |
| inventry | inventory |
| feeback | feedback |
| audt | audit |

The normalizer also maps alternate terminology such as employees and
workforce to the corresponding staff-related terminology.

#### Normalization test cases

| Input question | Expected intent | Result |
|---|---|---|
| Which outlet has the lowest custmer satisfation? | lowest_csat | PASS |
| Which outlet has the highest revanue? | highest_revenue | PASS |
| How many employes are in outlet OUT-001? | staff_count | PASS |
| Which campain has the best ROI? | best_campaign_roi | PASS |
| How many inventory items need reordering? | reorder_count | PASS |
| Show failed audits | failed_audits | PASS |
| Which outlet has the most negative reviews? | most_negative_reviews | PASS |

**Normalization test result: 7/7 passed.**

### 5. Full Intent Regression Testing

All 17 implemented intents were tested against their expected intent
identifiers.

**Result: 17/17 passed, 0 failed.**

Python syntax validation and updated module import were also successful.

### 6. SQL Execution and Response Structure

The custom handlers execute SQL queries against the live database.

The response structure includes:
- Intent identifier.
- Human-readable answer.
- SQL query.
- SQL parameters where applicable.
- Row count.
- Returned DataFrame.
- Completion status.

Queries use parameterized values for outlet filtering.

For aggregate queries, row_count represents the number of returned
result rows. It does not necessarily represent the number of underlying
database records.

For generic QA queries, the answer may report the total number of
matching records while displaying only the first 10 rows.

### 7. Outlet-Level Scope Enforcement

Outlet-level scope enforcement was implemented in the custom SQL handlers
and is supported by the generic QA engine.

The custom handlers use a shared scoped() helper to append an outlet
filter to applicable SQL queries.

If a user has an assigned outlet scope, questions without a named outlet
are restricted to that outlet.

If a question explicitly requests a different outlet, the handler returns
a scope_denied response.

#### Custom handler scope tests

| Test | Expected behavior | Result |
|---|---|---|
| Lowest CSAT with scope OUT-001 | Only OUT-001 data | PASS |
| Staff count for OUT-001 | Allow access | PASS |
| Staff count for OUT-002 with scope OUT-001 | Deny access | PASS |
| Reorder count with scope OUT-001 | Only OUT-001 data | PASS |

**Custom scope tests: 4/4 passed.**

#### Generic QA scope tests

| Question | Expected behavior | Result |
|---|---|---|
| Show inventory records | Filter by OUT-001 | PASS |
| Show staff members | Filter by OUT-001 | PASS |
| Show feedback entries | Filter by OUT-001 | PASS |

**Generic QA scope tests: 3/3 passed.**

### 8. Unsupported Question Handling

The existing Copilot endpoint in server.py provides a polite fallback
when neither the custom SQL handlers nor the generic QA engine can
answer a question.

The fallback:
- Explains that an exact answer could not be computed.
- Suggests five supported example questions.
- Does not fabricate database results.

Greetings and thank-you messages are also handled separately.

### 9. Test Summary

| Test category | Passed | Failed |
|---|---:|---:|
| Question normalization | 7 | 0 |
| Full intent regression | 17 | 0 |
| Custom handler scope isolation | 4 | 0 |
| Generic QA scope isolation | 3 | 0 |
| **Total test executions** | **31** | **0** |

These are test executions across different categories; they are not
31 unique intent patterns.

### 10. Integration Notes and Known Limitations

The current server.py uses a single local Admin user configuration.

The existing Copilot endpoint calls the SQL engines with a None scope:

    AN.answer(KIND, q, None, VC.decision(), dom)
    QA.answer(KIND, q, None, None)

Therefore, although the SQL engines support and pass direct outlet-scope
tests, authenticated role and outlet scope still need to be passed by
the application integration layer.

End-to-end role-based access has not yet been verified.

The fallback is already present in server.py and does not require a
separate implementation in qa.py.

### 11. Conclusion

The Copilot enhancement implements 17 SQL-based question patterns,
question normalization, and outlet-level filtering support.

All recorded normalization, intent-recognition, and direct scope-isolation
tests passed.

The remaining integration work is to connect authenticated user roles
and outlet assignments to the Copilot endpoint, verify the complete
application behavior, and perform regression testing after merging
with the other milestone components.
