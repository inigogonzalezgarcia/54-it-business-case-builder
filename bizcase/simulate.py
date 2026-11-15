"""The demo: Proseware Leasing, a made-up vehicle leasing and consumer finance company (Madrid head office, Lisbon branch), deciding
what to do with its ERP before the end of mainstream support. Four options, five years. Writes the files the case reads to
sample_data/. Deterministic: the same files every time."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ORG = "Proseware Leasing"
TITLE = "ERP: upgrade, move to SaaS or stay"
REVIEW = "2026-11-15"

OPTIONS = [
    ("BASE", "Stay on the current ERP", "Keep the current version on extended support; customisations and servers as today.", "yes", 0, "CFO"),
    ("A", "Upgrade on premises", "Upgrade to the current on-premises release on new servers, carrying the customisations over.", "no", 12, "CIO"),
    ("B", "SaaS ERP, big bang", "Move finance and leasing operations to a SaaS ERP in one cut-over.", "no", 15, "CIO"),
    ("C", "SaaS ERP in two phases", "Finance first (month 9), leasing operations next (month 21), old ERP retired after phase 2.", "no", 9, "CIO"),
]
Y = range(1, 6)


def costs() -> list[list]:
    r = []

    def add(opt, item, cat, kind, years, amount, conf, basis):
        for y in ([years] if isinstance(years, int) else years):
            r.append([opt, item, cat, kind, y, amount(y) if callable(amount) else amount, conf, basis])

    # the cost of doing nothing
    add("BASE", "ERP licences and support", "licences", "opex", Y, lambda y: {1: 310000, 2: 380000, 3: 400000, 4: 420000, 5: 440000}[y],
        "high", "Current contract; extended support uplift from year 2")
    add("BASE", "Hardware maintenance for the ERP servers", "hardware maintenance", "opex", Y, 95000, "high", "Maintenance contract")
    add("BASE", "Data centre hosting and power", "hosting", "opex", Y, 60000, "high", "Facilities recharge")
    add("BASE", "Customisation upkeep (partner)", "licences", "opex", Y, 180000, "medium", "Last 2 years' invoices")
    add("BASE", "Internal ERP team (4 FTE)", "internal staff", "opex", Y, 300000, "high", "HR cost per FTE")
    add("BASE", "Security fixes on an unsupported release", "implementation", "opex", [3, 4, 5], 70000, "low", "Partner estimate")
    # A: upgrade on premises
    add("A", "New servers and storage", "hardware", "capex", 0, 420000, "high", "Vendor quote")
    add("A", "Upgrade project (partner)", "implementation", "capex", 0, 650000, "medium", "Partner estimate")
    add("A", "Customisations carried over", "migration", "capex", 0, 280000, "low", "Partner estimate, 140 objects")
    add("A", "Training", "training", "opex", 0, 60000, "medium", "Internal estimate")
    add("A", "Internal team on the project", "internal staff", "opex", 0, 150000, "high", "2 FTE for a year")
    add("A", "Retire the old servers", "decommission", "opex", 1, 20000, "medium", "Disposal quote")
    add("A", "Contingency", "contingency", "capex", 0, 120000, "medium", "")
    add("A", "ERP licences and support", "licences", "opex", Y, 290000, "high", "Vendor quote")
    add("A", "Hardware maintenance for the ERP servers", "hardware maintenance", "opex", [4, 5], 40000, "high", "Warranty 3 years")
    add("A", "Data centre hosting and power", "hosting", "opex", Y, 55000, "high", "Facilities recharge")
    add("A", "Customisation upkeep (partner)", "licences", "opex", Y, 150000, "medium", "Partner estimate")
    add("A", "Internal ERP team (4 FTE)", "internal staff", "opex", Y, 300000, "high", "HR cost per FTE")
    # B: SaaS, big bang (built quickly: no migration, decommission or contingency lines, and the old ERP is dropped in year 1)
    add("B", "Implementation partner", "implementation", "capex", 0, 900000, "medium", "Vendor's partner, fixed price not agreed")
    add("B", "Implementation partner", "implementation", "capex", 1, 300000, "medium", "")
    add("B", "Training", "training", "opex", 0, 80000, "medium", "Internal estimate")
    add("B", "Internal team on the project", "internal staff", "opex", 0, 220000, "high", "3 FTE")
    add("B", "Internal team on the project", "internal staff", "opex", 1, 150000, "high", "2 FTE")
    add("B", "SaaS ERP subscription", "subscription", "opex", Y, 260000, "low", "List price less a 35 % discount (A2)")
    add("B", "ERP licences and support", "licences", "opex", 1, 310000, "high", "Current contract until cut-over")
    add("B", "Data centre hosting and power", "hosting", "opex", 1, 60000, "high", "Until cut-over")
    add("B", "Internal ERP team (2 FTE)", "internal staff", "opex", [2, 3, 4, 5], 150000, "high", "HR cost per FTE")
    # C: SaaS in two phases
    add("C", "Implementation partner", "implementation", "capex", 0, 600000, "medium", "Fixed price per phase, signed proposal")
    add("C", "Implementation partner", "implementation", "capex", 1, 200000, "medium", "Phase 2")
    add("C", "Data and customisation migration", "migration", "capex", 0, 200000, "medium", "Fit-gap of 140 objects: 90 retired")
    add("C", "Data and customisation migration", "migration", "capex", 1, 50000, "medium", "Phase 2")
    add("C", "Training", "training", "opex", 0, 70000, "medium", "Train-the-trainer, 2 waves")
    add("C", "Internal team on the project", "internal staff", "opex", 0, 200000, "high", "3 FTE")
    add("C", "Internal team on the project", "internal staff", "opex", 1, 120000, "high", "2 FTE")
    add("C", "Retire the old ERP (archive, contracts, disposal)", "decommission", "opex", 2, 40000, "medium", "Archive quote")
    add("C", "Contingency", "contingency", "capex", 0, 120000, "medium", "10 % of one-off costs")
    add("C", "SaaS ERP subscription", "subscription", "opex", Y, lambda y: 200000 if y == 1 else 300000, "high",
        "Signed quote, 3-year price cap (A4)")
    add("C", "ERP licences and support", "licences", "opex", [1, 2], lambda y: 310000 if y == 1 else 150000, "high", "Until phase 2")
    add("C", "Hardware maintenance for the ERP servers", "hardware maintenance", "opex", [1, 2], lambda y: 95000 if y == 1 else 45000,
        "high", "Until phase 2")
    add("C", "Data centre hosting and power", "hosting", "opex", [1, 2], lambda y: 60000 if y == 1 else 30000, "high", "Until phase 2")
    add("C", "Internal ERP team", "internal staff", "opex", Y, lambda y: 300000 if y == 1 else 190000, "high", "4 FTE, then 2.5")
    return r


def benefits() -> list[list]:
    r = []

    def add(opt, name, typ, kind, years, amount, kpi, base, target, owner, ev, asm=""):
        for y in years:
            r.append([opt, name, typ, kind, y, amount, kpi, base, target, owner, ev, asm])

    add("A", "Fewer ERP incidents", "avoidance", "hard", [2, 3, 4, 5], 40000, "P1/P2 ERP incidents a month", "22", "12",
        "Head of Operations", "measured")
    add("B", "Stop hardware maintenance for the ERP servers", "saving", "hard", Y, 95000, "", "", "", "IT Director", "measured")
    add("B", "Faster month-end close (overtime)", "productivity", "hard", Y, 70000, "Days to close", "8", "5", "", "estimate", "A1")
    add("B", "Self-service reports replace the BI contractor", "saving", "hard", [2, 3, 4, 5], 120000, "", "", "", "CFO",
        "assumption", "A3")
    add("B", "Fewer ERP incidents", "avoidance", "hard", [3, 4, 5], 40000, "P1/P2 ERP incidents a month", "22", "10",
        "Head of Operations", "estimate")
    add("C", "Self-service reports replace the BI contractor", "saving", "hard", [2, 3, 4, 5], 120000, "BI contractor days a month",
        "18", "0", "CFO", "measured", "A4")
    add("C", "Fewer ERP incidents", "avoidance", "hard", [2, 3, 4, 5], 40000, "P1/P2 ERP incidents a month", "22", "10",
        "Head of Operations", "measured")
    add("C", "Faster month-end close (overtime)", "productivity", "soft", [2, 3, 4, 5], 70000, "Days to close", "8", "5",
        "Financial Controller", "estimate", "A1")
    add("C", "Leasing quotes approved the same day", "revenue", "soft", [3, 4, 5], 90000, "Quotes approved within 24 h", "61 %",
        "90 %", "Head of Sales", "estimate")
    return r


def risks() -> list[list]:
    return [
        ["A", "Customisations break on the new release", "medium", 250000, "Regression test pack of 140 objects", "IT programme manager"],
        ["A", "Extended support needed again in 2032", "low", 300000, "Roadmap review in year 3", "CIO"],
        ["B", "Big-bang cut-over fails at a month-end", "medium", 600000, "", ""],
        ["B", "Customisations the SaaS cannot do", "40 %", 350000, "Fit-gap before signing", "IT programme manager"],
        ["C", "Two ERPs in parallel for a year", "high", 120000, "Interfaces frozen; one reconciliation a week", "Financial Controller"],
        ["C", "Leasing operations phase slips", "medium", 200000, "Phase 2 starts only after phase 1 closes two month-ends",
         "IT programme manager"],
    ]


def assumptions() -> list[list]:
    return [
        ["A1", "Month-end close falls from 8 to 5 days with the standard close process", "3 days", "Vendor reference customers",
         "Financial Controller", "no"],
        ["A2", "The vendor gives a 35 % discount on the list price", "35 %", "Account manager's email", "Procurement", "no"],
        ["A3", "The BI contractor can be released when self-service reports go live", "120k EUR/yr", "IT Director", "CFO", "no"],
        ["A4", "Subscription price capped for 3 years and BI contractor released at phase 1", "300k EUR/yr", "Signed quote; contract notice "
         "period 3 months", "Procurement", "yes"],
    ]


def criteria() -> list[list]:
    w = [("Strategic fit", 30), ("Business risk of the change", 25), ("Security and support", 20), ("Skills we have", 15),
         ("Vendor lock-in", 10)]
    sc = {"BASE": [1, 4, 1, 5, 3], "A": [2, 3, 4, 4, 3], "B": [5, 1, 5, 2, 2], "C": [5, 4, 5, 3, 2]}
    return [[c, wt, o, sc[o][i]] for o in sc for i, (c, wt) in enumerate(w)]


def _w(path: Path, head: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(head)
        w.writerows(rows)


def write(folder: Path) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _w(folder / "options.csv", ["Option", "Name", "Description", "Baseline", "GoLiveMonth", "Owner"], OPTIONS)
    _w(folder / "costs.csv", ["Option", "Item", "Category", "Type", "Year", "Amount", "Confidence", "Basis"], costs())
    _w(folder / "benefits.csv", ["Option", "Benefit", "Type", "Kind", "Year", "Amount", "KPI", "Baseline", "Target", "Owner", "Evidence",
                                 "Assumption"], benefits())
    _w(folder / "risks.csv", ["Option", "Risk", "Probability", "Impact", "Mitigation", "Owner"], risks())
    _w(folder / "assumptions.csv", ["Id", "Assumption", "Value", "Source", "Owner", "Validated"], assumptions())
    _w(folder / "criteria.csv", ["Criterion", "Weight", "Option", "Score"], criteria())
    (folder / "settings.json").write_text(json.dumps({
        "organisation": ORG, "title": TITLE, "review_date": REVIEW,
        "decision": "Which ERP option to fund before mainstream support ends in December 2027.",
        "currency": "EUR", "horizon": 5, "discount_rate": 0.08, "max_payback_years": 4, "hurdle_npv": 0, "driver_pct": 20,
        "contingency_pct": {"high": 5, "medium": 10, "low": 20}, "sensitivity_pct": 20, "delay_months": 6,
        "owners": {"FINANCE": "Finance business partner", "BENEFITS": "Business sponsor (CFO)", "COSTS": "IT programme manager",
                   "RISKS": "IT programme manager", "DECISION": "Investment committee"}}, indent=2) + "\n", encoding="utf-8")


def template(folder: Path) -> None:
    """Empty files with the columns the case reads, one example row each, and the default settings."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _w(folder / "options.csv", ["Option", "Name", "Description", "Baseline", "GoLiveMonth", "Owner"],
       [["BASE", "Do nothing", "What it costs to keep today's platform for the whole horizon", "yes", 0, ""],
        ["A", "First option", "", "no", 12, ""]])
    _w(folder / "costs.csv", ["Option", "Item", "Category", "Type", "Year", "Amount", "Confidence", "Basis"],
       [["BASE", "Support contract", "licences", "opex", 1, 0, "high", "current contract"],
        ["A", "Implementation partner", "implementation", "capex", 0, 0, "medium", "quote"]])
    _w(folder / "benefits.csv", ["Option", "Benefit", "Type", "Kind", "Year", "Amount", "KPI", "Baseline", "Target", "Owner", "Evidence",
                                 "Assumption"], [["A", "", "saving", "hard", 1, 0, "", "", "", "", "estimate", ""]])
    _w(folder / "risks.csv", ["Option", "Risk", "Probability", "Impact", "Mitigation", "Owner"], [["A", "", "30 %", 0, "", ""]])
    _w(folder / "assumptions.csv", ["Id", "Assumption", "Value", "Source", "Owner", "Validated"], [["A1", "", "", "", "", "no"]])
    _w(folder / "criteria.csv", ["Criterion", "Weight", "Option", "Score"], [["Strategic fit", 100, "A", 3]])
    (folder / "settings.json").write_text(json.dumps({
        "organisation": "Your organisation", "title": "IT business case", "review_date": "", "decision": "",
        "currency": "EUR", "horizon": 5, "discount_rate": 0.08, "max_payback_years": 3, "hurdle_npv": 0, "driver_pct": 20,
        "contingency_pct": {"high": 5, "medium": 10, "low": 20}, "sensitivity_pct": 20, "delay_months": 6}, indent=2) + "\n", encoding="utf-8")
