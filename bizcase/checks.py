"""The case: cash flows of each option against the cost of doing nothing, NPV, IRR, payback and ROI, optimistic and pessimistic
ranges from how sure each estimate is, risk-adjusted value, sensitivity, the weighted non-financial score, the quality checks a
finance partner would make (double counting, benefits before go-live, benefits without owner or KPI, unvalidated assumptions that
carry the value, missing cost lines and contingency) and the recommendation, computed on the figures that survive the checks."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .model import CONF, EVID, Data, Option, _norm

RED, AMBER, GREEN = "RED", "AMBER", "GREEN"
GROUPS = {"benefits": "Benefits", "costs": "Costs", "assumptions": "Assumptions", "finance": "Financials", "risks": "Risks",
          "criteria": "Criteria"}
REQUIRED_CATS = {"training": AMBER, "internal-staff": AMBER, "decommission": RED, "migration": RED}


@dataclass
class Finding:
    severity: str
    code: str
    group: str
    option: str
    title: str
    detail: str
    action: str
    owner: str = ""
    due: date | None = None


@dataclass
class Decision:
    id: str
    decision: str
    why: str
    options: str
    proposed: str
    owner: str
    needed_by: date | None


def npv(flows: list[float], rate: float) -> float:
    return sum(v / (1 + rate) ** y for y, v in enumerate(flows))


def irr(flows: list[float]) -> float | None:
    if not (any(v < 0 for v in flows) and any(v > 0 for v in flows)):
        return None
    lo, hi = -0.99, 10.0
    f_lo = npv(flows, lo)
    if f_lo * npv(flows, hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f = npv(flows, mid)
        if abs(f) < 1e-6:
            break
        if (f > 0) == (f_lo > 0):
            lo, f_lo = mid, f
        else:
            hi = mid
    return (lo + hi) / 2


def payback(flows: list[float]) -> float | None:
    """Years from the start (year 0 is the investment) until the cumulative net cash flow turns positive."""
    cum = 0.0
    for y, v in enumerate(flows):
        prev = cum
        cum += v
        if cum >= 0 and y > 0 and v > 0:
            return y - 1 + (-prev / v if prev < 0 else 0)
        if cum >= 0 and y == 0:
            continue
    return None


def _words(s: str) -> set:
    return {w for w in _norm(s).split() if len(w) > 3}


class Case:
    def __init__(self, d: Data):
        self.d = d
        self.s = d.settings
        self.H = int(self.s.horizon)
        self.base = d.baseline
        self.findings: list[Finding] = []
        self.excluded: dict[int, tuple[str, list[int]]] = {}     # benefit index -> (reason, years excluded)
        self.moved_soft: set[int] = set()
        self.shortfall: dict[str, float] = {}

    # -------------------------------------------------- cash flows
    def costs(self, oid: str, scenario: str = "base") -> list[float]:
        out = [0.0] * (self.H + 1)
        for c in self.d.costs:
            if c.option == oid and 0 <= c.year <= self.H:
                f = 1.0
                if scenario == "optimistic":
                    f -= CONF[c.confidence][0]
                elif scenario == "pessimistic":
                    f += CONF[c.confidence][1]
                elif scenario == "costs+":
                    f += self.s.sensitivity_pct / 100
                out[c.year] += c.amount * f
        return out

    def benefits(self, oid: str, scenario: str = "base", clean: bool = True, hard: bool = True) -> list[float]:
        out = [0.0] * (self.H + 1)
        for i, b in enumerate(self.d.benefits):
            if b.option != oid or not (0 <= b.year <= self.H):
                continue
            is_hard = b.hard and not (clean and i in self.moved_soft)
            if is_hard != hard:
                continue
            if clean and i in self.excluded and b.year in self.excluded[i][1]:
                continue
            f = 1.0
            if scenario == "optimistic":
                f += EVID[b.evidence][0]
            elif scenario == "pessimistic":
                f -= EVID[b.evidence][1]
            elif scenario == "benefits-":
                f -= self.s.sensitivity_pct / 100
            out[b.year] += b.amount * f
        if scenario == "delay":
            k = min(self.s.delay_months, 12) / 12
            out = [(1 - k) * out[y] + (k * out[y - 1] if y > 0 else 0) for y in range(self.H + 1)]
        return out

    def flows(self, oid: str, scenario: str = "base", clean: bool = True) -> dict:
        base = self.costs(self.base.id, "base")
        cost = self.costs(oid, scenario if scenario in ("optimistic", "pessimistic", "costs+") else "base")
        if clean and oid in self.shortfall:            # the contingency the estimates need, where the option has less
            cost[0] += self.shortfall[oid]
        ben = self.benefits(oid, scenario if scenario in ("optimistic", "pessimistic", "benefits-", "delay") else "base", clean)
        if scenario == "delay":       # the old platform runs for longer: its costs stay while the new one is not live
            k = min(self.s.delay_months, 12) / 12
            o = self.d.option(oid)
            y = max(o.golive_year, 1) if o else 1
            if y <= self.H:
                cost[y] += k * base[y]
        net = [base[y] - cost[y] + ben[y] for y in range(self.H + 1)]
        return {"base": base, "cost": cost, "benefits": ben, "net": net}

    def metrics(self, oid: str, scenario: str = "base", clean: bool = True, rate: float | None = None) -> dict:
        f = self.flows(oid, scenario, clean)
        r = self.s.discount_rate if rate is None else rate
        one_off = sum(c.amount for c in self.d.costs if c.option == oid and c.one_off)
        exp_risk = sum(x.expected for x in self.d.risks if x.option == oid)
        v = npv(f["net"], r)
        return {"npv": v, "irr": irr(f["net"]), "payback": payback(f["net"]), "tco": sum(f["cost"]),
                "roi": sum(f["net"]) / one_off * 100 if one_off else None, "one_off": one_off,
                "risk": exp_risk, "risk_npv": v - exp_risk / (1 + r) ** 2, "net": f["net"], "flows": f,
                "soft": sum(self.benefits(oid, "base", clean, hard=False))}

    # -------------------------------------------------- checks
    def add(self, sev, code, group, option, title, detail, action, owner_key):
        due = (self.s.review_date or date.today()) + timedelta(days=7 if sev == RED else 21)
        self.findings.append(Finding(sev, code, group, option, title, detail, action, self.s.owners.get(owner_key, owner_key), due))

    def check(self):
        d, s = self.d, self.s
        cur = s.currency
        base_items = {c.item for c in d.costs if c.option == self.base.id}
        for o in d.options:
            if o.baseline:
                continue
            own_items = {_norm(c.item) for c in d.costs if c.option == o.id}
            bs = [(i, b) for i, b in enumerate(d.benefits) if b.option == o.id]
            # double counting: a "saving" that is a baseline cost the option no longer has (already in the cost difference)
            for i, b in bs:
                if b.type != "saving":
                    continue
                hit = next((it for it in base_items if len(_words(it) & _words(b.name)) >= 2 and _norm(it) not in own_items), None)
                if hit:
                    self.excluded[i] = ("double counted", list(range(self.H + 1)))
            dbl = sorted({b.name for i, b in bs if self.excluded.get(i, ("",))[0] == "double counted"})
            if dbl:
                amt = sum(b.amount for i, b in bs if self.excluded.get(i, ("",))[0] == "double counted")
                self.add(RED, "BEN-DOUBLE", "benefits", o.id, "Benefit counted twice",
                         f"{'; '.join(dbl)}: the baseline already pays for it and this option does not, so the saving is in the cost "
                         f"difference. Counting it again adds {_money(amt, cur)} over {self.H} years.",
                         "Remove the benefit line; the saving stays in the comparison with the baseline.", "FINANCE")
            # benefits before go-live
            early = [(i, b) for i, b in bs if b.year < o.golive_year and i not in self.excluded]
            if early:
                for i, b in early:
                    self.excluded.setdefault(i, ("before go-live", []))[1].append(b.year)
                amt = sum(b.amount for _, b in early)
                self.add(RED, "BEN-EARLY", "benefits", o.id, "Benefits before the solution is live",
                         f"Go-live is in month {o.golive} (year {o.golive_year}), but {_money(amt, cur)} of benefits are booked earlier: "
                         + "; ".join(sorted({f'{b.name} (year {b.year})' for _, b in early})) + ".",
                         "Move each benefit to the year after go-live, or bring the plan forward with evidence.", "FINANCE")
            # owner and KPI
            noown = [(i, b) for i, b in bs if b.hard and not b.owner and i not in self.excluded]
            if noown:
                for i, _ in noown:
                    self.moved_soft.add(i)
                names = sorted({b.name for _, b in noown})
                amt = sum(b.amount for _, b in noown)
                self.add(RED, "BEN-NOOWNER", "benefits", o.id, "Hard benefit with no owner",
                         f"{'; '.join(names)} ({_money(amt, cur)}): nobody in the business has signed up to deliver it, so it is "
                         "treated as soft (outside the NPV) until someone does.",
                         "Name the business owner who will take it out of their budget, or keep it as a soft benefit.", "BENEFITS")
            nokpi = sorted({b.name for _, b in bs if not (b.kpi and b.baseline and b.target)})
            if nokpi:
                self.add(AMBER, "BEN-NOKPI", "benefits", o.id, "Benefits that cannot be measured",
                         f"No KPI, baseline or target for: {'; '.join(nokpi)}.",
                         "Add the KPI with today's value and the target, so the benefit can be tracked after go-live.", "BENEFITS")
            prod = sorted({b.name for i, b in bs if b.hard and b.type == "productivity" and i not in self.moved_soft and i not in self.excluded})
            if prod:
                self.add(AMBER, "BEN-PRODUCTIVITY", "benefits", o.id, "Time saved counted as cash",
                         f"{'; '.join(prod)}: hours saved only become cash if a budget goes down (fewer contractors, overtime, hires "
                         "not made).", "Say which budget line goes down, or move it to soft benefits.", "FINANCE")
            # assumptions behind the value
            total = sum(b.amount for _, b in bs if b.hard) or 0
            by_asm = defaultdict(float)
            for _, b in bs:
                if b.hard:
                    for a in b.assumptions:
                        by_asm[a] += b.amount
            for a, amt in sorted(by_asm.items(), key=lambda x: -x[1]):
                asm = d.assumptions.get(a)
                share = amt / total * 100 if total else 0
                if (asm is None or not asm.validated) and share >= s.driver_pct:
                    self.add(RED if share >= 40 else AMBER, "ASM-UNVALIDATED", "assumptions", o.id, "Unvalidated assumption carries the case",
                             f"{a}{(': ' + asm.text) if asm else ' (not in assumptions.csv)'} is behind {share:.0f} % of the hard benefits "
                             f"({_money(amt, cur)}) and is not validated" + (f" (source: {asm.source})" if asm and asm.source else "") + ".",
                             f"Validate it with {asm.owner if asm and asm.owner else 'its owner'} (a written quote or a measurement) "
                             "before the committee.", "FINANCE")
            # costs
            cats = {c.category for c in d.costs if c.option == o.id}
            for cat, sev in REQUIRED_CATS.items():
                if cat not in cats:
                    self.add(sev, "COST-MISSING", "costs", o.id, f"No {cat.replace('-', ' ')} cost",
                             {"training": "Nobody is trained on the new solution in this estimate.",
                              "internal-staff": "The time of our own people on the project is not costed.",
                              "decommission": "Switching off the old platform (data archive, contracts, disposal) is not costed.",
                              "migration": "Moving the data and the customisations is not costed."}[cat],
                             "Add the line with its basis, even if it is an estimate.", "COSTS")
            run_years = {c.year for c in d.costs if c.option == o.id and not c.one_off}
            missing_run = [y for y in range(max(o.golive_year, 1), self.H + 1) if y not in run_years]
            if missing_run:
                self.add(RED, "COST-RUN", "costs", o.id, "Years with no running cost",
                         f"No running cost after go-live in year {', '.join(map(str, missing_run))}.",
                         "Add subscriptions, support and people for every year of the horizon.", "COSTS")
            one_off = [c for c in d.costs if c.option == o.id and c.one_off and c.category != "contingency"]
            base_amt = sum(c.amount for c in one_off)
            need = sum(c.amount * s.contingency_pct.get(c.confidence, 10) / 100 for c in one_off)
            have = sum(c.amount for c in d.costs if c.option == o.id and c.category == "contingency")
            if base_amt and have < need * 0.95:
                self.shortfall[o.id] = need - have
                self.add(AMBER if have else RED, "COST-CONTINGENCY", "costs", o.id, "Contingency below what the estimates need",
                         f"{_money(have, cur)} of contingency against {_money(need, cur)} for one-off costs of {_money(base_amt, cur)} "
                         f"({', '.join(f'{k} {v} %' for k, v in s.contingency_pct.items())} by confidence).",
                         "Add the contingency line, or raise the confidence of the estimates with quotes.", "COSTS")
            # risks
            bad = [x.risk for x in d.risks if x.option == o.id and not (x.mitigation and x.owner)]
            if bad:
                self.add(AMBER, "RISK-NOMITIGATION", "risks", o.id, "Risks without mitigation or owner", "; ".join(bad) + ".",
                         "Add the mitigation and who owns it.", "RISKS")
        # weights
        w = {}
        for sc in d.scores:
            w[sc.criterion] = sc.weight
        if w and abs(sum(w.values()) - 100) > 0.5:
            self.add(AMBER, "CRIT-WEIGHTS", "criteria", "", "Criteria weights do not add up to 100",
                     f"They add up to {sum(w.values()):g}.", "Agree the weights with the committee before scoring.", "DECISION")

    def finance_findings(self, rec: str | None):
        cur = self.s.currency
        for o in self.d.options:
            if o.baseline:
                continue
            m = self.metrics(o.id)
            p = self.metrics(o.id, "pessimistic")
            if m["payback"] is None:
                self.add(RED, "FIN-PAYBACK", "finance", o.id, "Never pays back",
                         f"The cumulative cash flow is still negative after {self.H} years ({_money(sum(m['net']), cur)}).",
                         "Rework the scope or drop the option.", "FINANCE")
            elif m["payback"] > self.s.max_payback_years:
                self.add(AMBER, "FIN-PAYBACK", "finance", o.id, "Payback longer than the limit",
                         f"Pays back in {m['payback']:.1f} years against a limit of {self.s.max_payback_years:g}.",
                         "Phase the investment or bring benefits forward with evidence.", "FINANCE")
            if p["npv"] < self.s.hurdle_npv:
                self.add(AMBER, "FIN-PESSIMISTIC", "finance", o.id, "Loses money in the pessimistic case",
                         f"NPV {_money(m['npv'], cur)} in the base case, {_money(p['npv'], cur)} with costs at their high estimate and "
                         "benefits at their low one.", "Reduce the uncertainty (quotes, measured baselines) before committing.", "FINANCE")

    def scores(self) -> dict:
        out = defaultdict(float)
        for sc in self.d.scores:
            out[sc.option] += sc.weight * sc.score / 5
        return dict(out)

    def ready(self, oid: str) -> bool:
        """An option with a red finding on its benefits or costs is not ready for the committee: its figures cannot be trusted yet."""
        return not any(f.option == oid and f.severity == RED and f.group in ("benefits", "costs") for f in self.findings)

    def recommend(self) -> tuple[str | None, str]:
        rows = []
        for o in self.d.options:
            if o.baseline:
                continue
            m = self.metrics(o.id)
            ok = self.ready(o.id) and m["npv"] >= self.s.hurdle_npv and m["payback"] is not None and m["payback"] <= self.s.max_payback_years
            rows.append((ok, m["risk_npv"], self.scores().get(o.id, 0), o.id))
        good = sorted([r for r in rows if r[0]], key=lambda r: (-r[1], -r[2]))
        if good:
            o = self.d.option(good[0][3])
            return o.id, (f"{o.label}: the highest risk-adjusted NPV among the options that are ready for the committee (no red "
                          f"finding on their costs or benefits), have a positive NPV and pay back within {self.s.max_payback_years:g} "
                          "years, on the figures after the checks.")
        return None, ("No option is ready, has a positive NPV and pays back in time: rework the options before deciding.")

    def sensitivity(self, oid: str) -> list[tuple[str, float, float]]:
        s = self.s
        base = self.metrics(oid)["npv"]
        rows = [(f"Costs +{s.sensitivity_pct:g} %", self.metrics(oid, "costs+")["npv"]),
                (f"Hard benefits -{s.sensitivity_pct:g} %", self.metrics(oid, "benefits-")["npv"]),
                (f"Go-live {s.delay_months} months later", self.metrics(oid, "delay")["npv"]),
                (f"Discount rate {(s.discount_rate + .02) * 100:g} %", self.metrics(oid, rate=s.discount_rate + .02)["npv"]),
                ("Pessimistic estimates", self.metrics(oid, "pessimistic")["npv"]),
                ("Optimistic estimates", self.metrics(oid, "optimistic")["npv"])]
        return [(k, v, v - base) for k, v in rows]

    def decisions(self, rec: str | None) -> list[Decision]:
        s, cur = self.s, self.s.currency
        due = s.review_date + timedelta(days=14) if s.review_date else None
        out = []
        names = " / ".join(o.label for o in self.d.options)
        if rec:
            o, m = self.d.option(rec), self.metrics(rec)
            out.append(Decision("D1", f"Approve {o.label}", s.decision or "Which option to fund.", names,
                                f"{o.label}: NPV {_money(m['npv'], cur)}, payback {m['payback']:.1f} years, one-off "
                                f"{_money(m['one_off'], cur)}.", s.owners.get("DECISION", ""), due))
            asm = [f for f in self.findings if f.option == rec and f.code == "ASM-UNVALIDATED"]
            if asm:
                out.append(Decision("D2", "Approve on condition of the open assumptions", "; ".join(f.detail for f in asm),
                                    "Approve now / approve with a condition and a date / wait", "Approve with the condition, confirmed "
                                    "before the contract is signed.", s.owners.get("DECISION", ""), due))
            pess = [f for f in self.findings if f.option == rec and f.code == "FIN-PESSIMISTIC"]
            if pess:
                out.append(Decision(f"D{len(out) + 1}", "How to hold the downside", pess[0].detail,
                                    "Fund it all now / fund phase 1 and decide phase 2 at a gate / wait for firmer quotes",
                                    "Fund phase 1 now and phase 2 at a gate, with the benefits of phase 1 measured.",
                                    s.owners.get("DECISION", ""), due))
            cont = [f for f in self.findings if f.option == rec and f.code == "COST-CONTINGENCY"]
            if cont:
                out.append(Decision(f"D{len(out) + 1}", "Contingency to hold", cont[0].detail,
                                    "Inside the budget / held centrally / none", "Inside the budget, released by the steering committee.",
                                    s.owners.get("DECISION", ""), due))
        else:
            out.append(Decision("D1", "Send the options back", "No option passes the financial tests.", "Rework / do nothing",
                                "Rework the options with quotes and measured baselines.", s.owners.get("DECISION", ""), due))
        out.append(Decision(f"D{len(out) + 1}", "Benefits owner and review dates",
                            "The benefits only exist if someone tracks them after go-live.",
                            "Business sponsor / IT / finance", "The business sponsor, with reviews 6 and 12 months after go-live.",
                            s.owners.get("DECISION", ""), due))
        return out

    def run(self) -> dict:
        self.check()
        rec, why = self.recommend()
        self.finance_findings(rec)
        order = {RED: 0, AMBER: 1}
        self.findings.sort(key=lambda f: (order[f.severity], f.option, list(GROUPS).index(f.group)))
        return {"case": self, "findings": self.findings, "recommended": rec, "why": why, "decisions": self.decisions(rec),
                "sensitivity": self.sensitivity(rec) if rec else []}


def _money(x: float, cur: str = "EUR") -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e6:
        return f"{sign}{x / 1e6:.2f} M {cur}"
    if x >= 1e3:
        return f"{sign}{x / 1e3:.0f}k {cur}"
    return f"{sign}{x:.0f} {cur}"


def review(d: Data) -> dict:
    return Case(d).run()


def summary(d: Data, rv: dict) -> dict:
    c: Case = rv["case"]
    fs = rv["findings"]
    red = sum(f.severity == RED for f in fs)
    amber = sum(f.severity == AMBER for f in fs)
    rec = rv["recommended"]
    m = c.metrics(rec) if rec else None
    return {"status": RED if red else AMBER if amber else GREEN, "red": red, "amber": amber, "recommended": rec,
            "npv": m["npv"] if m else None, "payback": m["payback"] if m else None, "roi": m["roi"] if m else None,
            "irr": m["irr"] if m else None, "risk_npv": m["risk_npv"] if m else None,
            "pess_npv": c.metrics(rec, "pessimistic")["npv"] if rec else None, "one_off": m["one_off"] if m else None,
            "options": len(d.options) - 1,
            "removed": sum(b.amount for i, b in enumerate(d.benefits) if i in c.excluded and b.year in c.excluded[i][1])
            + sum(b.amount for i, b in enumerate(d.benefits) if i in c.moved_soft)}
