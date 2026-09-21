#!/usr/bin/env python3
"""reconcile.py — what the model recommended last week, against what the FPL site records.

WHY THIS EXISTS

Jon, 2026-09-21: "a couple of times I think the thoughts I have put down in the chat here have
become baked in as 'what actually happened'. What actually happened is what the FPL sites record."

The failure mode is specific and it is not about the squad. weekly.py already reads the live
fifteen, so the players are right. What goes wrong is the NARRATIVE: a recommendation gets made,
everyone assumes it was actioned, and the following week's reasoning is built on an assumption
nobody checked. The assumption is usually true - by agreement Santa Claude follows the model
exactly - which is what makes the exceptions so easy to miss:

  * Village Idiots takes the model as an input, not an instruction, so a divergence there is a
    normal decision, not an error.
  * Jon may be out of range of a deadline and have to guess at the recommendation.
  * A move can simply be actioned wrong in the app.

None of those are visible in the squad alone. A transfer that went to a different player still
leaves a valid fifteen; a captaincy that landed on the vice still leaves eleven starters. So this
compares the RECORDED recommendation against the RECORDED outcome, and says where they part.

    python scripts/reconcile.py                 # last completed gameweek, both entries
    python scripts/reconcile.py --gw 5
    python scripts/reconcile.py --gw 5 --entry 1169767

Where there is no stored recommendation for a gameweek - anything before 2026-09-21, when the
recording started - it says so rather than inventing one. Silence is not agreement.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state"
API = "https://fantasy.premierleague.com/api/"
TEAMS = {4180925: "SANTA CLAUDE", 1169767: "VILLAGE IDIOTS"}
# Santa Claude follows the engine by agreement, so a divergence there is a fault to investigate.
# Village Idiots weighs the engine against Jon's own judgement, so a divergence is a decision.
BINDING = {4180925: True, 1169767: False}
CHIP_CODE = {"wildcard": "WC", "bboost": "BB", "3xc": "TC", "freehit": "FH"}


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _arg(flag, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def rec_path(gw):
    return STATE / f"recommended_gw{gw}.json"


def save_recommendations(actions, gw):
    """Write what the model recommended, so next week can check it against the record.

    Called on every run and overwritten each time, so the file ends up holding the LAST
    recommendation made before the deadline - which is the one Jon would have acted on.
    """
    if not actions:
        return
    STATE.mkdir(parents=True, exist_ok=True)
    payload = {"gw": gw, "written": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "teams": {}}
    for a in actions:
        if not a.get("entry"):
            continue
        t = a["transfer"] or {}
        payload["teams"][str(a["entry"])] = {
            "team": a["team"],
            "transfer": ({"out": t.get("out"), "in": t.get("inn")} if t.get("do") else None),
            "chip": (a["chips"][0] if a.get("chips") else None),
            "captain": (a.get("captain") or "").split(" (")[0],
            "vice": a.get("vice") or "",
            "bench": [p.strip() for p in (a.get("bench") or "").split(",") if p.strip()],
        }
    rec_path(gw).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


def actual(entry, gw, els):
    """What the FPL site records for this entry in this gameweek. The source of truth."""
    picks = get(f"entry/{entry}/event/{gw}/picks/")
    transfers = [t for t in get(f"entry/{entry}/transfers/") if t["event"] == gw]
    subs = picks.get("automatic_subs", [])
    xi_ids, bench_ids, cap, vice = [], [], "", ""
    for p in sorted(picks["picks"], key=lambda x: x["position"]):
        (xi_ids if p["position"] <= 11 else bench_ids).append(p["element"])
        if p["is_captain"]:
            cap = els[p["element"]]["name"]
        if p["is_vice_captain"]:
            vice = els[p["element"]]["name"]

    # Undo FPL's automatic substitutions. Once a gameweek finishes, this endpoint reports the
    # FINAL eleven, with auto-subs already applied - so comparing it against the recommended bench
    # flags a divergence for something Jon did not choose and could not have prevented. The
    # benching decision under test is the one he SET at the deadline, which is this state with
    # each auto-sub reversed: the player who came on goes back to the bench, the one who did not
    # play goes back into the eleven.
    for s in subs:
        if s["element_in"] in xi_ids and s["element_out"] in bench_ids:
            xi_ids[xi_ids.index(s["element_in"])] = s["element_out"]
            bench_ids[bench_ids.index(s["element_out"])] = s["element_in"]
    xi = [els[i]["name"] for i in xi_ids]
    bench = [els[i]["name"] for i in bench_ids]
    auto = {s["element_in"] for s in subs}
    return dict(
        chip=CHIP_CODE.get(picks.get("active_chip")),
        transfers=[{"out": els[t["element_out"]]["name"], "in": els[t["element_in"]]["name"]}
                   for t in transfers],
        hit=picks["entry_history"].get("event_transfers_cost", 0),
        captain=cap, vice=vice, xi=xi, bench=bench,
        auto_subs=[els[e]["name"] for e in auto],
    )


def compare(rec, act, entry):
    """Line per decision: agreed, diverged, or not recorded. Returns (lines, n_divergences)."""
    L, n = [], 0

    def row(label, recommended, actually, same):
        nonlocal n
        if same:
            L.append(f"    {label:<10} followed    {actually}")
        else:
            n += 1
            L.append(f"    {label:<10} DIVERGED    recommended: {recommended}")
            L.append(f"    {'':<10}             actual:      {actually}")

    # --- chip ---
    rc, ac = (rec or {}).get("chip"), act["chip"]
    if rec is not None:
        row("chip", rc or "none", ac or "none", rc == ac)
    elif ac:
        L.append(f"    {'chip':<10} —           actual: {ac} (no recommendation on file)")

    # --- transfers ---
    at = act["transfers"]
    a_str = ", ".join(f"{t['out']} -> {t['in']}" for t in at) or "none"
    if act["hit"]:
        a_str += f"  (-{act['hit']} hit)"
    if rec is not None:
        rt = rec.get("transfer")
        r_str = f"{rt['out']} -> {rt['in']}" if rt else "none"
        same = (len(at) == 1 and rt and at[0]["out"] == rt["out"] and at[0]["in"] == rt["in"]) \
            or (not at and not rt)
        row("transfer", r_str, a_str, same)
    else:
        L.append(f"    {'transfer':<10} —           actual: {a_str} (no recommendation on file)")

    # --- captain ---
    if rec is not None:
        rcap = rec.get("captain", "")
        row("captain", rcap or "—", act["captain"] or "—", rcap == act["captain"])
    else:
        L.append(f"    {'captain':<10} —           actual: {act['captain']} (no recommendation "
                 f"on file)")

    # --- bench ---
    if rec is not None and rec.get("bench"):
        rb, ab = set(rec["bench"]), set(act["bench"])
        if rb == ab:
            L.append(f"    {'bench':<10} followed    {', '.join(act['bench'])}")
        else:
            n += 1
            L.append(f"    {'bench':<10} DIVERGED    started instead: "
                     f"{', '.join(sorted(rb - ab)) or '—'}")
            L.append(f"    {'':<10}             benched instead: "
                     f"{', '.join(sorted(ab - rb)) or '—'}")
    else:
        L.append(f"    {'bench':<10} —           actual: {', '.join(act['bench'])}")

    if act["auto_subs"]:
        L.append(f"    {'':<10}             (auto-subs came on: {', '.join(act['auto_subs'])} "
                 f"— FPL's doing, not a benching decision)")
    return L, n


def block(gw, els, entries=None):
    """The report block. Returns a list of lines, safe to print or append."""
    L = [f"LAST GAMEWEEK — RECOMMENDED vs WHAT THE FPL SITE RECORDS (GW{gw})",
         "━" * 31]
    stored = None
    if rec_path(gw).exists():
        stored = json.loads(rec_path(gw).read_text(encoding="utf-8")).get("teams", {})
    for entry in (entries or TEAMS):
        try:
            act = actual(entry, gw, els)
        except Exception as e:                       # a 404 simply means picks are not public yet
            L.append(f"  {TEAMS.get(entry, entry)}: could not read GW{gw} from the API ({e})")
            continue
        rec = (stored or {}).get(str(entry))
        L.append(f"  {TEAMS.get(entry, entry)} (entry {entry})")
        if stored is None:
            L.append("    no recommendation was recorded for this gameweek — reporting the "
                     "actual only, and not assuming the model was followed")
        lines, n = compare(rec, act, entry)
        L += lines
        if rec is not None:
            if n == 0:
                L.append("    → actioned as recommended")
            elif BINDING.get(entry):
                L.append(f"    → {n} divergence(s). This team follows the engine by agreement, so "
                         f"treat these as something to explain, not a preference.")
            else:
                L.append(f"    → {n} divergence(s). This team takes the engine as an input, so "
                         f"these are Jon's calls — the model plans from the ACTUAL squad above.")
        L.append("")
    return L


def main():
    els = {e["id"]: dict(name=e["web_name"]) for e in get("bootstrap-static/")["elements"]}
    boot = get("bootstrap-static/")
    now = dt.datetime.now(dt.timezone.utc)
    passed = [e["id"] for e in boot["events"]
              if dt.datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) <= now]
    gw = _arg("--gw", max(passed, default=1), int)
    entries = [_arg("--entry", cast=int)] if "--entry" in sys.argv else None
    for line in block(gw, els, entries):
        print(line)


if __name__ == "__main__":
    main()
