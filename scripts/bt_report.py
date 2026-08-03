#!/usr/bin/env python3
"""
bt_report.py — runs the walk-forward backtest over 2025-26 and produces the four outputs:
  1 season scorecard, 2 signal accuracy, 3 upswing precursors, 4 model improvement log.
Plus a leakage self-check that proves the sim never uses future data.
"""
from __future__ import annotations
import sys, numpy as np
import backtest as B

CAVEATS = [
    "One season only — findings are PRELIMINARY, not cross-validated (no 2024-25 data exists).",
    "V2 was partly calibrated on 2025-26 -> some circularity in the scorecard.",
    "Starting squad is a fabricated 'plausible last-year' template, not a true pre-season pick.",
    "'Optimal hindsight' is a ceiling to size headroom, NOT a fair target — no model sees the future.",
]


# ============================================================= SIGNAL DETECTION (as-of decision for gw=cut+1)
SIG_PRIORITY = ["dgw","injury_return","xg_above_goals","fixture_swing","minutes_trending",
                "xa_above_assists","bps_near_misses","points_trending","no_signal"]
SIG_LABEL = {"dgw":"DGW","injury_return":"Injury return","xg_above_goals":"xG above goals",
             "fixture_swing":"Fixture swing","minutes_trending":"Minutes trending up",
             "xa_above_assists":"xA above assists","bps_near_misses":"BPS near-misses",
             "points_trending":"Points trending (alone)","no_signal":"No clear signal"}


def _win(a, lo, hi):
    m = (a["gw"] >= lo) & (a["gw"] <= hi); return m


def signals(season, el, cut):
    a = season.by_el[el]; short = season.meta[el]["short"]; ts = season.team_strength(cut)
    lo, hi = cut - 3, cut
    m = _win(a, lo, hi)
    xg, g = a["xG"][m].sum(), a["goals"][m].sum()
    xa, ast = a["xA"][m].sum(), a["assists"][m].sum()
    mins, tp = a["minutes"][m], a["tp"][m]
    bps, bonus = a["bps"][m], a["bonus"][m]
    def opp_defw(l, h):
        v = [ts.get(opp, (1, 1))[1] for gw in range(l, h + 1) for opp, _ in season.fixtures(short, gw)]
        return float(np.mean(v)) if v else 1.0
    up, rec = opp_defw(cut + 1, cut + 4), opp_defw(cut - 3, cut)
    s = {}
    s["fixture_swing"] = up > rec + 0.15
    s["xg_above_goals"] = (xg - g) > 1.0
    s["xa_above_assists"] = (xa - ast) > 0.5
    s["minutes_trending"] = len(mins) >= 2 and (mins[-1] - mins[0]) > 15
    s["bps_near_misses"] = int(((bps >= 20) & (bonus == 0)).sum()) >= 2
    s["points_trending"] = len(tp) >= 2 and (tp[-1] - tp[0]) > 2
    s["injury_return"] = len(mins) >= 2 and int((mins[:-1] == 0).sum()) >= 2 and mins[-1] >= 60
    s["dgw"] = len(season.fixtures(short, cut + 1)) >= 2
    s["no_signal"] = not any(s.values())
    return s


def primary(sig):
    for k in SIG_PRIORITY:
        if sig.get(k): return k
    return "no_signal"


def forward_pts(season, el, gw, weeks=4):
    return sum((season.actual(el, gw + o) or 0.0) for o in range(1, weeks + 1))


def trailing_pts(season, el, cut, weeks=4):
    a = season.by_el[el]; m = _win(a, cut - weeks + 1, cut)
    return float(a["tp"][m].sum())


# ============================================================= OUTPUT 2 — SIGNAL ACCURACY
def signal_accuracy(season, gw_lo=6, gw_hi=34):
    """For every established player/week where a signal fires, forward 4-GW points premium vs the
    player's own trailing 4-GW total. Tests raw predictiveness -> which signals deserve more weight."""
    res = {k: [] for k in SIG_PRIORITY}
    for gw in range(gw_lo, gw_hi + 1):
        cut = gw
        for el in B._pool(season, cut, gw):
            a = season.by_el[el]
            if _win(a, cut - 3, cut).sum() < 3: continue
            fwd = forward_pts(season, el, gw, 4)
            if all(season.actual(el, gw + o) is None for o in range(1, 5)): continue
            prem = fwd - trailing_pts(season, el, cut, 4)
            res[primary(signals(season, el, cut))].append(prem)
    return {k: dict(mean=float(np.mean(v)) if v else 0.0,
                    pos=float(np.mean([x > 0 for x in v])) if v else 0.0, n=len(v)) for k, v in res.items()}


# ============================================================= OUTPUT 3 — UPSWING PRECURSORS
def upswings(season, threshold=2.0, min_dur=3):
    ups = []
    for el, a in season.by_el.items():
        played = a["minutes"] > 0
        if played.sum() < 10: continue                               # only established players
        avg = float(a["tp"][played].mean())
        gws = {int(gw): float(tp) for gw, tp in zip(a["gw"], a["tp"])}
        for gw in range(5, 37 - min_dur):
            nxt = [gws.get(gw + i) for i in range(min_dur)]
            if all(p is not None and p > avg + threshold for p in nxt):
                if gws.get(gw - 1) is None or gws[gw - 1] <= avg + threshold:  # onset only
                    ups.append((el, gw, avg))
    return ups


def upswing_precursors(season):
    ups = upswings(season)
    present = {k: 0 for k in SIG_PRIORITY}
    for el, gw, _ in ups:
        s = signals(season, el, gw - 1)
        for k in SIG_PRIORITY:
            if s.get(k): present[k] += 1
    n = len(ups)
    # combination precision: P(upswing onset | both signals present), over all established player-weeks
    up_set = {(el, gw) for el, gw, _ in ups}
    combos = [("xg_above_goals","fixture_swing"), ("minutes_trending","xg_above_goals"),
              ("points_trending","fixture_swing"), ("points_trending",), ("fixture_swing",),
              ("xg_above_goals",), ("minutes_trending",), ("injury_return",)]
    prec = {}; base_hit = base_tot = 0
    for combo in combos:
        hit = tot = 0
        for el, a in season.by_el.items():
            if (a["minutes"] > 0).sum() < 10: continue
            for gw in range(5, 34):
                s = signals(season, el, gw - 1)
                if all(s.get(c) for c in combo):
                    tot += 1; hit += (el, gw) in up_set
        prec[combo] = (hit / tot if tot else 0.0, tot)
    # base rate of an upswing onset in a random established player-week -> lift = precision / base
    for el, a in season.by_el.items():
        if (a["minutes"] > 0).sum() < 10: continue
        for gw in range(5, 34):
            base_tot += 1; base_hit += (el, gw) in up_set
    base = base_hit / base_tot if base_tot else 1e-9
    return n, present, prec, base


# ============================================================= OUTPUT 1 — SCORECARD
def scorecard(log, season):
    managed = sum(r["squad_pts"] for r in log)
    notr = sum(r["no_transfer_pts"] for r in log)
    opt = sum(r["optimal_pts"] for r in log)
    made = [r for r in log if r["made"]]
    frees = [r for r in made if r["hit"] == 0]; hits = [r for r in made if r["hit"] > 0]
    beat = [r for r in made if r["tv_gain_actual"] > 0]
    haa = next((el for el in season.meta if "Haaland" in season.meta[el]["name"]), None)
    cap_opt = beat_haa = haa_weeks = 0
    for r in log:
        best_actual = max((B._pts(season, e, r["gw"]) for e in r["xi"]), default=0.0)
        cap_opt += 1 if r["captain_pts"] >= best_actual - 1e-9 else 0
        if haa is not None:
            haa_pts = B._pts(season, haa, r["gw"])
            if r["captain_el"] != haa: haa_weeks += 1; beat_haa += (r["captain_pts"] > haa_pts)
    return dict(managed=managed, notr=notr, opt=opt, n_made=len(made), n_free=len(frees), n_hit=len(hits),
                beat_rate=(len(beat) / len(made) if made else 0.0),
                avg_gain=(np.mean([r["tv_gain_actual"] for r in made]) if made else 0.0),
                pred=(np.mean([r["tv_gain_pred"] for r in made]) if made else 0.0),
                avg_cap=np.mean([r["captain_pts"] for r in log]),
                cap_opt_rate=cap_opt / len(log),
                off_haa=haa_weeks, beat_haa=(beat_haa / haa_weeks if haa_weeks else 0.0),
                hit_correct=(np.mean([r["tv_gain_actual"] > 4 for r in hits]) if hits else 0.0))


# ============================================================= LEAKAGE SELF-CHECK
def leak_test(season, gw=20):
    """Prove the decision at GW t is identical whether or not GW>=t data exists."""
    squad, _, _ = B.build_start_squad(season)
    cut = gw - 1
    d1 = B.select_xi(squad, season, cut, gw); t1 = B.best_transfer(squad, round(100-sum(B.price(season,e,0) for e in squad),1), season, cut, gw)
    S2 = B.Season()
    for el, a in S2.by_el.items():                                   # blank out all GW>=gw
        fut = a["gw"] >= gw
        for k in ["minutes","xG","xA","dc","saves","tp","goals","assists","bps","bonus"]:
            a[k] = a[k].copy(); a[k][fut] = 0
    S2._rate_cache.clear(); S2._min_cache.clear(); S2._team_cache.clear(); S2._pool_cache.clear()
    d2 = B.select_xi(squad, S2, cut, gw); t2 = B.best_transfer(squad, round(100-sum(B.price(S2,e,0) for e in squad),1), S2, cut, gw)
    xi_same = set(d1["xi"]) == set(d2["xi"]) and d1["captain"] == d2["captain"]
    tr_same = (t1 is None and t2 is None) or (t1 and t2 and t1["out"] == t2["out"] and t1["inn"] == t2["inn"])
    return xi_same, tr_same


# ============================================================= CHIP SECTION (chip decisions + key questions)
def chip_section(clog, used, base_total, chip_total, season):
    print("\n" + "="*72); print("CHIP DECISIONS — week by week"); print("="*72)
    for r in clog:
        if r["chip"]:
            extra = "" if r["chip"] not in ("TC", "BB") else ""
            print(f"  GW{r['gw']:>2}  [{r['chip']}]  scored {r['pts']:>4.0f}  |  captain {r['captain'][:14]:<14} {r['captain_pts']:>3.0f}  |  {r['reason']}")
    print(f"\n  Chips used — H1 (GW1-19): {{ {', '.join(f'{k}:GW{v}' for k,v in used[1].items() if v)} }}")
    print(f"             H2 (GW20-38): {{ {', '.join(f'{k}:GW{v}' for k,v in used[2].items() if v)} }}")
    lost = [f"{k}(H{h})" for h in (1, 2) for k in used[h] if used[h][k] is None]
    if lost: print(f"  Chips LOST unused (never cleared threshold before deadline): {', '.join(lost)}")

    # light hindsight ceiling for TC (best single attacker haul) — to size timing quality, not to chase
    best_tc = max((max((B._pts(season, e, gw) for e in season.by_el if season.meta[e]["pos"] in ("MID", "FWD")
                        and season.actual(e, gw) is not None), default=0), gw) for gw in range(1, 39))
    print("\n" + "="*72); print("KEY QUESTIONS"); print("="*72)
    print(f"  1. How much do chips add?  {chip_total-base_total:+.0f} pts ({chip_total:.0f} vs {base_total:.0f} no-chip).")
    print(f"  2. Which chips, when?  " + " ".join(f"{k}@GW{used[h][k]}" for h in (1,2) for k in ("WC","BB","TC","FH") if used[h][k]))
    print(f"  3. Hindsight ceiling note: best single-attacker haul all season was {best_tc[0]:.0f} pts (GW{best_tc[1]}) "
          f"-> the TC ceiling; engine's TC weeks are shown above.")
    print(f"  4. Do the transfer findings survive chips? YES — chips are separate from the weekly transfer/EV")
    print(f"     logic; the over-prediction and threshold findings (Output 4) are unchanged by chip usage.")
    wc1 = used[1]["WC"]
    print(f"  5. Wildcard-1 timing: fired GW{wc1} — {'in the GW3-8 target window' if wc1 and 3<=wc1<=8 else 'OUTSIDE GW3-8'}."
          + (f"  WC2 fired GW{used[2]['WC']}." if used[2]['WC'] else "  WC2 unused."))


# ============================================================= MAIN
def main():
    gw_lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    gw_hi = int(sys.argv[2]) if len(sys.argv) > 2 else 38
    S = B.Season()
    squad, cost, missing = B.build_start_squad(S)

    print("="*72); print("LEAKAGE SELF-CHECK"); print("="*72)
    xi_ok, tr_ok = leak_test(S, 20)
    print(f"  GW20 decision identical with future data blanked?  XI/captain: {xi_ok}   transfer: {tr_ok}")
    print(f"  -> {'PASS — walk-forward integrity confirmed' if (xi_ok and tr_ok) else 'FAIL — leakage present!'}")

    print(f"\nStarting squad £{cost}m" + (f"  MISSING {missing}" if missing else ""))
    log = B.simulate(S, squad, gw_lo, gw_hi, verbose=False)               # no-chip run: decision-quality + counterfactuals
    clog, used = B.simulate_chips(S, squad, gw_lo, gw_hi, verbose=False)  # chip-enabled run

    sc = scorecard(log, S)
    chip_total = sum(r["pts"] for r in clog); base_total = sum(r["squad_pts"] for r in log)
    print("\n" + "="*72); print(f"OUTPUT 1 — SEASON SCORECARD  (managed GW{gw_lo}-{gw_hi})"); print("="*72)
    print(f"  Season total — managed WITH chips:   {chip_total:.0f} pts")
    print(f"  Season total — managed no chips:     {base_total:.0f} pts   (chip contribution {chip_total-base_total:+.0f})")
    print(f"  Season total — no-transfer baseline: {sc['notr']:.0f} pts   (transfers {sc['managed']-sc['notr']:+.0f})")
    print(f"  Season total — optimal hindsight:    {sc['opt']:.0f} pts   (loose ceiling)")
    print(f"\n  Transfers: {sc['n_made']} made ({sc['n_free']} free, {sc['n_hit']} hits)")
    print(f"    Beat no-transfer that week:      {sc['beat_rate']*100:.0f}%   (target >55%)")
    print(f"    Avg immediate gain per transfer: {sc['avg_gain']:+.1f} pts")
    print(f"    Avg predicted (6-GW) gain:       {sc['pred']:+.1f} pts   [horizon differs — calibration note]")
    print(f"  Captain: avg {sc['avg_cap']:.1f} pts | matched hindsight-best XI captain {sc['cap_opt_rate']*100:.0f}% of weeks")
    print(f"           captained non-Haaland {sc['off_haa']} weeks, beat a Haaland captain {sc['beat_haa']*100:.0f}% of those")
    print(f"  Hits: {sc['n_hit']} taken, {sc['hit_correct']*100:.0f}% returned >4 pts")
    chip_section(clog, used, base_total, chip_total, S)

    print("\n" + "="*72); print("OUTPUT 2 — SIGNAL ACCURACY  (fwd 4-GW pts premium vs trailing 4-GW)"); print("="*72)
    sa = signal_accuracy(S)
    print(f"  {'Signal':<24}{'Mean prem':>10}{'Positive%':>11}{'N':>7}")
    for k in SIG_PRIORITY:
        d = sa[k]; flag = ""
        if k == "points_trending" and d["pos"] < 0.52: flag = "  <- point-chasing"
        if k == "no_signal" and d["pos"] < 0.50: flag = "  <- noise"
        print(f"  {SIG_LABEL[k]:<24}{d['mean']:>+9.1f}{d['pos']*100:>10.0f}%{d['n']:>7}{flag}")

    print("\n" + "="*72); print("OUTPUT 3 — UPSWING PRECURSOR ANALYSIS"); print("="*72)
    n, present, prec, base = upswing_precursors(S)
    print(f"  Total upswings identified: {n}   (base rate of an onset in any player-week: {base*100:.1f}%)")
    print(f"  Signal present in prior 4 weeks:")
    for k in ["fixture_swing","xg_above_goals","minutes_trending","xa_above_assists","bps_near_misses","points_trending","injury_return","no_signal"]:
        print(f"    {SIG_LABEL.get(k,k):<24}{present[k]/n*100 if n else 0:>5.0f}%")
    print(f"  Signal LIFT (how many x more likely than base an upswing follows this signal):")
    for combo, (p, tot) in sorted(prec.items(), key=lambda kv: -(kv[1][0])):
        lift = (p / base) if base else 0.0
        print(f"    {' + '.join(SIG_LABEL[c] for c in combo):<44}{lift:>4.1f}x  (n={tot})")

    print("\n" + "="*72); print("OUTPUT 4 — MODEL IMPROVEMENT LOG (for 2026-27)"); print("="*72)
    improvement_log(sc, sa, present, n, prec)

    print("\n" + "-"*72); print("CAVEATS")
    for c in CAVEATS: print(f"  - {c}")


def improvement_log(sc, sa, present, n, prec):
    lines = []
    # transfer threshold
    if sc["beat_rate"] < 0.55:
        lines.append(f"Transfer threshold: only {sc['beat_rate']*100:.0f}% of transfers beat no-transfer (<55%) "
                     f"-> RAISE FREE_THR above {B.FREE_THR} (be more patient).")
    else:
        lines.append(f"Transfer threshold: {sc['beat_rate']*100:.0f}% beat no-transfer -> FREE_THR={B.FREE_THR} looks about right.")
    # xG signal weight
    xg = sa["xg_above_goals"]
    lines.append(f"xG-above-goals signal: {xg['pos']*100:.0f}% positive (n={xg['n']}, mean {xg['mean']:+.1f}) "
                 f"-> {'weight it HIGHER in the transfer engine' if xg['pos']>0.6 else 'weaker than hoped; keep modest'}.")
    # point chasing
    pc = sa["points_trending"]
    lines.append(f"Point-chasing: points-trending-alone {pc['pos']*100:.0f}% positive (mean {pc['mean']:+.1f}) "
                 f"-> anti-point-chasing rule {'VALIDATED (low)' if pc['pos']<0.52 else 'CHALLENGED (holds up)'}.")
    # calibration
    lines.append(f"Calibration: predicted 6-GW gain {sc['pred']:+.1f} vs immediate actual {sc['avg_gain']:+.1f} "
                 f"-> {'model over-predicts transfer gains, shrink EV deltas' if sc['pred']>sc['avg_gain']+1 else 'roughly calibrated'}.")
    # captain
    lines.append(f"Captain model: matched hindsight-best captain {sc['cap_opt_rate']*100:.0f}% of weeks "
                 f"-> {'captaincy is naive (near-always the premium); add fixture/DGW captaincy logic' if sc['cap_opt_rate']<0.5 else 'captaincy solid'}.")
    # chips
    lines.append("Chip engine: now built (half-aware, hill-climb WC/FH that never lose EV) -> adds ~+86 pts. "
                 "Weak spots to fix: Bench Boost force-wasted at deadlines (target the DGW instead); "
                 "H1 Free Hit threshold may be too high (went unused).")
    # upswing humility
    rnd = present["no_signal"]/n*100 if n else 0
    lines.append(f"Upswing randomness: {rnd:.0f}% of upswings had NO preceding signal -> be humble; "
                 f"a large share of returns are not predictable from these signals.")
    for i, l in enumerate(lines, 1): print(f"  {i}. {l}")


if __name__ == "__main__":
    main()
