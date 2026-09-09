#!/usr/bin/env python3
"""model_tests.py — six standing tests for defects that a human had to catch.

WHY THIS FILE EXISTS

Every one of the defects below was found the same way: Jon looked at a recommendation, said
"that's wrong", and we measured until we found out why. That is a fine way to find a bug once
and a terrible way to run a model, because it means the tool is a hypothesis generator that
needs a human check rather than something that can act.

These six turn each defect into a measurement that fails loudly. They are deliberately
calibration tests, not unit tests: they run against the live API and the locked forecast and
ask "is the model still wrong in this specific way".

    python scripts/model_tests.py            # run all six, exit 1 if any fail
    python scripts/model_tests.py --quiet    # one line per test

THE SIX, AND WHAT EACH COST TO FIND

1. POINT-CHASING, ATTACKERS ONLY (2026-09-07). For midfielders and forwards the projection gives
   points already banked exactly as much weight as underlying output — standardised beta +0.412
   on each — and pays a +0.67 luck premium: attackers who had overperformed their xGI were rated
   4.51 against 3.83 for attackers with the same underlying numbers who had been unlucky.
   Finishing luck does not persist, so this buys players at the top of their variance. Jon:
   "classic point chasing that weaker FPL human managers do, which is a losing strategy."
   CORRECTION, recorded because the first version of this test was wrong: run across ALL
   positions it also failed, at +0.341 on points against +0.039 on xGI. That was a mis-specified
   test, not a defect. A defender's points ARE clean-sheet points, so points/90 legitimately
   proxies his club's defensive strength and xGI is close to irrelevant to him. Defender quality
   is test 2 instead.

2. CLEAN SHEETS OVER-PREDICTED (2026-09-07). Jon's structural point: for a keeper or defender the
   fundamental unit is projected clean sheets times P(60 minutes), not historic points. The model
   is already built that way — compute_ev_v2 is cs_prob*cs_pts + appearance + xG/xA*fixture +
   player-specific DefCon, all gated on p60 — so the architecture was never the problem. The
   NUMBER is: retro-predicting the 60 team-matches already played gives mean predicted 0.373
   against an actual 0.267, a bias of +0.106, with correlation only +0.281. Optimistic in every
   band above 0.2. Chelsea were given 0.529 having conceded seven in three with no clean sheet.
   This is why defenders at leaky clubs rate too highly and why Newcastle's defenders looked
   better than Arsenal's.

2. FIXTURE TERM TOO WEAK (2026-09-07). Mean projection ran 4.55 at the easiest fixture difficulty
   and 3.26 at the hardest — a 0.77-point spread, where clean-sheet probability alone should move
   a defender more than that. Found when Tavernier's projection barely moved for Liverpool at
   home versus Brentford at home.

3. NO RECENCY IN MINUTES (2026-09-07). p60 is a season average with no recency term. Tzolis had
   started all three games and played 90 in the most recent, and carried p60 0.42 — below even
   the naive 2-of-3 rate. Konsa had just taken Mosquera's place (0, 11, 90 minutes) and carried
   0.57. This is what made Newcastle's fourth-choice defender look better than Arsenal's new
   starter.

4. PREMIUM COMPRESSION (2026-09-04, still open). The model keeps only about three quarters of the
   real gap between elite and mid-tier attackers, so the optimiser drops Haaland for someone
   cheaper. Measured then on xG90: Haaland/Mbeumo 1.41 in the model against 1.88 in history.

5. NO COVER VALUE (2026-09-07). Squad metrics score a non-starting player at zero, so a dead
   bench player looks free to hold. Mateta was out until 11 October and did not surface as a
   priority sale, because he never appeared in the best XI either way. He was also one of only
   three forwards, so the squad had no forward cover at all. Jon has now corrected this same
   blind spot in two different models.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from collections import defaultdict

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOT = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXT = "https://fantasy.premierleague.com/api/fixtures/"
LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"

MIN_MINUTES = 150          # enough to have a meaningful per-90
LUCK_PREMIUM_TOL = 0.25    # points the model may pay for having been fortunate
P60_REGULAR = 0.85


def _get(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def load_context():
    """Everything the tests share, fetched once.

    Players are keyed on (web_name, team) throughout and NEVER on name alone. Seventeen web_names
    in the game are ambiguous — there are two Palmers, three Wilsons, three Phillipses — and a
    name-keyed lookup silently returned Ipswich's reserve keeper in place of Cole Palmer while
    this file was being written.
    """
    boot = _get(BOOT)
    tm = {t["id"]: t["short_name"] for t in boot["teams"]}
    elements = {(e["web_name"], tm[e["team"]]): e for e in boot["elements"]}

    fc_dir = ROOT / "data" / "processed"
    locks = sorted(fc_dir.glob("forecast_gw*.json"))
    locks = [p for p in locks if "_locked_" not in p.name]
    if not locks:
        raise SystemExit("  no locked forecast — run: python scripts/forecast.py")
    fc = json.loads(locks[-1].read_text(encoding="utf-8"))
    return dict(boot=boot, tm=tm, elements=elements, fc=fc, players=fc["players"],
                lock=locks[-1].name)


def regulars(ctx):
    """Players with enough minutes and a real starting probability, joined to their own stats."""
    out = []
    for key, p in ctx["players"].items():
        nm, t = key.split("|")
        e = ctx["elements"].get((nm, t))
        if not e or e["minutes"] < MIN_MINUTES or p["p60"] < P60_REGULAR:
            continue
        mins = e["minutes"]
        out.append(dict(
            name=nm, team=t, pos=p["pos"], ev=p["ev"][0], p60=p["p60"],
            xgi90=float(e["expected_goal_involvements"]) / mins * 90,
            pts90=e["total_points"] / mins * 90,
            over=(e["goals_scored"] + e["assists"]) - float(e["expected_goal_involvements"]),
            element=e))
    return out


def _ols2(ys, x1, x2):
    """Two-variable OLS, returning standardised betas. Small enough to not want a dependency."""
    n = len(ys)
    m1, m2, my = sum(x1) / n, sum(x2) / n, sum(ys) / n
    s11 = sum((a - m1) ** 2 for a in x1)
    s22 = sum((a - m2) ** 2 for a in x2)
    s12 = sum((a - m1) * (b - m2) for a, b in zip(x1, x2))
    s1y = sum((a - m1) * (b - my) for a, b in zip(x1, ys))
    s2y = sum((a - m2) * (b - my) for a, b in zip(x2, ys))
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-9:
        return 0.0, 0.0
    b1 = (s22 * s1y - s12 * s2y) / det
    b2 = (s11 * s2y - s12 * s1y) / det
    sdy = statistics.pstdev(ys) or 1.0
    return b1 * statistics.pstdev(x1) / sdy, b2 * statistics.pstdev(x2) / sdy


# ---------------------------------------------------------------- 1. point chasing
def test_point_chasing(ctx):
    """The projection must lean on underlying output, not on points already banked.

    Points scored and expected output are correlated, so the test is not "does points/90 predict
    the projection" — it is whether points/90 carries MORE weight than xGI/90 once both are in
    the same regression. If it does, the model is rewarding finishing luck, which does not
    persist, and it will keep buying players at the top of their variance.
    """
    # ATTACKERS ONLY, and the restriction is the whole point.
    #
    # The first version of this test ran on everybody and failed loudly, and it was wrong to. A
    # defender's points ARE mostly clean-sheet points, so points/90 legitimately proxies his
    # club's defensive strength and xGI/90 is close to irrelevant to him. Measured across
    # positions: keepers and defenders gave beta +0.039 on xGI against +0.341 on points, which is
    # the model working, not failing. Attackers gave +0.412 on each — genuinely equal weight,
    # where underlying output should dominate because finishing luck does not persist.
    # Clean-sheet quality is tested separately by test_cs_calibration.
    rs = [r for r in regulars(ctx) if r["pos"] in ("MID", "FWD")]
    if len(rs) < 30:
        return "point-chasing", None, [f"only {len(rs)} attackers — too early to judge"]
    b_xgi, b_pts = _ols2([r["ev"] for r in rs], [r["xgi90"] for r in rs], [r["pts90"] for r in rs])
    hi = [r for r in rs if r["over"] > 0.3]
    lo = [r for r in rs if r["over"] < -0.3]
    lines = [f"n={len(rs)} regular starters",
             f"standardised beta on xGI/90 (underlying) {b_xgi:+.3f}",
             f"standardised beta on points/90 (actual)  {b_pts:+.3f}"]
    if hi and lo:
        mh = sum(r["ev"] for r in hi) / len(hi)
        ml = sum(r["ev"] for r in lo) / len(lo)
        xh = sum(r["xgi90"] for r in hi) / len(hi)
        xl = sum(r["xgi90"] for r in lo) / len(lo)
        lines.append(f"overperformers n={len(hi)} xGI/90 {xh:.3f} -> ev {mh:.2f}")
        lines.append(f"underperformers n={len(lo)} xGI/90 {xl:.3f} -> ev {ml:.2f}")
        lines.append(f"luck premium {mh - ml:+.2f} pts for the same underlying output")
    # Two conditions, because the regression alone passes on a knife edge. Equal weight is not
    # acceptable: for an attacker, underlying output should CLEARLY dominate points already
    # banked, since finishing luck does not persist. The luck premium is the direct measure of
    # the harm — what the model pays for having been fortunate, holding underlying output equal.
    premium = None
    if hi and lo:
        premium = (sum(r["ev"] for r in hi) / len(hi)) - (sum(r["ev"] for r in lo) / len(lo))
    ratio_ok = b_pts <= 0 or b_xgi >= 1.5 * b_pts
    premium_ok = premium is None or premium <= LUCK_PREMIUM_TOL
    lines.append(f"underlying/actual beta ratio {b_xgi / b_pts:.2f}" if b_pts > 0 else "")
    if not ratio_ok:
        lines.append("FAIL: underlying does not clearly outweigh points banked (need 1.5x)")
    if premium is not None and not premium_ok:
        lines.append(f"FAIL: luck premium {premium:+.2f} exceeds {LUCK_PREMIUM_TOL}")
    return "point-chasing", (ratio_ok and premium_ok), [x for x in lines if x]


# ---------------------------------------------------------------- 2. fixture strength
MIN_FIXTURE_SPREAD = 1.5


def test_fixture_spread(ctx):
    """Easiest fixture minus hardest, in projected points.

    A defender's clean-sheet probability alone swings more than a point between the softest home
    game and the hardest away one, before any attacking difference. A spread below 1.5 means the
    model cannot tell you to sell a good player with a bad run, which is most of what a fixture
    model is for.
    """
    fixtures = _get(FIXT)
    tm = ctx["tm"]
    diff = {}
    for m in fixtures:
        if m["event"] is None:
            continue
        diff[(tm[m["team_h"]], m["event"])] = m["team_h_difficulty"]
        diff[(tm[m["team_a"]], m["event"])] = m["team_a_difficulty"]
    gw0 = ctx["fc"]["gw0"]
    rows = []
    for key, p in ctx["players"].items():
        if p["p60"] < P60_REGULAR:
            continue
        for i, gw in enumerate(range(gw0, gw0 + len(p["ev"]))):
            d = diff.get((p["team"], gw))
            if d is not None:
                rows.append((d, p["ev"][i]))
    if len(rows) < 100:
        return "fixture-spread", None, [f"only {len(rows)} player-gameweeks with a difficulty"]
    by = defaultdict(list)
    for d, ev in rows:
        by[d].append(ev)
    easy = [ev for d, ev in rows if d <= 2]
    hard = [ev for d, ev in rows if d >= 4]
    lines = [f"{len(rows)} player-gameweeks"]
    for d in sorted(by):
        lines.append(f"difficulty {d}: n={len(by[d]):<4} mean ev {sum(by[d]) / len(by[d]):.2f}")
    if not easy or not hard:
        return "fixture-spread", None, lines + ["no fixtures at one of the extremes yet"]
    spread = sum(easy) / len(easy) - sum(hard) / len(hard)
    lines.append(f"spread easiest-to-hardest {spread:+.2f} (need >= {MIN_FIXTURE_SPREAD})")
    return "fixture-spread", spread >= MIN_FIXTURE_SPREAD, lines


# ---------------------------------------------------------------- 3. minutes recency
RECENCY_TOL = 0.70


def test_minutes_recency(ctx):
    """A player who started the last two matches must not carry a low p60.

    p60 is a season average. A player who was rotated in August and has started since is the
    exact case where an average is wrong and a human is obviously right, and it is common: new
    signings, returning injuries, anyone who has just won a place.
    """
    boot = ctx["boot"]
    finished = [e["id"] for e in boot["events"] if e["finished"]]
    if len(finished) < 2:
        return "minutes-recency", None, ["fewer than two finished gameweeks"]
    last2 = finished[-2:]
    mins = defaultdict(dict)
    for gw in last2:
        for d in _get(LIVE.format(gw=gw))["elements"]:
            mins[d["id"]][gw] = d["stats"]["minutes"]
    offenders = []
    checked = 0
    for key, p in ctx["players"].items():
        nm, t = key.split("|")
        e = ctx["elements"].get((nm, t))
        if not e:
            continue
        m = mins.get(e["id"], {})
        if len(m) < 2 or not all(v >= 60 for v in m.values()):
            continue
        checked += 1
        if p["p60"] < RECENCY_TOL:
            offenders.append((p["p60"], nm, t, [m[g] for g in last2]))
    offenders.sort()
    lines = [f"{checked} players started (60+ mins) in both of GW{last2[0]} and GW{last2[1]}",
             f"{len(offenders)} of them carry p60 below {RECENCY_TOL}"]
    for p60, nm, t, mm in offenders[:8]:
        lines.append(f"  {nm} ({t}) p60 {p60:.2f} after {mm[0]}' and {mm[1]}'")
    return "minutes-recency", not offenders, lines


# ---------------------------------------------------------------- 4. premium compression
MIN_GAP_KEPT = 0.85


def test_premium_compression(ctx):
    """The model must preserve the gap between elite and mid-tier attackers.

    Compression is not a rounding error: it decides whether the optimiser keeps Haaland. Measured
    as the ratio of the top attackers' projection to the mid-tier's, against the same ratio in
    their actual underlying output. Anything below 0.85 means the model is flattening the top.
    """
    rs = [r for r in regulars(ctx) if r["pos"] in ("MID", "FWD")]
    if len(rs) < 30:
        return "premium-compression", None, [f"only {len(rs)} attackers with enough minutes"]
    rs.sort(key=lambda r: -r["xgi90"])
    n = max(3, len(rs) // 10)
    top, mid = rs[:n], rs[len(rs) // 2 - n // 2: len(rs) // 2 + n // 2 + 1]
    xt = sum(r["xgi90"] for r in top) / len(top)
    xm = sum(r["xgi90"] for r in mid) / len(mid)
    et = sum(r["ev"] for r in top) / len(top)
    em = sum(r["ev"] for r in mid) / len(mid)
    if xm <= 0 or em <= 0:
        return "premium-compression", None, ["mid-tier baseline is zero"]
    real, modelled = xt / xm, et / em
    kept = (modelled - 1) / (real - 1) if real > 1 else 1.0
    lines = [f"top {len(top)} by xGI/90 vs {len(mid)} mid-tier",
             f"real gap    {real:.2f}x  (xGI/90 {xt:.3f} vs {xm:.3f})",
             f"modelled    {modelled:.2f}x  (ev {et:.2f} vs {em:.2f})",
             f"share of the gap kept {kept:.2f} (need >= {MIN_GAP_KEPT})",
             "top names: " + ", ".join(r["name"] for r in top[:5])]
    return "premium-compression", kept >= MIN_GAP_KEPT, lines


# ---------------------------------------------------------------- 5. cover value
ENTRIES = ROOT / "data" / "state" / "entries.json"
NEED = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}     # minimum that must start


def live_squads(ctx):
    """{team name: [(web_name, team_short)]} pulled straight from the entry API.

    Read live rather than from a cached file: a cover check against last week's squad is worse
    than no cover check, because it reports confidently on a roster that has since changed.
    """
    if not ENTRIES.exists():
        return {}
    ids = json.loads(ENTRIES.read_text(encoding="utf-8")).get("ids", [])
    by_id = {e["id"]: e for e in ctx["boot"]["elements"]}
    gw = max((e["id"] for e in ctx["boot"]["events"] if e["finished"]), default=1)
    out = {}
    for eid in ids:
        try:
            entry = _get(f"https://fantasy.premierleague.com/api/entry/{eid}/")
            picks = _get(f"https://fantasy.premierleague.com/api/entry/{eid}/event/{gw}/picks/")
        except Exception:
            continue
        name = entry.get("name", str(eid))
        rows = []
        for p in picks.get("picks", []):
            e = by_id.get(p["element"])
            if e:
                rows.append((e["web_name"], ctx["tm"][e["team"]]))
        out[name] = rows
    return out


def test_cover(ctx, squads=None):
    """Every position must have at least one FIT player beyond the minimum that has to start.

    Squad metrics score a non-starting player at zero, so a dead bench player looks free to hold.
    That is how Mateta — out until 11 October, and one of only three forwards — failed to surface
    as a priority sale. This test does not ask what the bench is worth; it asks whether it exists.
    """
    if squads is None:
        squads = live_squads(ctx)
        if not squads:
            return "cover", None, ["no entry ids in data/state/entries.json"]
    lines, ok = [], True
    for team, names in squads.items():
        fit = defaultdict(int)
        dead = []
        for nm, t in names:
            e = ctx["elements"].get((nm, t))
            p = ctx["players"].get(f"{nm}|{t}")
            available = bool(e) and e["status"] == "a" and (p is None or p["p60"] >= 0.4)
            pos = p["pos"] if p else (e and {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
                                      .get(e["element_type"]))
            if pos:
                if available:
                    fit[pos] += 1
                else:
                    dead.append(f"{nm} ({pos})")
        lines.append(f"{team}: " + ", ".join(f"{k} {fit[k]}" for k in ("GK", "DEF", "MID", "FWD")))
        if dead:
            lines.append(f"  unavailable: {', '.join(dead)}")
        for pos, need in NEED.items():
            if fit[pos] <= need:
                ok = False
                lines.append(f"  NO COVER at {pos}: {fit[pos]} fit, {need} must start")
    return "cover", ok, lines


# ---------------------------------------------------------------- 6. clean sheets
CS_BIAS_TOL = 0.05


def test_cs_calibration(ctx):
    """Retro-predict the clean sheets in gameweeks already played.

    For a keeper or defender the clean sheet IS the projection — everything else is a rounding
    term on top of appearance points. So this is the single most important number in the model
    for half the squad, and it is testable directly: ask the model for each fixture that has
    already happened and compare with what occurred.

    Measured 2026-09-07 over 60 team-matches: mean predicted 0.373 against an actual rate of
    0.267, a bias of +0.106, with correlation 0.281. It is optimistic in every band above 0.2 and
    barely discriminates. Chelsea were given 0.529 having conceded seven in three with no clean
    sheet. This — not any points-versus-xGI weighting — is why defenders at leaky clubs rate too
    highly, and why Newcastle's defenders looked better than Arsenal's.

    Small samples run hot early in a season, so treat a bias under 0.05 as fine and read the
    correlation as the more durable signal.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import ev_v2 as V
    except Exception as e:
        return "cs-calibration", None, [f"cannot import ev_v2 ({type(e).__name__}: {e})"]
    tm = ctx["tm"]
    played = []
    for m in _get(FIXT):
        if not m["finished"]:
            continue
        h, a = tm[m["team_h"]], tm[m["team_a"]]
        played.append((h, a, True, m["team_a_score"] == 0))
        played.append((a, h, False, m["team_h_score"] == 0))
    preds = []
    for team, opp, home, got in played:
        try:
            preds.append((V.get_cs_probability(team, opp, home), got))
        except Exception:
            continue
    if len(preds) < 30:
        return "cs-calibration", None, [f"only {len(preds)} completed team-matches"]
    n = len(preds)
    mp = sum(p for p, _ in preds) / n
    ma = sum(1 for _, g in preds if g) / n
    xs = [p for p, _ in preds]
    ys = [1.0 if g else 0.0 for _, g in preds]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    r = cov / (sx * sy) if sx and sy else 0.0
    lines = [f"{n} completed team-matches",
             f"mean predicted {mp:.3f}  actual {ma:.3f}  bias {mp - ma:+.3f}"
             f" (tolerance {CS_BIAS_TOL})",
             f"correlation predicted vs realised r = {r:+.3f}"]
    for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, 1.01)):
        g = [(p, got) for p, got in preds if lo <= p < hi]
        if g:
            lines.append(f"  predicted {lo:.1f}-{hi:.1f}: n={len(g):<3} "
                         f"mean {sum(p for p, _ in g) / len(g):.3f} "
                         f"actual {sum(1 for _, x in g if x) / len(g):.3f}")
    return "cs-calibration", abs(mp - ma) <= CS_BIAS_TOL, lines


TESTS = [test_point_chasing, test_cs_calibration, test_fixture_spread, test_minutes_recency,
         test_premium_compression, test_cover]


def main():
    quiet = "--quiet" in sys.argv
    ctx = load_context()
    print(f"  model tests against {ctx['lock']}\n")
    failures = 0
    for fn in TESTS:
        name, passed, lines = fn(ctx)
        mark = "PASS" if passed else ("FAIL" if passed is False else "SKIP")
        if passed is False:
            failures += 1
        print(f"  [{mark}] {name}")
        if not quiet:
            for ln in lines:
                print(f"         {ln}")
            print()
    print(f"  {failures} of {len(TESTS)} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
