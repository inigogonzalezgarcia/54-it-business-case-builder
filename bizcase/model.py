"""Loading: the options (options.csv), their costs year by year (costs.csv), the benefits (benefits.csv), the risks (risks.csv),
the assumptions (assumptions.csv), the non-financial criteria and scores (criteria.csv) and the settings (settings.json).
Forgiving column names, into plain dataclasses."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

OPTION_ALIASES = {
    "id": ["Option", "Id", "Option id", "Code"],
    "name": ["Name", "Option name", "Title"],
    "description": ["Description", "Summary", "Scope"],
    "baseline": ["Baseline", "Do nothing", "Status quo", "Is baseline"],
    "golive": ["GoLiveMonth", "Go-live month", "Go live", "Golive", "Go-live"],
    "owner": ["Owner", "Sponsor", "Lead"],
}
COST_ALIASES = {
    "option": ["Option", "Option id"],
    "item": ["Item", "Cost", "Line", "Description", "Name"],
    "category": ["Category", "Cost category", "Type of cost"],
    "kind": ["Type", "Capex/Opex", "CapexOpex", "Nature"],
    "year": ["Year", "Period", "Yr"],
    "amount": ["Amount", "Cost amount", "Value", "EUR", "Cost (EUR)"],
    "confidence": ["Confidence", "Estimate confidence", "Certainty"],
    "basis": ["Basis", "Source", "Quote", "Notes"],
}
BENEFIT_ALIASES = {
    "option": ["Option", "Option id"],
    "name": ["Benefit", "Name", "Description"],
    "type": ["Type", "Benefit type", "Category"],
    "kind": ["Kind", "Hard/Soft", "HardSoft", "Cashable"],
    "year": ["Year", "Period", "Yr"],
    "amount": ["Amount", "Value", "EUR", "Benefit (EUR)"],
    "kpi": ["KPI", "Measure", "Metric"],
    "baseline": ["Baseline", "Current value", "Today"],
    "target": ["Target", "Target value"],
    "owner": ["Owner", "Benefit owner", "Accountable"],
    "evidence": ["Evidence", "Confidence", "Source type"],
    "assumption": ["Assumption", "Assumption id", "Assumptions"],
}
RISK_ALIASES = {
    "option": ["Option", "Option id"],
    "risk": ["Risk", "Description", "Name"],
    "probability": ["Probability", "Likelihood", "P"],
    "impact": ["Impact", "Impact (EUR)", "Cost if it happens", "Exposure"],
    "mitigation": ["Mitigation", "Response", "Treatment"],
    "owner": ["Owner", "Risk owner"],
}
ASSUMPTION_ALIASES = {
    "id": ["Id", "Assumption id", "Ref", "Code"],
    "text": ["Assumption", "Description", "Text"],
    "value": ["Value", "Figure"],
    "source": ["Source", "Basis", "Evidence"],
    "owner": ["Owner", "Validated by", "Accountable"],
    "validated": ["Validated", "Confirmed", "Status"],
}
CRITERIA_ALIASES = {
    "criterion": ["Criterion", "Criteria", "Factor"],
    "weight": ["Weight", "Weight %", "Weighting"],
    "option": ["Option", "Option id"],
    "score": ["Score", "Rating", "Points"],
    "note": ["Note", "Rationale", "Comment"],
}
YES = {"yes", "y", "true", "1", "x", "si", "validated", "confirmed", "baseline"}
NO = {"no", "n", "false", "0", "", "pending", "open"}
FILES = {"options.csv": "Options", "costs.csv": "Costs", "benefits.csv": "Benefits", "risks.csv": "Risks",
         "assumptions.csv": "Assumptions", "criteria.csv": "Criteria and scores"}
REQUIRED = ("options.csv", "costs.csv")
ONE_OFF = {"hardware", "implementation", "migration", "training", "decommission", "contingency", "data migration"}
CONF = {"high": (0.05, 0.10), "medium": (0.10, 0.25), "low": (0.15, 0.50)}      # (optimistic -, pessimistic +) on costs
EVID = {"measured": (0.05, 0.10), "estimate": (0.10, 0.30), "assumption": (0.20, 0.50)}   # (optimistic +, pessimistic -) on benefits


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def parse_d(v) -> date | None:
    s = str(v or "").strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def num(v) -> float | None:
    """'1.250.000', '1,250,000', '1250000.50', '€ 12 500', '-3.000' -> float."""
    s = re.sub(r"[€$£\s]|eur|usd|gbp", "", str(v or "").strip().lower())
    if not s:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def yes_no(v) -> bool:
    return _norm(v) in YES


def probability(v) -> float:
    """0.3, 30 %, 'medium' -> 0.3."""
    n = _norm(v)
    if n in {"low", "l", "unlikely"}:
        return 0.1
    if n in {"medium", "m", "possible", "moderate"}:
        return 0.3
    if n in {"high", "h", "likely"}:
        return 0.6
    x = num(str(v).replace("%", ""))
    if x is None:
        return 0.3
    return x / 100 if x > 1 else x


def category(v) -> str:
    n = _norm(v)
    for key, words in (("contingency", ("contingency", "reserve", "buffer")), ("decommission", ("decommission", "retire", "exit", "disposal")),
                       ("hosting", ("hosting", "data centre", "data center", "power", "colocation")),
                       ("migration", ("migration", "data", "conversion")), ("training", ("training", "change management", "adoption")),
                       ("internal-staff", ("internal", "staff", "fte", "people", "headcount")),
                       ("implementation", ("implementation", "integration", "partner", "project", "consult")),
                       ("subscription", ("subscription", "saas", "cloud")), ("licences", ("licence", "license", "support", "maintenance")),
                       ("hardware", ("hardware", "server", "storage", "device")),
                       ):
        if any(w in n for w in words):
            return key
    return n or "other"


def benefit_type(v) -> str:
    n = _norm(v)
    for key, words in (("saving", ("saving", "reduction", "cashable")), ("avoidance", ("avoid",)), ("productivity", ("productivity", "time", "efficien")),
                       ("revenue", ("revenue", "income", "growth", "sales")), ("risk", ("risk", "compliance", "outage", "security"))):
        if any(w in n for w in words):
            return key
    return n or "other"


def evidence(v) -> str:
    n = _norm(v)
    if any(w in n for w in ("measur", "actual", "invoice", "contract", "quote")):
        return "measured"
    if any(w in n for w in ("assum", "guess", "target", "vendor claim")):
        return "assumption"
    return "estimate"


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=header.count)
        reader = csv.DictReader(fh, delimiter=delim)
        return list(reader.fieldnames or []), list(reader)


def _map(fields: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    heads = {_norm(h): h for h in fields}
    cols = {}
    for k, names in aliases.items():
        for n in names + [k.replace("_", " ")]:
            if _norm(n) in heads and heads[_norm(n)] not in cols.values():
                cols[k] = heads[_norm(n)]
                break
    return cols


def _rows(path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    fields, raw = _read(path)
    cols = _map(fields, aliases)
    return [{k: (r.get(c) or "").strip() for k, c in cols.items()} for r in raw]


# ---------------------------------------------------------------- records

@dataclass
class Option:
    id: str
    name: str = ""
    description: str = ""
    baseline: bool = False
    golive: int = 0                 # months from the start of year 1
    owner: str = ""

    @property
    def golive_year(self) -> int:
        """The first year with the new solution live: go-live in month 1-12 is year 1, 13-24 year 2..."""
        return 0 if self.golive <= 0 else (self.golive - 1) // 12 + 1

    @property
    def label(self) -> str:
        return f"{self.id} · {self.name}" if self.name else self.id


@dataclass
class Cost:
    option: str
    item: str
    category: str
    kind: str
    year: int
    amount: float
    confidence: str = "medium"
    basis: str = ""

    @property
    def one_off(self) -> bool:
        return self.kind == "capex" or self.category in ONE_OFF


@dataclass
class Benefit:
    option: str
    name: str
    type: str
    hard: bool
    year: int
    amount: float
    kpi: str = ""
    baseline: str = ""
    target: str = ""
    owner: str = ""
    evidence: str = "estimate"
    assumptions: list = field(default_factory=list)


@dataclass
class Risk:
    option: str
    risk: str
    probability: float
    impact: float
    mitigation: str = ""
    owner: str = ""

    @property
    def expected(self) -> float:
        return self.probability * self.impact


@dataclass
class Assumption:
    id: str
    text: str
    value: str = ""
    source: str = ""
    owner: str = ""
    validated: bool = False


@dataclass
class Score:
    criterion: str
    weight: float
    option: str
    score: float
    note: str = ""


@dataclass
class Settings:
    organisation: str = "Your organisation"
    title: str = "IT business case"
    decision: str = ""
    review_date: date | None = None
    currency: str = "EUR"
    horizon: int = 5
    discount_rate: float = 0.08
    max_payback_years: float = 3.0
    hurdle_npv: float = 0.0
    driver_pct: float = 20.0           # an unvalidated assumption behind this share of an option's benefits is a finding
    contingency_pct: dict = field(default_factory=lambda: {"high": 5, "medium": 10, "low": 20})
    sensitivity_pct: float = 20.0
    delay_months: int = 6
    owners: dict = field(default_factory=lambda: {"FINANCE": "Finance business partner", "BENEFITS": "Business sponsor",
                                                  "COSTS": "IT programme manager", "RISKS": "IT programme manager",
                                                  "DECISION": "Investment committee"})

    @classmethod
    def load(cls, path: Path) -> "Settings":
        s = cls()
        if not path.exists():
            return s
        raw = json.loads(path.read_text(encoding="utf-8"))
        for k, v in raw.items():
            if k == "review_date":
                s.review_date = parse_d(v)
            elif k == "owners":
                s.owners.update(v)
            elif k == "contingency_pct":
                s.contingency_pct.update(v)
            elif hasattr(s, k):
                setattr(s, k, v)
        return s


@dataclass
class Data:
    settings: Settings
    options: list
    costs: list
    benefits: list
    risks: list
    assumptions: dict
    scores: list
    sources: dict = field(default_factory=dict)

    @property
    def baseline(self) -> Option | None:
        return next((o for o in self.options if o.baseline), None)

    def option(self, oid: str) -> Option | None:
        return next((o for o in self.options if o.id == oid), None)


def _year(v) -> int:
    n = num(re.sub(r"(?i)^y(ear)?\s*", "", str(v or "")))
    return int(n) if n is not None else 0


def load(folder: Path) -> Data:
    folder = Path(folder)
    missing = [f for f in REQUIRED if not (folder / f).exists()]
    if missing:
        raise FileNotFoundError(f"missing in {folder}: {', '.join(missing)}")
    s = Settings.load(folder / "settings.json")
    sources: dict[str, int] = {}

    def rows(name: str, aliases: dict) -> list[dict]:
        p = folder / name
        if not p.exists():
            return []
        r = _rows(p, aliases)
        sources[name] = len(r)
        return r

    options = [Option(r["id"], r.get("name", ""), r.get("description", ""), yes_no(r.get("baseline")), int(num(r.get("golive")) or 0),
                      r.get("owner", "")) for r in rows("options.csv", OPTION_ALIASES) if r.get("id")]
    if not options:
        raise ValueError("options.csv has no options")
    if sum(o.baseline for o in options) != 1:
        raise ValueError("options.csv needs exactly one baseline option (Baseline = yes): the cost of doing nothing")
    ids = {o.id for o in options}
    costs = []
    for r in rows("costs.csv", COST_ALIASES):
        if r.get("option") not in ids:
            raise ValueError(f"costs.csv: unknown option {r.get('option')!r}")
        cat = category(r.get("category") or r.get("item"))
        kind = "capex" if "capex" in _norm(r.get("kind")) else "opex"
        conf = _norm(r.get("confidence")) or "medium"
        costs.append(Cost(r["option"], r.get("item", ""), cat, kind, _year(r.get("year")), num(r.get("amount")) or 0.0,
                          conf if conf in CONF else "medium", r.get("basis", "")))
    benefits = []
    for r in rows("benefits.csv", BENEFIT_ALIASES):
        if r.get("option") not in ids:
            raise ValueError(f"benefits.csv: unknown option {r.get('option')!r}")
        benefits.append(Benefit(r["option"], r.get("name", ""), benefit_type(r.get("type") or r.get("name")),
                                _norm(r.get("kind")) not in {"soft", "non cashable", "noncashable", "intangible"},
                                _year(r.get("year")), num(r.get("amount")) or 0.0, r.get("kpi", ""), r.get("baseline", ""),
                                r.get("target", ""), r.get("owner", ""), evidence(r.get("evidence")),
                                [x for x in re.split(r"[\s,;]+", r.get("assumption", "")) if x]))
    risks = [Risk(r["option"], r.get("risk", ""), probability(r.get("probability")), num(r.get("impact")) or 0.0, r.get("mitigation", ""),
                  r.get("owner", "")) for r in rows("risks.csv", RISK_ALIASES) if r.get("option") in ids]
    assumptions = {r["id"]: Assumption(r["id"], r.get("text", ""), r.get("value", ""), r.get("source", ""), r.get("owner", ""),
                                       yes_no(r.get("validated"))) for r in rows("assumptions.csv", ASSUMPTION_ALIASES) if r.get("id")}
    scores = [Score(r.get("criterion", ""), num(r.get("weight")) or 0.0, r.get("option", ""), num(r.get("score")) or 0.0, r.get("note", ""))
              for r in rows("criteria.csv", CRITERIA_ALIASES) if r.get("option") in ids]
    return Data(s, options, costs, benefits, risks, assumptions, scores, sources)
