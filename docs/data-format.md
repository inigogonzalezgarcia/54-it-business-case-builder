# Data format

Put the files in one folder and run `python -m bizcase build <folder>`. `options.csv` and `costs.csv` are required; the rest are optional. Column names are forgiving (the alternatives are in `bizcase/model.py`), amounts accept `1.250.000`, `1,250,000` and `€ 12 500`, and `python -m bizcase template <folder>` writes every file with its columns.

## options.csv

| Column | Meaning |
|---|---|
| Option | Short id (`BASE`, `A`, `B`…) |
| Name, Description | Shown in the report and the paper |
| Baseline | `yes` for exactly one option: the cost of doing nothing (keeping today's platform for the whole horizon) |
| GoLiveMonth | Months from the start until the option is live; benefits count from the year that contains that month (month 1–12 → year 1, 13–24 → year 2…) |
| Owner | Sponsor of the option |

## costs.csv

One row per cost item and year. Year 0 is the start (the investment); years 1 to the horizon follow.

| Column | Meaning |
|---|---|
| Option, Item, Year, Amount | What, when and how much |
| Category | `implementation`, `hardware`, `migration`, `training`, `decommission`, `contingency` (one-off); `licences`, `subscription`, `hosting`, `internal-staff` (running). Free text is mapped by keywords |
| Type | `capex` or `opex` (shown, not used in the figures) |
| Confidence | `high` (quote or contract), `medium` (estimate), `low` (rough estimate) |
| Basis | Where the figure comes from |

## benefits.csv

| Column | Meaning |
|---|---|
| Option, Benefit, Year, Amount | What, when and how much a year |
| Type | `saving`, `avoidance`, `productivity`, `revenue`, `risk` |
| Kind | `hard` (cash: a budget goes down or income goes up; counted in the NPV) or `soft` (shown, not counted) |
| KPI, Baseline, Target | How it will be measured, today's value and the target |
| Owner | Who in the business will deliver it |
| Evidence | `measured`, `estimate` or `assumption` |
| Assumption | Ids from `assumptions.csv`, separated by commas |

## risks.csv, assumptions.csv, criteria.csv

- `risks.csv`: Option, Risk, Probability (`0.3`, `30 %`, `low`/`medium`/`high` = 10/30/60 %), Impact, Mitigation, Owner.
- `assumptions.csv`: Id, Assumption, Value, Source, Owner, Validated (`yes`/`no`).
- `criteria.csv`: Criterion, Weight (adding up to 100), Option, Score (1–5). The weighted score is shown and breaks ties; it does not override the financial result.

## settings.json

| Key | Default | Meaning |
|---|---|---|
| organisation, title, decision, review_date | | Shown in the outputs; decisions are due 14 days after the review date |
| currency | EUR | |
| horizon | 5 | Years after year 0 |
| discount_rate | 0.08 | For NPV |
| max_payback_years | 3 | Payback limit for a recommendation |
| hurdle_npv | 0 | Minimum NPV for a recommendation and for the pessimistic case |
| driver_pct | 20 | An unvalidated assumption behind this share of an option's hard benefits is a finding (RED from 40 %) |
| contingency_pct | high 5, medium 10, low 20 | Contingency the one-off costs need, by confidence |
| sensitivity_pct, delay_months | 20, 6 | Size of the sensitivity scenarios |
| owners | | Who owns each kind of action: FINANCE, BENEFITS, COSTS, RISKS, DECISION |

## How the figures are worked out

- **Net cash flow** per year = cost of the baseline − cost of the option + hard benefits. NPV discounts it at the discount rate from year 0; IRR is the rate where the NPV is zero; payback is when the cumulative net flow turns positive, interpolated within the year; ROI is the total net flow over the one-off cost.
- **After the checks:** double-counted savings are removed for every year, benefits before go-live for those years, hard benefits with no owner become soft, and the missing contingency is added in year 0. The report also shows the figures as submitted.
- **Pessimistic and optimistic:** costs move by their confidence (high −5 % / +10 %, medium −10 % / +25 %, low −15 % / +50 %) and benefits by their evidence (measured +5 % / −10 %, estimate +10 % / −30 %, assumption +20 % / −50 %).
- **Late go-live:** benefits move by the delay, and the baseline's cost stays for that part of the go-live year.
- **Risk-adjusted NPV:** NPV minus probability × impact of the option's risks, discounted to year 2.
- **Recommendation:** among the options with no red finding on costs or benefits, a NPV at or above the hurdle and payback within the limit, the highest risk-adjusted NPV; ties go to the weighted score.
