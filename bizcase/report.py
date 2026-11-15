"""Outputs: report.html (the recommendation, options side by side as submitted and after the checks, cumulative cash flow,
sensitivity, benefits, assumptions, risks, scores and findings), business-case.md (the paper for the committee), and the CSVs:
options-summary, cashflows, sensitivity, benefits-register, assumptions-review, findings and actions."""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from .checks import GROUPS, RED, Case, _money, summary
from .model import FILES, Data

e = html.escape
TODO = "**[TO COMPLETE]**"


def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _r(x) -> str:
    return "" if x is None else f"{x:.0f}"


def _pb(x) -> str:
    return "never" if x is None else f"{x:.1f} years"


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0f} %"


def _irr(x) -> str:
    return "–" if x is None else f"{x * 100:.1f} %"


def _sc(x) -> str:
    return "" if x is None else f"{x:.0f}"


def _day(x) -> str:
    return "–" if x is None else f"{x:%d %b %Y}"


def option_rows(d: Data, rv: dict) -> list[dict]:
    c: Case = rv["case"]
    sc = c.scores()
    out = []
    for o in d.options:
        if o.baseline:
            continue
        raw, m, p, op = c.metrics(o.id, clean=False), c.metrics(o.id), c.metrics(o.id, "pessimistic"), c.metrics(o.id, "optimistic")
        out.append({"o": o, "raw": raw, "m": m, "p": p, "op": op, "score": sc.get(o.id), "ready": c.ready(o.id),
                    "red": sum(f.severity == RED for f in rv["findings"] if f.option == o.id),
                    "amber": sum(f.severity != RED for f in rv["findings"] if f.option == o.id)})
    return out


# ---------------------------------------------------------------- csv

def write_options(d: Data, rv: dict, path: Path) -> None:
    rows = []
    base_sc = rv["case"].scores().get(d.baseline.id)
    rows.append([d.baseline.id, d.baseline.name, "baseline", "", "", "", "", "", "", "", "", "", "", _r(sum(rv["case"].costs(d.baseline.id))),
                 "" if base_sc is None else f"{base_sc:.0f}", "", ""])
    for x in option_rows(d, rv):
        o, raw, m, p, op = x["o"], x["raw"], x["m"], x["p"], x["op"]
        rows.append([o.id, o.name, "recommended" if o.id == rv["recommended"] else ("ready" if x["ready"] else "not ready"),
                     _r(raw["npv"]), _r(m["npv"]), _r(p["npv"]), _r(op["npv"]), _r(m["risk_npv"]),
                     "" if m["irr"] is None else f"{m['irr'] * 100:.1f}", "" if m["payback"] is None else f"{m['payback']:.2f}",
                     "" if m["roi"] is None else f"{m['roi']:.0f}", _r(m["one_off"]), _r(m["soft"]), _r(m["tco"]),
                     "" if x["score"] is None else f"{x['score']:.0f}", x["red"], x["amber"]])
    _w(path, ["option", "name", "status", "npv_as_submitted", "npv", "npv_pessimistic", "npv_optimistic", "npv_risk_adjusted", "irr_pct",
              "payback_years", "roi_pct", "one_off_cost", "soft_benefits", "tco", "weighted_score", "red_findings", "amber_findings"], rows)


def write_cashflows(d: Data, rv: dict, path: Path) -> None:
    c: Case = rv["case"]
    rows = []
    for o in d.options:
        if o.baseline:
            continue
        f = c.flows(o.id)
        cum = 0.0
        for y in range(c.H + 1):
            cum += f["net"][y]
            rows.append([o.id, y, _r(f["base"][y]), _r(f["cost"][y]), _r(f["base"][y] - f["cost"][y]), _r(f["benefits"][y]), _r(f["net"][y]),
                         _r(cum), _r(f["net"][y] / (1 + d.settings.discount_rate) ** y)])
    _w(path, ["option", "year", "baseline_cost", "option_cost", "cost_difference", "hard_benefits", "net", "cumulative", "discounted"], rows)


def write_sensitivity(rv: dict, path: Path) -> None:
    _w(path, ["scenario", "npv", "change_vs_base"], [[k, _r(v), _r(dd)] for k, v, dd in rv["sensitivity"]])


def benefit_rows(d: Data, rv: dict) -> list[list]:
    c: Case = rv["case"]
    by = defaultdict(list)
    for i, b in enumerate(d.benefits):
        by[(b.option, b.name)].append((i, b))
    rows = []
    for (oid, name), xs in by.items():
        b = xs[0][1]
        o = d.option(oid)
        total = sum(x.amount for _, x in xs)
        counted = sum(x.amount for i, x in xs if x.hard and i not in c.moved_soft and not (i in c.excluded and x.year in c.excluded[i][1]))
        reason = "; ".join(sorted({c.excluded[i][0] for i, _ in xs if i in c.excluded} | ({"no owner: soft"} if any(i in c.moved_soft for i, _ in xs) else set())))
        start = d.settings.review_date
        live = (start + timedelta(days=30 * o.golive)) if start and o.golive else None
        rows.append([oid, name, b.type, "hard" if b.hard else "soft", min(x.year for _, x in xs), _r(total), _r(counted), reason, b.kpi,
                     b.baseline, b.target, b.owner, b.evidence, ";".join(b.assumptions),
                     _day(live + timedelta(days=182)) if live else "", _day(live + timedelta(days=365)) if live else ""])
    return rows


def write_benefits(d: Data, rv: dict, path: Path) -> None:
    _w(path, ["option", "benefit", "type", "kind", "from_year", "total", "counted_in_npv", "not_counted_because", "kpi", "baseline", "target",
              "owner", "evidence", "assumptions", "review_6_months", "review_12_months"], benefit_rows(d, rv))


def write_assumptions(d: Data, rv: dict, path: Path) -> None:
    used = defaultdict(lambda: defaultdict(float))
    for b in d.benefits:
        for a in b.assumptions:
            used[a][b.option] += b.amount
    _w(path, ["id", "assumption", "value", "source", "owner", "validated", "benefit_value_by_option", "flagged"],
       [[a.id, a.text, a.value, a.source, a.owner, "yes" if a.validated else "no",
         "; ".join(f"{o} {_r(v)}" for o, v in used[a.id].items()),
         "yes" if any(f.code == "ASM-UNVALIDATED" and f.detail.startswith(a.id + ":") for f in rv["findings"]) else "no"]
        for a in d.assumptions.values()])


def write_findings(rv: dict, path: Path) -> None:
    _w(path, ["severity", "code", "group", "option", "title", "detail", "action", "owner", "due"],
       [[f.severity, f.code, GROUPS[f.group], f.option, f.title, f.detail, f.action, f.owner, "" if not f.due else f.due.isoformat()]
        for f in rv["findings"]])


def actions(rv: dict) -> list:
    return [(f"A-{i:03d}", f) for i, f in enumerate(rv["findings"], 1)]


def write_actions(rv: dict, path: Path) -> None:
    _w(path, ["ref", "severity", "code", "option", "action", "owner", "due", "done"],
       [[ref, f.severity, f.code, f.option, f.action, f.owner, "" if not f.due else f.due.isoformat(), ""] for ref, f in actions(rv)])


# ---------------------------------------------------------------- the paper

def _md(x) -> str:
    return str(x).replace("|", "/").replace("\n", " ")


def paper_md(d: Data, rv: dict, title: str) -> str:
    s, cur = d.settings, d.settings.currency
    sm = summary(d, rv)
    c: Case = rv["case"]
    rec = d.option(rv["recommended"]) if rv["recommended"] else None
    out = [f"# {title}", "",
           f"> Prepared on {_day(s.review_date)} for the {s.owners.get('DECISION', 'committee').lower()}. Every option is compared with "
           f"the cost of doing nothing ({d.baseline.name}) over {s.horizon} years at a {s.discount_rate * 100:g} % discount rate. "
           f"Figures are after the quality checks; sections marked {TODO} are for the meeting.", "",
           f"**The decision:** {_md(s.decision) or TODO}", ""]
    if rec:
        m = c.metrics(rec.id)
        out += [f"**Recommendation: {rec.label}.** NPV {_money(m['npv'], cur)}, IRR {_irr(m['irr'])}, payback {_pb(m['payback'])}, "
                f"one-off cost {_money(m['one_off'], cur)}; {_money(c.metrics(rec.id, 'pessimistic')['npv'], cur)} in the pessimistic case. "
                + _md(rv["why"]), ""]
    else:
        out += [f"**No recommendation.** {_md(rv['why'])}", ""]
    out += ["## Options", "", f"| Option | NPV as submitted | NPV after checks | Pessimistic | Payback | ROI | One-off | Score | Ready |",
            "|---|---|---|---|---|---|---|---|---|"]
    for x in option_rows(d, rv):
        o = x["o"]
        out.append(f"| {'**' if o.id == rv['recommended'] else ''}{_md(o.label)}{'**' if o.id == rv['recommended'] else ''} | "
                   f"{_money(x['raw']['npv'], cur)} | {_money(x['m']['npv'], cur)} | {_money(x['p']['npv'], cur)} | {_pb(x['m']['payback'])} | "
                   f"{_pct(x['m']['roi'])} | {_money(x['m']['one_off'], cur)} | {_sc(x['score'])} | "
                   f"{'yes' if x['ready'] else 'no: ' + str(x['red']) + ' red'} |")
    out += ["", f"Removed by the checks: {_money(sm['removed'], cur)} of benefits counted twice, booked before go-live or with no owner.", ""]
    if rec:
        f = c.flows(rec.id)
        out += [f"## Cash flow: {_md(rec.label)}", "", "| Year | " + " | ".join(str(y) for y in range(c.H + 1)) + " |",
                "|---|" + "---|" * (c.H + 1)]
        cum, cums = 0.0, []
        for v in f["net"]:
            cum += v
            cums.append(cum)
        for label, vals in (("Cost of doing nothing", f["base"]), ("Cost of the option", f["cost"]), ("Hard benefits", f["benefits"]),
                            ("Net", f["net"]), ("Cumulative", cums)):
            out.append(f"| {label} | " + " | ".join(_money(v, '').strip() for v in vals) + " |")
        out += ["", "## Sensitivity", "", "| Scenario | NPV | Change |", "|---|---|---|"]
        out += [f"| {k} | {_money(v, cur)} | {_money(dd, cur)} |" for k, v, dd in rv["sensitivity"]]
        out += ["", "## Benefits and who delivers them", "", "| Benefit | Kind | Counted | KPI: today → target | Owner | Reviews |",
                "|---|---|---|---|---|---|"]
        for r in benefit_rows(d, rv):
            if r[0] == rec.id:
                out.append(f"| {_md(r[1])} | {r[3]} | {_money(float(r[6] or 0), cur)} | {_md(r[8])}: {_md(r[9])} → {_md(r[10])} | "
                           f"{_md(r[11]) or TODO} | {r[14]}, {r[15]} |")
        out += ["", "## Risks", "", "| Risk | Probability | Impact | Mitigation | Owner |", "|---|---|---|---|---|"]
        out += [f"| {_md(x.risk)} | {x.probability * 100:.0f} % | {_money(x.impact, cur)} | {_md(x.mitigation) or TODO} | {_md(x.owner) or TODO} |"
                for x in d.risks if x.option == rec.id]
    out += ["", "## Decisions needed", "", "| # | Decision | Options | Proposed | Owner | Needed by | Outcome |", "|---|---|---|---|---|---|---|"]
    out += [f"| {x.id} | **{_md(x.decision)}**<br>{_md(x.why)} | {_md(x.options)} | {_md(x.proposed)} | {_md(x.owner)} | {_day(x.needed_by)} | |"
            for x in rv["decisions"]]
    out += ["", "## Quality checks", "", f"{sm['red']} red and {sm['amber']} amber findings; all of them in `findings.csv`.", "",
            "| Severity | Option | Finding | Action |", "|---|---|---|---|"]
    out += [f"| {f.severity} | {f.option} | **{_md(f.title)}**: {_md(f.detail)} | {_md(f.action)} |" for f in rv["findings"]]
    out += ["", "## Assumptions", "", "| Id | Assumption | Source | Owner | Validated |", "|---|---|---|---|---|"]
    out += [f"| {a.id} | {_md(a.text)} | {_md(a.source)} | {_md(a.owner)} | {'yes' if a.validated else '**no**'} |" for a in d.assumptions.values()]
    out += ["", "## Method and sources", "",
            f"- Net cash flow per year = cost of doing nothing − cost of the option + hard benefits. Year 0 is the investment.",
            f"- Pessimistic and optimistic cases: each cost moves by its confidence (high, medium, low) and each benefit by its evidence "
            "(measured, estimate, assumption). Risk-adjusted NPV subtracts probability × impact of the option's risks.",
            "- After the checks: benefits counted twice or booked before go-live are removed, hard benefits with no owner are moved to "
            "soft, and the missing contingency is added in year 0.", "", "| Source | File | Rows |", "|---|---|---|"]
    out += [f"| {FILES.get(k, k)} | `{k}` | {v} |" for k, v in d.sources.items()]
    out += ["", "## Notes", "", f"- Decision taken: {TODO}", f"- Conditions: {TODO}", f"- Next review: {TODO}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;
--g:#cfeedd;--a:#fbe6bd;--r:#f8d2cd;--n:#eef0f2;--c1:#0b6bcb;--c2:#a46200;--c3:#1e7a4c;--c4:#7a4cc2}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;
--bad:#f2685c;--info:#5aa9f0;--g:#173527;--a:#3d2f12;--r:#45201d;--n:#232a31;--c1:#5aa9f0;--c2:#f0a83a;--c3:#4cc38a;--c4:#b08cf0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:24px}
.rec{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--ok);border-radius:10px;padding:14px 18px;margin-top:18px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.red{color:var(--bad)}.amber{color:var(--warn)}.green{color:var(--ok)}tr.best td{background:var(--g)}
td.subj{min-width:150px}td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:340px}td.sm{font-size:13px}
.chart{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.chart svg{display:block;width:100%;height:auto}
.chart text{fill:var(--muted);font-size:11px}.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;margin-top:6px}
.legend i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}
.brk{overflow-wrap:anywhere;word-break:break-word}footer{margin-top:40px;font-size:13px}
"""
COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)"]


def _pill(x: str) -> str:
    return f"<span class='pill {x.lower()}'>{e(x)}</span>"


def _table(head: list[str], rows: list[str]) -> str:
    return ("<div class='wrap'><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows) + "</table></div>")


def _cum_chart(d: Data, rv: dict) -> str:
    c: Case = rv["case"]
    series = []
    for o in d.options:
        if o.baseline:
            continue
        cum, pts = 0.0, []
        for v in c.flows(o.id)["net"]:
            cum += v
            pts.append(cum)
        series.append((o, pts))
    lo = min(min(p) for _, p in series)
    hi = max(max(p) for _, p in series)
    lo, hi = min(lo, 0), max(hi, 0)
    W, H, L, B = 760, 260, 70, 30
    x = lambda y: L + y * (W - L - 20) / c.H
    yv = lambda v: 10 + (hi - v) * (H - B - 10) / (hi - lo or 1)
    g = [f"<line x1='{L}' x2='{W - 20}' y1='{yv(0):.1f}' y2='{yv(0):.1f}' stroke='currentColor' stroke-opacity='.35'/>"]
    for t in sorted({lo, 0.0, hi}):
        g.append(f"<text x='{L - 8}' y='{yv(t) + 4:.1f}' text-anchor='end'>{e(_money(t, ''))}</text>")
    for y in range(c.H + 1):
        g.append(f"<text x='{x(y):.1f}' y='{H - 8}' text-anchor='middle'>Y{y}</text>")
    for i, (o, pts) in enumerate(series):
        col = COLORS[i % 4]
        w = 3 if o.id == rv["recommended"] else 1.6
        g.append(f"<polyline fill='none' stroke='{col}' stroke-width='{w}' points='"
                 + " ".join(f"{x(y):.1f},{yv(v):.1f}" for y, v in enumerate(pts)) + "'/>")
    legend = "".join(f"<span><i style='background:{COLORS[i % 4]}'></i>{e(o.label)}</span>" for i, (o, _) in enumerate(series))
    return (f"<div class='chart'><svg viewBox='0 0 {W} {H}' role='img' aria-label='Cumulative net cash flow by option'>{''.join(g)}</svg>"
            f"<div class='legend'>{legend}</div></div>")


def _tornado(rv: dict, cur: str) -> str:
    rows = sorted(rv["sensitivity"], key=lambda r: -abs(r[2]))
    if not rows:
        return ""
    m = max(abs(r[2]) for r in rows) or 1
    W, rowh, L, R = 760, 28, 200, 100          # labels on the left, NPV values in a column on the right
    half = (W - L - R - 20) / 2
    mid = L + half
    g = [f"<line x1='{mid}' x2='{mid}' y1='0' y2='{rowh * len(rows)}' stroke='currentColor' stroke-opacity='.35'/>"]
    for i, (k, v, dd) in enumerate(rows):
        w = abs(dd) / m * half
        x0 = mid - w if dd < 0 else mid
        col = "var(--bad)" if dd < 0 else "var(--ok)"
        g.append(f"<text x='{L - 10}' y='{i * rowh + 18}' text-anchor='end'>{e(k)}</text>"
                 f"<rect x='{x0:.1f}' y='{i * rowh + 6}' width='{max(w, 1):.1f}' height='16' fill='{col}' rx='3'/>"
                 f"<text x='{W - 4}' y='{i * rowh + 18}' text-anchor='end'>{e(_money(v, cur))}</text>")
    return f"<div class='chart'><svg viewBox='0 0 {W} {rowh * len(rows) + 4}' role='img' aria-label='Sensitivity of the NPV'>{''.join(g)}</svg></div>"


def render_html(d: Data, rv: dict, title: str) -> str:
    s, cur = d.settings, d.settings.currency
    sm = summary(d, rv)
    c: Case = rv["case"]
    rec = d.option(rv["recommended"]) if rv["recommended"] else None
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>{e(s.organisation)} · {sm['options']} options against “{e(d.baseline.name)}” · "
         f"{s.horizon} years at {s.discount_rate * 100:g} % · prepared {_day(s.review_date)}</p>",
         f"<span class='overall {sm['status'].lower()}'>Case quality: {e(sm['status'])} · {sm['red']} red and {sm['amber']} amber findings</span>"]
    if rec:
        h.append(f"<div class='rec'><b>Recommendation: {e(rec.label)}</b><br><span class='muted'>{e(rv['why'])}</span></div>")
    else:
        h.append(f"<div class='rec'><b>No recommendation</b><br><span class='muted'>{e(rv['why'])}</span></div>")
    h.append("<div class='tiles'>")
    tiles = [("NPV", _money(sm["npv"], cur) if rec else "–", f"{_money(sm['pess_npv'], cur)} pessimistic" if rec else ""),
             ("Payback", _pb(sm["payback"]) if rec else "–", f"limit {s.max_payback_years:g} years"),
             ("IRR", _irr(sm["irr"]), f"discount rate {s.discount_rate * 100:g} %"),
             ("ROI", _pct(sm["roi"]), f"on {_money(sm['one_off'], cur)} one-off" if rec else ""),
             ("Risk-adjusted NPV", _money(sm["risk_npv"], cur) if rec else "–", "after expected risk cost"),
             ("Removed by checks", _money(sm["removed"], cur), "benefits not counted")]
    h += [f"<div class='tile'><span class='muted'>{e(a)}</span><b>{e(b)}</b><span class='muted'>{e(x)}</span></div>" for a, b, x in tiles]
    h.append("</div><h2>Decisions needed</h2>")
    h.append(_table(["#", "Decision", "Options", "Proposed", "Owner", "By"],
                    [f"<tr><td class='nw'>{e(x.id)}</td><td class='subj'><b>{e(x.decision)}</b><br><span class='sm muted'>{e(x.why)}</span></td>"
                     f"<td class='sm'>{e(x.options)}</td><td class='fix'>{e(x.proposed)}</td><td class='sm'>{e(x.owner)}</td>"
                     f"<td class='nw'>{e(_day(x.needed_by))}</td></tr>" for x in rv["decisions"]]))
    h.append("<h2>Options</h2><p class='muted'>As submitted, and after the checks (benefits counted twice, before go-live or with no "
             "owner removed; missing contingency added).</p>")
    rows = []
    for x in option_rows(d, rv):
        o = x["o"]
        rows.append(f"<tr class='{'best' if o.id == rv['recommended'] else ''}'><td class='subj'><b>{e(o.label)}</b><br><span class='sm muted'>"
                    f"{e(o.description)}</span></td><td class='num'>{e(_money(x['raw']['npv'], cur))}</td><td class='num'><b>{e(_money(x['m']['npv'], cur))}</b></td>"
                    f"<td class='num'>{e(_money(x['p']['npv'], cur))}</td><td class='num'>{e(_pb(x['m']['payback']))}</td>"
                    f"<td class='num'>{e(_irr(x['m']['irr']))}</td><td class='num'>{e(_money(x['m']['one_off'], cur))}</td>"
                    f"<td class='num'>{_sc(x['score'])}</td>"
                    f"<td class='sm {'green' if x['ready'] else 'red'}'>{'ready' if x['ready'] else str(x['red']) + ' red'}</td></tr>")
    h.append(_table(["Option", "NPV submitted", "NPV checked", "Pessimistic", "Payback", "IRR", "One-off", "Score", "Ready"], rows))
    h.append("<h2>Cumulative net cash flow</h2><p class='muted'>Against the cost of doing nothing, after the checks. Where a line crosses "
             "zero, the option has paid for itself.</p>")
    h.append(_cum_chart(d, rv))
    if rec:
        h.append(f"<h2>Sensitivity: {e(rec.label)}</h2><p class='muted'>NPV under each scenario; bars show the change from the base case "
                 f"({e(_money(c.metrics(rec.id)['npv'], cur))}).</p>")
        h.append(_tornado(rv, cur))
        h.append("<h2>Benefits register</h2>")
        h.append(_table(["Benefit", "Kind", "Counted", "KPI: today → target", "Owner", "Reviews"],
                        [f"<tr><td class='subj'>{e(r[1])}</td><td class='sm'>{e(r[3])}</td><td class='num'>{e(_money(float(r[6] or 0), cur))}</td>"
                         f"<td class='sm'>{e(r[8])}: {e(r[9])} → {e(r[10])}</td><td class='sm'>{e(r[11] or 'none')}</td>"
                         f"<td class='nw sm'>{e(r[14])}<br>{e(r[15])}</td></tr>" for r in benefit_rows(d, rv) if r[0] == rec.id]))
    h.append("<h2>Assumptions</h2>")
    h.append(_table(["Id", "Assumption", "Source", "Owner", "Validated"],
                    [f"<tr><td class='nw'>{e(a.id)}</td><td class='sm'>{e(a.text)}</td><td class='sm'>{e(a.source)}</td><td class='sm'>{e(a.owner)}</td>"
                     f"<td class='{'green' if a.validated else 'amber'}'>{'yes' if a.validated else 'no'}</td></tr>" for a in d.assumptions.values()]))
    if d.scores:
        crit = list(dict.fromkeys(x.criterion for x in d.scores))
        opts = [o.id for o in d.options]
        cell = {(x.criterion, x.option): x.score for x in d.scores}
        wt = {x.criterion: x.weight for x in d.scores}
        tot = c.scores()
        h.append("<h2>Non-financial criteria</h2><p class='muted'>Scores 1–5, weighted to 100.</p>")
        h.append(_table(["Criterion", "Weight"] + opts,
                        [f"<tr><td>{e(k)}</td><td class='num'>{wt[k]:g}</td>" + "".join(f"<td class='num'>{cell.get((k, o), 0):g}</td>" for o in opts) + "</tr>"
                         for k in crit] + ["<tr><td><b>Weighted</b></td><td></td>" + "".join(f"<td class='num'><b>{tot.get(o, 0):.0f}</b></td>" for o in opts) + "</tr>"]))
    h.append("<h2>Quality checks</h2>")
    h.append(_table(["Severity", "Option", "Finding", "Action", "Owner"],
                    [f"<tr><td>{_pill(f.severity)}</td><td class='nw'>{e(f.option)}</td><td class='sm brk'><b>{e(f.title)}</b><br>{e(f.detail)}</td>"
                     f"<td class='fix'>{e(f.action)}</td><td class='sm'>{e(f.owner)}</td></tr>" for f in rv["findings"]]
                    or ["<tr><td colspan='5'>No findings.</td></tr>"]))
    h.append("<footer class='muted'>Generated by bizcase. Fictional demo data unless you ran it on your own files. The paper for the "
             "committee is business-case.md.</footer></main></body></html>")
    return "".join(h)
