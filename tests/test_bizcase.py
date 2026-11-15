import csv
import json
from pathlib import Path

import pytest

from bizcase import simulate
from bizcase.checks import RED, irr, npv, payback, review, summary
from bizcase.cli import OUTPUTS, main, run
from bizcase.model import category, load, num, probability

OPT_HEAD = ["Option", "Name", "Description", "Baseline", "GoLiveMonth", "Owner"]
COST_HEAD = ["Option", "Item", "Category", "Type", "Year", "Amount", "Confidence", "Basis"]
BEN_HEAD = ["Option", "Benefit", "Type", "Kind", "Year", "Amount", "KPI", "Baseline", "Target", "Owner", "Evidence", "Assumption"]


def write(path: Path, head: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        w.writerows(rows)


def clean_costs(oid: str = "X") -> list[list]:
    """A complete option: every cost category, running cost every year, enough contingency."""
    rows = [[oid, "Implementation partner", "implementation", "capex", 0, 200000, "high", "quote"],
            [oid, "Data migration", "migration", "capex", 0, 50000, "high", "quote"],
            [oid, "Training", "training", "opex", 0, 20000, "high", "quote"],
            [oid, "Internal staff on the project", "internal-staff", "opex", 0, 30000, "high", "timesheets"],
            [oid, "Decommission old platform", "decommission", "opex", 1, 10000, "high", "quote"],
            [oid, "Contingency", "contingency", "capex", 0, 20000, "high", "5 %"]]
    rows += [[oid, "Subscription", "subscription", "opex", y, 50000, "high", "contract"] for y in range(1, 6)]
    return rows


def case(tmp_path: Path, costs=None, benefits=None, golive=6, assumptions=None, settings=None) -> Path:
    write(tmp_path / "options.csv", OPT_HEAD, [["BASE", "Stay", "", "yes", 0, "CFO"], ["X", "New platform", "", "no", golive, "CIO"]])
    base = [["BASE", "Server maintenance contract", "licences", "opex", y, 150000, "high", "contract"] for y in range(1, 6)]
    write(tmp_path / "costs.csv", COST_HEAD, base + (costs if costs is not None else clean_costs()))
    write(tmp_path / "benefits.csv", BEN_HEAD, benefits if benefits is not None else
          [["X", "Fewer incidents", "risk", "hard", y, 20000, "P1 incidents a year", "12", "4", "Head of operations", "measured", ""]
           for y in range(1, 6)])
    if assumptions is not None:
        write(tmp_path / "assumptions.csv", ["Id", "Assumption", "Value", "Source", "Owner", "Validated"], assumptions)
    (tmp_path / "settings.json").write_text(json.dumps({"organisation": "Test", "review_date": "2026-11-15", "max_payback_years": 4,
                                                        **(settings or {})}))
    return tmp_path


def codes(rv) -> dict:
    out = {}
    for f in rv["findings"]:
        out.setdefault(f.code, f.severity)
    return out


def test_parsers():
    assert num("1.250.000") == 1250000 and num("1,250,000") == 1250000 and num("€ 12 500") == 12500 and num("-3.000") == -3000
    assert probability("30 %") == pytest.approx(0.3) and probability("high") == 0.6 and probability(0.2) == 0.2
    assert category("Data centre hosting") == "hosting" and category("Data migration") == "migration"
    assert category("Hardware maintenance") == "licences" and category("New servers") == "hardware"
    assert category("SaaS subscription") == "subscription" and category("Retire old servers") == "decommission"


def test_finance_maths():
    assert npv([-100, 110], 0.10) == pytest.approx(0)
    assert irr([-100, 60, 60]) == pytest.approx(0.1307, abs=1e-3)
    assert irr([-100, 10, 10]) is not None and irr([-100, -10]) is None
    assert payback([-100, 50, 50, 50]) == pytest.approx(2.0)
    assert payback([-100, 40, 40, 40]) == pytest.approx(2.5)
    assert payback([-100, 10, 10]) is None


def test_clean_case_is_green_and_recommended(tmp_path):
    rv = review(load(case(tmp_path)))
    assert not [f for f in rv["findings"] if f.severity == RED], [f.code for f in rv["findings"]]
    assert rv["recommended"] == "X"
    m = rv["case"].metrics("X")
    # year 0: -320k (one-off and our own people); then 150k baseline - 50k subscription + 20k benefits (10k decommission in year 1)
    assert m["net"][0] == pytest.approx(-320000) and m["net"][1] == pytest.approx(110000) and m["net"][2] == pytest.approx(120000)
    assert m["payback"] == pytest.approx(2 + 90000 / 120000)


def test_double_counted_saving_is_removed(tmp_path):
    ben = [["X", "Server maintenance saving", "saving", "hard", y, 150000, "Contract cost", "150k", "0", "CFO", "measured", ""]
           for y in range(1, 6)]
    rv = review(load(case(tmp_path, benefits=ben)))
    assert codes(rv)["BEN-DOUBLE"] == RED
    assert rv["case"].metrics("X", clean=False)["npv"] > rv["case"].metrics("X")["npv"] + 500000
    assert sum(rv["case"].benefits("X")) == 0


def test_benefits_before_golive_are_excluded(tmp_path):
    ben = [["X", "Fewer incidents", "risk", "hard", y, 20000, "P1", "12", "4", "Ops", "measured", ""] for y in range(1, 6)]
    rv = review(load(case(tmp_path, benefits=ben, golive=18)))       # live in year 2
    assert codes(rv)["BEN-EARLY"] == RED
    assert rv["case"].benefits("X")[1] == 0 and rv["case"].benefits("X")[2] == 20000
    assert not rv["case"].ready("X")


def test_hard_benefit_without_owner_moves_to_soft(tmp_path):
    ben = [["X", "Fewer incidents", "risk", "hard", y, 20000, "P1", "12", "4", "", "measured", ""] for y in range(1, 6)]
    rv = review(load(case(tmp_path, benefits=ben)))
    assert codes(rv)["BEN-NOOWNER"] == RED
    m = rv["case"].metrics("X")
    assert m["soft"] == pytest.approx(100000) and sum(rv["case"].benefits("X")) == 0


def test_productivity_and_missing_kpi(tmp_path):
    ben = [["X", "Time saved on month-end close", "productivity", "hard", y, 10000, "", "", "", "CFO", "estimate", ""] for y in range(1, 6)]
    c = codes(review(load(case(tmp_path, benefits=ben))))
    assert c["BEN-PRODUCTIVITY"] == "AMBER" and c["BEN-NOKPI"] == "AMBER"


def test_unvalidated_assumption_driving_the_case(tmp_path):
    ben = [["X", "Fewer incidents", "risk", "hard", y, 20000, "P1", "12", "4", "Ops", "assumption", "A1"] for y in range(1, 6)]
    asm = [["A1", "Vendor says incidents halve", "50 %", "Vendor deck", "Head of operations", "no"]]
    rv = review(load(case(tmp_path, benefits=ben, assumptions=asm)))
    assert codes(rv)["ASM-UNVALIDATED"] == RED
    asm[0][5] = "yes"
    assert "ASM-UNVALIDATED" not in codes(review(load(case(tmp_path, benefits=ben, assumptions=asm))))


def test_missing_costs_and_contingency(tmp_path):
    costs = [r for r in clean_costs() if r[2] not in ("decommission", "training", "contingency")]
    rv = review(load(case(tmp_path, costs=costs)))
    c = codes(rv)
    assert c["COST-MISSING"] == RED and c["COST-CONTINGENCY"] == RED
    kinds = {f.title for f in rv["findings"] if f.code == "COST-MISSING"}
    assert kinds == {"No decommission cost", "No training cost"}
    assert rv["case"].shortfall["X"] == pytest.approx((200000 + 50000) * 0.05)   # our own people are not one-off
    assert rv["case"].costs("X")[0] == pytest.approx(280000)
    assert rv["case"].flows("X")["cost"][0] == pytest.approx(280000 + 12500)


def test_missing_running_cost_years(tmp_path):
    costs = [r for r in clean_costs() if not (r[2] == "subscription" and r[4] >= 4)]
    rv = review(load(case(tmp_path, costs=costs)))
    f = next(f for f in rv["findings"] if f.code == "COST-RUN")
    assert "4, 5" in f.detail and rv["recommended"] is None


def test_never_pays_back_is_not_recommended(tmp_path):
    ben = [["X", "Fewer incidents", "risk", "hard", y, 1000, "P1", "12", "4", "Ops", "measured", ""] for y in range(1, 6)]
    costs = clean_costs()
    costs = [r[:5] + [r[5] * 4 if r[2] == "subscription" else r[5]] + r[6:] for r in costs]
    rv = review(load(case(tmp_path, costs=costs, benefits=ben)))
    assert codes(rv)["FIN-PAYBACK"] == RED and rv["recommended"] is None


def test_sensitivity_and_decisions(tmp_path):
    rv = review(load(case(tmp_path)))
    sens = {k: dd for k, _, dd in rv["sensitivity"]}
    assert sens["Costs +20 %"] < 0 and sens["Optimistic estimates"] > 0 and sens["Go-live 6 months later"] < 0
    assert rv["decisions"][0].decision.startswith("Approve") and "X" in rv["decisions"][0].decision


def test_load_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path)
    write(tmp_path / "options.csv", OPT_HEAD, [["A", "One", "", "no", 0, ""], ["B", "Two", "", "no", 0, ""]])
    write(tmp_path / "costs.csv", COST_HEAD, [])
    with pytest.raises(ValueError, match="baseline"):
        load(tmp_path)


def test_demo_end_to_end(tmp_path):
    simulate.write(tmp_path / "data")
    sm = run(tmp_path / "data", tmp_path / "out")
    assert sm["recommended"] == "C" and sm["status"] == RED and sm["red"] >= 5
    for name in OUTPUTS:
        assert (tmp_path / "out" / name).stat().st_size > 200, name
    rows = list(csv.DictReader(open(tmp_path / "out" / "options-summary.csv", encoding="utf-8")))
    b = next(r for r in rows if r["option"] == "B")
    assert b["status"] == "not ready" and float(b["npv_as_submitted"]) > float(b["npv"])
    md = (tmp_path / "out" / "business-case.md").read_text(encoding="utf-8")
    assert "Recommendation: C" in md and "Decisions needed" in md
    html = (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert "<svg" in html and "Proseware Leasing" in html


def test_cli_build_errors(tmp_path, capsys):
    assert main(["build", str(tmp_path)]) == 2
    assert "missing" in capsys.readouterr().err


def test_template_loads(tmp_path, capsys):
    assert main(["template", str(tmp_path / "t")]) == 0
    d = load(tmp_path / "t")
    assert d.baseline.id == "BASE" and [o.id for o in d.options] == ["BASE", "A"]
    assert main(["template", str(tmp_path / "t")]) == 2
