"""Command line: `demo` writes the fictional Proseware Leasing case to sample_data/ and builds the outputs; `template` writes empty
files to fill in; `build` runs on your own files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report, simulate
from .checks import _money, review, summary
from .model import load

OUTPUTS = ("report.html", "business-case.md", "options-summary.csv", "cashflows.csv", "sensitivity.csv", "benefits-register.csv",
           "assumptions-review.csv", "findings.csv", "actions.csv")


def run(data: Path, out: Path, title: str | None = None) -> dict:
    d = load(data)
    rv = review(d)
    s = d.settings
    title = title or f"{s.organisation} · {s.title}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, title), encoding="utf-8")
    (out / "business-case.md").write_text(report.paper_md(d, rv, title), encoding="utf-8")
    report.write_options(d, rv, out / "options-summary.csv")
    report.write_cashflows(d, rv, out / "cashflows.csv")
    report.write_sensitivity(rv, out / "sensitivity.csv")
    report.write_benefits(d, rv, out / "benefits-register.csv")
    report.write_assumptions(d, rv, out / "assumptions-review.csv")
    report.write_findings(rv, out / "findings.csv")
    report.write_actions(rv, out / "actions.csv")
    sm = summary(d, rv)
    sm["currency"] = s.currency
    return sm


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bizcase", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional case to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    tp = sub.add_parser("template", help="write empty CSV files with the expected columns, and a settings.json, to fill in")
    tp.add_argument("folder", type=Path)
    bd = sub.add_parser("build", help="build the outputs from your own files")
    bd.add_argument("data", type=Path, nargs="?", help="folder with options.csv, costs.csv and the optional files")
    bd.add_argument("--data", dest="data_opt", type=Path, help="same as the positional folder")
    bd.add_argument("--out", type=Path, default=Path("output"))
    bd.add_argument("--title", help="title of the report and the paper")
    a = p.parse_args(argv)
    if a.cmd == "template":
        if (a.folder / "options.csv").exists():
            print(f"error: {a.folder} already has an options.csv; nothing written", file=sys.stderr)
            return 2
        simulate.template(a.folder)
        print(f"empty files in {a.folder}/: {', '.join(sorted(p.name for p in a.folder.iterdir()))}")
        return 0
    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out)
    else:
        folder = a.data or a.data_opt
        if not folder:
            print("error: give the folder with options.csv and costs.csv", file=sys.stderr)
            return 2
        try:
            sm = run(folder, a.out, a.title)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    cur = sm["currency"]
    if sm["recommended"]:
        print(f"Recommended: {sm['recommended']} · NPV {_money(sm['npv'], cur)} ({_money(sm['pess_npv'], cur)} pessimistic) · payback "
              f"{sm['payback']:.1f} years · case quality {sm['status']}: {sm['red']} red and {sm['amber']} amber findings")
    else:
        print(f"No option recommended · case quality {sm['status']}: {sm['red']} red and {sm['amber']} amber findings")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
