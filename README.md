# Credit Gap Analyser & Loan Eligibility Evaluator

A configurable, two-mode rule engine that powers Softlend's credit
improvement product: given a customer's credit report, identify what's
dragging their score down and by how much (**Gap Analysis**); given a
customer's profile, decide whether they qualify for a loan right now,
and exactly why or why not (**Eligibility Evaluation**).

Every threshold, every rule, and every operator the rules use lives in
one file — `rules.yaml`. Changing a number (the utilisation threshold,
the minimum CIBIL score, an age limit) is a YAML edit, never a code
change.

Built for the Softlend Rule Engine Intern Evaluation Activity.

---

## 1. Problem Statement

Build a two-stage engine:

1. **Gap analysis mode** — given a credit report, identify which gap
   rules fire and produce a ranked list of improvement actions.
2. **Eligibility mode** — given a customer profile, evaluate loan
   eligibility and return pass/fail per rule, with reasons.

Both modes are driven entirely by `rules.yaml`. Business logic in
Python contains zero hardcoded thresholds.

---

## 2. Architecture

```
Input JSON (credit report / customer profile)
        │
        ▼
engine/evaluator.py  (RuleEngine — loads rules ONCE, dispatches by mode)
        │
        ├──► engine/gap_analyser.py        (gap_analysis mode)
        │         │
        │         ▼
        │    engine/operators.py  (registry lookup, no if/elif chains)
        │
        └──► engine/eligibility_engine.py  (eligibility mode)
                  │
                  ▼
             engine/operators.py  (same registry, same operators)

Both modes read their rules from:
        engine/rule_loader.py  ──►  rules.yaml
        (parses + validates at LOAD time, fails fast on any problem)
```

### Why this shape

- **One operator registry, shared by both modes.** `engine/operators.py`
  is a `dict[str, Callable]` mapping operator name → comparison
  function. Evaluating any rule — gap or eligibility — never branches
  on operator name via `if/elif`; it looks the function up and calls
  it. Adding a new operator means writing one function and adding one
  registry entry; nothing else in the engine changes.
- **Validation happens once, at load time, not at evaluation time.**
  `rule_loader.py` parses `rules.yaml`, checks every required key is
  present, every operator is registered, every impact value is valid,
  and every rule id is unique — all before the engine ever evaluates a
  single record. A bad config fails immediately and loudly (fail-fast),
  with a specific, actionable error, rather than surfacing as a
  confusing crash on whichever request happens to hit the bad rule
  first.
- **Typed models separate config shape from output shape.**
  `models/rule_models.py` is what `rules.yaml` parses into;
  `models/response_models.py` is what gets serialized back out as
  JSON. They're deliberately different dataclasses, not the same
  objects reused for two purposes.
- **`engine/evaluator.py` is the only file main.py and the bonus HTTP
  API need to import.** Neither needs to know that `rule_loader`,
  `gap_analyser`, and `eligibility_engine` exist as separate modules —
  this thin façade is the one stable surface those three internal
  modules hide behind.
- **The core engine has zero web-framework dependency.** `api.py` (the
  bonus HTTP layer) is the only file that imports FastAPI. You can use
  the entire engine as a pure Python library — as `main.py` does —
  without installing or importing anything web-related.

---

## 3. Folder Structure

```
credit-rule-engine/
├── rules.yaml                       # the ONLY place business rules live
├── sample_data/
│   ├── credit_report.json           # brief's exact sample input
│   └── customer_profile.json        # brief's exact sample input
├── engine/
│   ├── operators.py                 # operator registry (gt, gte, lt, ..., lte_multiplier)
│   ├── rule_loader.py               # YAML parsing + fail-fast schema validation
│   ├── gap_analyser.py              # gap_analysis mode
│   ├── eligibility_engine.py        # eligibility mode (AND/OR group logic, risk score)
│   ├── evaluator.py                 # RuleEngine façade -- single entry point
│   └── exceptions.py                # RuleLoadError, ConfigurationError, etc.
├── models/
│   ├── rule_models.py                # GapRule, EligibilitySubRule, EligibilityRuleGroup, RuleSet
│   └── response_models.py            # GapAnalysisResult, EligibilityResult, etc.
├── tests/
│   ├── test_operators.py
│   ├── test_rule_loader.py
│   ├── test_gap_analysis.py
│   ├── test_eligibility.py
│   ├── test_evaluator.py
│   └── test_api.py
├── outputs/                          # optional --output destination for main.py
├── main.py                           # CLI entry point
├── api.py                            # bonus: POST /analyse HTTP endpoint
├── requirements.txt
└── README.md
```

---

## 4. Supported Operators

| Operator | Meaning | Example |
|---|---|---|
| `gt` | strictly greater than | `credit_utilisation_pct > 30` |
| `gte` | greater than or equal | `cibil_score >= 650` |
| `lt` | strictly less than | `credit_age_months < 36` |
| `lte` | less than or equal | `foir <= 0.5` |
| `eq` | equal | `written_off_accounts == 0` |
| `neq` | not equal | — |
| `between` | inclusive range | `21 <= age <= 60` |
| `in` | value in list | `employment_type in [salaried, self_employed]` |
| `not_in` | value not in list | — |
| `lte_multiplier` | field ≤ another field × multiplier | `requested_amount <= monthly_income * 10` |

All numeric operators reject non-numeric input (and reject booleans
specifically — see [Design Decisions](#7-design-decisions)) with a
clear `ConfigurationError` rather than crashing with a raw `TypeError`.

### Adding a new operator

```python
# engine/operators.py
def _op_my_new_operator(actual, rule, profile):
    ...
    return True_or_False

OPERATORS["my_new_operator"] = _op_my_new_operator
```

That's it — no other file needs to change. `rules.yaml` can reference
`operator: my_new_operator` immediately.

---

## 5. How Rules Are Loaded

`engine/rule_loader.py::load_rules()` is called exactly once, when
`RuleEngine` is constructed (in `main.py` at CLI startup, or in
`api.py`'s `lifespan` hook at server startup — never per-request).

Validation performed, in order:

1. The file must exist and the YAML must parse.
2. Top-level structure must have `gap_rules` and `eligibility_rules`
   keys, each a list.
3. Every gap rule must have all required keys (`id`, `field`,
   `operator`, `impact`, `estimated_score_gain`, `action_template`), a
   valid `impact` (`high`/`medium`/`low`), a positive integer
   `estimated_score_gain`, and a **registered** operator.
4. Every eligibility group must have `name`, `logic` (`AND` or `OR`),
   and a non-empty `rules` list; every sub-rule must have `id`, `field`,
   `operator`, `message`, and a registered operator.
5. **No duplicate rule ids anywhere** — across gap rules and
   eligibility sub-rules combined, since ids are meant to be unique,
   referenceable identifiers.

Any failure raises immediately, before the engine evaluates anything.

---

## 6. How to Run

**Requirements:** Python 3.11+ (developed and tested on 3.12).

```bash
cd credit-rule-engine
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Gap analysis mode

```bash
python main.py --mode gap_analysis --input sample_data/credit_report.json
```

### Eligibility mode

```bash
python main.py --mode eligibility --input sample_data/customer_profile.json
```

### Optional flags

```bash
python main.py --mode gap_analysis \
    --input sample_data/credit_report.json \
    --rules rules.yaml \
    --output outputs/result.json
```

### Bonus: HTTP endpoint

```bash
uvicorn api:app --reload
```

Then:

```bash
curl -X POST http://127.0.0.1:8000/analyse \
  -H "Content-Type: application/json" \
  -d '{"mode": "gap_analysis", "customer_id": "C001", "credit_utilisation_pct": 87, "missed_payments_12m": 2, "written_off_accounts": 0, "credit_age_months": 14, "hard_enquiries_6m": 2}'
```

Interactive docs at `http://127.0.0.1:8000/docs`.

---

## 7. How to Test

```bash
pytest                                          # run the suite
pytest --cov=engine --cov=models --cov-report=term-missing   # with coverage
```

**120 tests, 99% line coverage** across `engine/` and `models/`
(the one uncovered line is a documented, structurally-unreachable
defensive guard — see the docstring on `_build_next_step` in
`engine/eligibility_engine.py`).

Test files map directly to what they cover:

| File | Covers |
|---|---|
| `test_operators.py` | Every operator individually, including numeric coercion edge cases (booleans, strings, `None`) |
| `test_rule_loader.py` | Malformed YAML, duplicate ids, unknown operators, missing keys, invalid impact/logic values, invalid weights, empty rule sets |
| `test_gap_analysis.py` | Exact sample-input match, all-rules-fire, no-gaps-found, **sorting order** (explicitly tested), action template substitution (including malformed templates), null/missing fields |
| `test_eligibility.py` | Exact sample-input match, all-pass, multi-failure, missing fields, **every named boundary value** (age 21/60/20/61, cibil 650/649, foir 0.5/0.51), AND logic, **OR logic** (proves future-readiness with zero engine changes), weighted risk score |
| `test_evaluator.py` | The `RuleEngine` façade: construction, mode dispatch, unknown-mode error, JSON-serializability |
| `test_api.py` | The bonus HTTP endpoint |

---

## 8. Example Input / Output

### Gap analysis

**Input** (`sample_data/credit_report.json`):
```json
{
  "customer_id": "C001",
  "credit_utilisation_pct": 87,
  "missed_payments_12m": 2,
  "written_off_accounts": 0,
  "credit_age_months": 14,
  "hard_enquiries_6m": 2
}
```

**Output:**
```json
{
  "mode": "gap_analysis",
  "customer_id": "C001",
  "gaps_found": 3,
  "total_potential_score_gain": 70,
  "gaps": [
    {
      "id": "high_utilisation",
      "impact": "high",
      "estimated_score_gain": 35,
      "current_value": 87,
      "action": "Reduce credit card utilisation from 87% to below 30%"
    },
    {
      "id": "missed_payments",
      "impact": "high",
      "estimated_score_gain": 25,
      "current_value": 2,
      "action": "Clear 2 overdue EMI(s) to remove missed payment flag"
    },
    {
      "id": "short_credit_age",
      "impact": "medium",
      "estimated_score_gain": 10,
      "current_value": 14,
      "action": "Avoid closing old accounts — your oldest account is only 14 months old"
    }
  ]
}
```

### Eligibility evaluation

**Input** (`sample_data/customer_profile.json`):
```json
{
  "customer_id": "C001",
  "age": 29,
  "cibil_score": 620,
  "monthly_income": 60000,
  "existing_emis": 15000,
  "foir": 0.25,
  "employment_type": "salaried",
  "written_off_accounts": 0,
  "requested_amount": 400000
}
```

**Output:**
```json
{
  "mode": "eligibility",
  "customer_id": "C001",
  "eligible": false,
  "rules": [
    { "rule": "age", "passed": true },
    { "rule": "cibil_score", "passed": false, "reason": "CIBIL score must be at least 650" },
    { "rule": "foir", "passed": true },
    { "rule": "employment_type", "passed": true },
    { "rule": "no_written_off_accounts", "passed": true },
    { "rule": "loan_amount_cap", "passed": true }
  ],
  "fail_reasons": ["cibil_score"],
  "next_step": "Improve CIBIL score. See gap analysis for specific improvement actions.",
  "risk_score": 25.0
}
```

`risk_score` (bonus feature) = `(sum of weights of failed rules / sum
of all weights) × 100`. Weights are configured per-rule in
`rules.yaml` (defaulting to `1.0` if omitted).

---

## 9. Design Decisions

- **Operator registry over if/elif chains.** Already covered above —
  this is the single biggest design choice in the codebase and the one
  most directly tied to the "add a rule/operator without touching core
  logic" requirement.
- **AND/OR is a property of the *group*, not the engine.**
  `eligibility_engine.py::evaluate_eligibility` already branches on
  `group.logic` for every group, even though the sample `rules.yaml`
  only defines one `AND` group. Adding an `OR` group is a YAML-only
  change — proven by `test_eligibility.py::TestOrGroupLogicFutureReadiness`,
  which loads a custom config with an `OR` group and confirms it
  evaluates correctly without any engine code modification.
- **`eq`/`neq` explicitly reject boolean-vs-number comparisons.**
  Python treats `bool` as a subtype of `int`, so `True == 1` and
  `False == 0` are both `True` by default. Left unguarded, a malformed
  `written_off_accounts: true` in a credit report could silently
  satisfy a rule checking `written_off_accounts == 0` — exactly the
  rule used in `rules.yaml`'s `no_written_off_accounts` check. `_eq`
  treats a bool-vs-non-bool comparison as always unequal, regardless of
  numeric value, closing that gap.
- **A missing or null field means "rule doesn't fire" / "rule fails
  with a clear reason," never a crash.** In gap analysis, a missing
  field means the rule simply doesn't apply (the credit report may
  legitimately omit a factor that isn't relevant to that customer). In
  eligibility mode, a missing field is a `passed: false` result with an
  explicit "Required field 'X' is missing" message — visible, not
  silent.
- **A malformed `action_template` never crashes the analysis.** If a
  template references a field that doesn't exist in the input, or has
  invalid `str.format()` syntax entirely (an unclosed brace, for
  example), rendering falls back gracefully — first to leaving unknown
  placeholders literally in the string, and if that's not even possible
  (genuinely malformed syntax), to returning the raw template
  unmodified. Either way the rest of the gap analysis still completes.
- **Validation happens once, at load time.** Already covered in
  [Section 5](#5-how-rules-are-loaded) — this is what makes the engine
  "fail fast."
- **The core engine never imports a web framework.** `api.py` is an
  optional, separate layer. This keeps the engine usable as a pure
  library (which is what `main.py` and the test suite both rely on)
  and means the bonus HTTP feature can be skipped entirely without
  touching the engine itself.

---

## 10. Edge Cases Handled

| Category | Edge case | Behavior |
|---|---|---|
| Input data | Missing field | Gap rule: doesn't fire. Eligibility rule: fails with explicit "missing" reason. |
| Input data | Null field | Same as missing — treated as "cannot evaluate," not an error. |
| Input data | Wrong data type (e.g. string where a number is expected) | `ConfigurationError` caught internally; rule treated as not-fired (gap) or failed-with-reason (eligibility), never propagates as a crash. |
| Input data | Empty credit report / customer profile | Zero gaps found / every rule reported as failed with a clear reason — no crash. |
| Input data | Negative values | Numeric operators evaluate them normally (e.g. `gt 0` correctly fails for `-5`); no special-casing needed since comparisons are mathematically well-defined for negatives. |
| Config | Malformed YAML | `RuleLoadError` at load time, before any evaluation. |
| Config | Unknown operator | `OperatorNotSupportedError` at load time (not first use). |
| Config | Missing required keys | `ConfigurationError` naming the exact missing keys. |
| Config | Invalid impact value | `ConfigurationError`. |
| Config | Invalid group logic (not AND/OR) | `ConfigurationError`. |
| Config | Duplicate rule ids (within or across gap/eligibility) | `ConfigurationError` naming both locations. |
| Config | Empty rule sets (`gap_rules: []`) | Loads successfully; evaluation against them simply finds zero gaps / is vacuously eligible. |
| Config | Missing `multiplier_field` / `multiplier` for `lte_multiplier` | `ConfigurationError` at evaluation time, surfaced as a failed-rule reason in eligibility mode. |
| Config | Malformed `action_template` (unclosed brace, missing variable) | Falls back gracefully; never raises. |
| Config | Negative or non-numeric `weight` | Rejected at load time with `ConfigurationError`. |
| Operators | `between` missing `min`/`max` | `ConfigurationError`. |
| Operators | `in`/`not_in` missing `values` | `ConfigurationError`. |
| Operators | Boolean compared against a number via `eq`/`neq` | Always treated as not-equal (see Design Decisions). |
| Operators | Boolean passed to a numeric comparator (`gt`, `gte`, etc.) | Explicitly rejected with `ConfigurationError`. |

---

## 11. Bonus Features Implemented

- ✅ **Weighted risk score** — `risk_score = (sum of weights of failed
  rules / sum of all weights) × 100`, configurable per-rule via an
  optional `weight` key in `rules.yaml` (defaults to `1.0`).
- ✅ **HTTP endpoint** — `POST /analyse`, dispatching both modes from a
  single endpoint based on a `mode` field in the request body, exactly
  matching the brief's example shape.

---

## 12. Future Improvements

- **Pluggable rule sources.** `load_rules()` currently only reads from
  a local YAML file; the same `RuleSet` shape could be populated from a
  database or a remote config service without changing anything
  downstream of `rule_loader.py`.
- **Per-customer rule overrides.** Some lenders may want
  customer-segment-specific thresholds (e.g. a different CIBIL cutoff
  for self-employed applicants). The `RuleSet` model could be extended
  to support layered/overridable configs without restructuring the
  evaluation logic.
- **Async rule evaluation for very large rule sets.** Today, evaluation
  is a simple synchronous loop, which is appropriate for the rule-set
  sizes this system is designed for (tens of rules, not thousands). If
  that assumption ever changes, the operator-function signature is
  already pure and side-effect-free, so parallelizing evaluation across
  rules would be a localized change.
