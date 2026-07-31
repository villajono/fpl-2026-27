#!/usr/bin/env python3
"""Generate the definitive GW1-3 squad-comparison artifact HTML from gw13.json."""
import json, sys, html

J = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]
POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
SQUADS = ["Santa Claude", "FPL Mate", "Andy (LTFPL)"]
SUB = {"Santa Claude": "Model self-optimum", "FPL Mate": "Elite community squad",
       "Andy (LTFPL)": "Real manager · 388th / 11.4M last year"}


def esc(s): return html.escape(str(s))


def cell(ev, role):
    if ev is None:
        return '<td class="num muted">–</td>'
    cls = {"C": "cap", "S": "start", "B": "bench"}.get(role, "start")
    star = ' <span class="cx">×2</span>' if role == "C" else ''
    return f'<td class="num {cls}">{ev:.1f}{star}</td>'


rows_by_squad = {}
for name in SQUADS:
    s = J["squads"][name]
    pls = sorted(s["players"], key=lambda p: (POS_ORDER[p["pos"]], -sum(x or 0 for x in p["ev"])))
    body = []
    last_pos = None
    for p in pls:
        if p["pos"] != last_pos:
            body.append(f'<tr class="grp"><td colspan="6">{p["pos"]}</td></tr>')
            last_pos = p["pos"]
        never = all(r is None for r in p["role"])
        nm = f'{esc(p["name"])} <span class="tm">{esc(p["team"])}</span>'
        ps = f'{p["pstart"]:.2f}'
        body.append(
            f'<tr class="{"dead" if never else ""}"><td class="pl">{nm}</td>'
            + cell(p["ev"][0], p["role"][0]) + cell(p["ev"][1], p["role"][1]) + cell(p["ev"][2], p["role"][2])
            + f'<td class="num ps">{ps}</td></tr>')
    rows_by_squad[name] = "\n".join(body)

# weekly totals matrix
wk_rows = []
for name in SQUADS:
    s = J["squads"][name]
    cells = ""
    for w in s["weekly"]:
        cells += (f'<td class="num"><span class="tot">{w["total"]:.1f}</span>'
                  f'<span class="brk">{w["xi"]:.0f}<i>xi</i> +{w["cap"]:.0f}<i>c</i> +{w["auto"]:.1f}<i>a</i></span></td>')
    wk_rows.append(f'<tr><td class="pl">{esc(name)}</td>{cells}<td class="num grand">{s["total"]:.1f}</td></tr>')
wk_body = "\n".join(wk_rows)

tot = {n: J["squads"][n]["total"] for n in SQUADS}
gap = tot["FPL Mate"] - tot["Andy (LTFPL)"]

squad_sections = ""
for name in SQUADS:
    s = J["squads"][name]
    w = s["weekly"]
    circ = ' <span class="circ">circular benchmark</span>' if name == "Santa Claude" else ''
    squad_sections += f'''
<section class="squad">
  <div class="shead">
    <div><h3>{esc(name)}{circ}</h3><p class="ssub">{SUB[name]}</p></div>
    <div class="sgrand"><span>{s["total"]:.1f}</span><small>GW1-3 pts</small></div>
  </div>
  <div class="tw"><table class="ptab">
    <thead><tr><th class="pl">Player</th><th class="num">GW1</th><th class="num">GW2</th><th class="num">GW3</th><th class="num">P<span class="th2">start</span></th></tr></thead>
    <tbody>{rows_by_squad[name]}</tbody>
  </table></div>
</section>'''

page = f'''<title>FPL 2026-27 · Pre-season squad comparison (GW1-3)</title>
<style>
:root {{
  --bg:#f6f4f2; --card:#ffffff; --ink:#221b2e; --dim:#6f6880; --line:#e7e3ec;
  --accent:#4a0e4e; --good:#0b7d50; --cap:#8a6200; --cap-bg:rgba(180,140,20,.15);
  --start:#221b2e; --bench:#9a93a8; --grand-bg:#f0ecf3;
}}
@media (prefers-color-scheme:dark) {{
  :root {{ --bg:#141019; --card:#1e1830; --ink:#ece8f2; --dim:#9a93ad; --line:#2e2644;
    --accent:#c99bff; --good:#43dc99; --cap:#ffd166; --cap-bg:rgba(255,209,102,.13);
    --start:#ece8f2; --bench:#7a7392; --grand-bg:#261e3a; }}
}}
:root[data-theme="light"] {{ --bg:#f6f4f2; --card:#ffffff; --ink:#221b2e; --dim:#6f6880; --line:#e7e3ec;
  --accent:#4a0e4e; --good:#0b7d50; --cap:#8a6200; --cap-bg:rgba(180,140,20,.15); --start:#221b2e; --bench:#9a93a8; --grand-bg:#f0ecf3; }}
:root[data-theme="dark"] {{ --bg:#141019; --card:#1e1830; --ink:#ece8f2; --dim:#9a93ad; --line:#2e2644;
  --accent:#c99bff; --good:#43dc99; --cap:#ffd166; --cap-bg:rgba(255,209,102,.13); --start:#ece8f2; --bench:#7a7392; --grand-bg:#261e3a; }}

* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:960px; margin:0 auto; padding:32px 20px 64px; }}
.eyebrow {{ font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--accent); font-weight:700; margin:0 0 8px; }}
h1 {{ font-size:clamp(26px,4.5vw,38px); line-height:1.1; margin:0 0 10px; letter-spacing:-.02em; text-wrap:balance; }}
.lede {{ color:var(--dim); font-size:15px; max-width:62ch; margin:0 0 6px; }}
.meta {{ color:var(--dim); font-size:12.5px; margin:4px 0 28px; }}
.mono {{ font-family:ui-monospace,"SF Mono","Cascadia Code",Menlo,monospace; }}

.read {{ background:var(--card); border:1px solid var(--line); border-left:3px solid var(--accent); border-radius:12px; padding:16px 18px; margin:0 0 28px; }}
.read h2 {{ font-size:13px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin:0 0 8px; }}
.read p {{ margin:0; font-size:14.5px; }} .read b {{ color:var(--ink); }}
.hl {{ color:var(--good); font-weight:700; }}

.cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:0 0 30px; }}
.c {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; }}
.c .rk {{ font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--dim); }}
.c .nm {{ font-size:15px; font-weight:700; margin:2px 0 8px; }}
.c .pts {{ font-size:30px; font-weight:800; letter-spacing:-.02em; font-family:ui-monospace,monospace; }}
.c .pts small {{ font-size:12px; font-weight:500; color:var(--dim); letter-spacing:0; }}
.c .note {{ font-size:11.5px; color:var(--dim); margin-top:6px; min-height:2.4em; }}
.c.win {{ border-color:var(--accent); }}

h2.sec {{ font-size:13px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin:34px 0 12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}

.tw {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
th,td {{ text-align:left; padding:8px 10px; }}
th {{ font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--dim); font-weight:600; border-bottom:1px solid var(--line); }}
th.th2,.ps small {{ font-weight:400; }} .th2 {{ font-size:9px; text-transform:none; letter-spacing:0; color:var(--dim); }}
.num {{ text-align:right; font-family:ui-monospace,"SF Mono",Menlo,monospace; font-variant-numeric:tabular-nums; }}
.wktab td.num {{ vertical-align:top; }}
.wktab .tot {{ font-size:17px; font-weight:700; display:block; }}
.wktab .brk {{ font-size:10.5px; color:var(--dim); display:block; margin-top:2px; }}
.wktab .brk i {{ font-style:normal; opacity:.7; font-size:9px; }}
.wktab .grand {{ font-size:19px; font-weight:800; background:var(--grand-bg); border-radius:8px; }}
.wktab tr td:first-child {{ font-weight:600; }}

.squad {{ margin:0 0 26px; }}
.shead {{ display:flex; justify-content:space-between; align-items:flex-end; gap:12px; margin:0 0 4px; }}
.shead h3 {{ font-size:19px; margin:0; letter-spacing:-.01em; }}
.ssub {{ color:var(--dim); font-size:12.5px; margin:2px 0 0; }}
.sgrand {{ text-align:right; }} .sgrand span {{ font-size:24px; font-weight:800; font-family:ui-monospace,monospace; }}
.sgrand small {{ display:block; font-size:10.5px; color:var(--dim); text-transform:uppercase; letter-spacing:.08em; }}
.circ {{ font-size:10.5px; font-weight:600; color:var(--cap); background:var(--cap-bg); padding:2px 7px; border-radius:20px; vertical-align:middle; letter-spacing:.02em; }}

.ptab td {{ border-bottom:1px solid var(--line); }}
.ptab .pl {{ font-weight:500; }} .ptab .tm {{ color:var(--dim); font-size:11px; font-weight:400; }}
.ptab .grp td {{ font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); font-weight:700; padding:10px 10px 4px; border-bottom:none; background:transparent; }}
td.start {{ color:var(--start); }}
td.cap {{ color:var(--cap); font-weight:800; background:var(--cap-bg); }}
td.cx {{ font-size:9px; }}
td.bench {{ color:var(--bench); }}
td.muted {{ color:var(--bench); opacity:.5; }}
td.ps {{ color:var(--dim); font-size:12.5px; }}
tr.dead .pl {{ color:var(--bench); font-style:italic; }}

.legend {{ display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:var(--dim); margin:10px 2px 0; }}
.legend span b {{ font-weight:700; }}
.lg-cap {{ color:var(--cap); }} .lg-bench {{ color:var(--bench); }}

footer {{ margin-top:40px; padding-top:18px; border-top:1px solid var(--line); color:var(--dim); font-size:12.5px; }}
footer p {{ margin:0 0 8px; }} footer b {{ color:var(--ink); }}

@media (max-width:640px) {{
  .cards {{ grid-template-columns:1fr; }}
  .wrap {{ padding:24px 14px 48px; }}
}}
</style>

<div class="wrap">
  <p class="eyebrow">FPL 2026-27 · Model V2 (corrected)</p>
  <h1>Pre-season squad comparison — the first three gameweeks</h1>
  <p class="lede">Expected points for each squad's <b>starting XI</b> across GW1-3 (Aug 21 – Sep 12), the window before the likely GW4 wildcard. Every point comes from the XI plus captain doubling plus auto-subs — nothing else scores.</p>
  <p class="meta mono">All 5 audit fixes applied · Maguire override P(start)=0.95 · captain = highest-EV XI player each week</p>

  <div class="read">
    <h2>The read</h2>
    <p><b>Andy {tot['Andy (LTFPL)']:.1f} vs FPL Mate {tot['FPL Mate']:.1f} is a dead heat</b> — {gap:.1f} points over three weeks, about <span class="hl">0.9 a gameweek (~1.4%)</span>. The model cannot separate a top-400 real manager from an elite community squad over his actual planning window. Santa Claude's {tot['Santa Claude']:.1f} sits on top but is the model's own optimised output graded by the model that built it — a <b>circular benchmark</b>, not evidence of an edge.</p>
  </div>

  <div class="cards">'''

ranked = sorted(SQUADS, key=lambda n: -tot[n])
notes = {"Santa Claude": "Optimised to this metric — informative as a ceiling, not a rival.",
         "FPL Mate": "Highest of the two real, human-built squads.",
         "Andy (LTFPL)": "Level with Mate; two dead bench slots are deliberate — GW4 wildcard."}
for i, n in enumerate(ranked):
    win = ' win' if n == "Santa Claude" else ''
    page += f'''
    <div class="c{win}"><div class="rk">#{i+1}</div><div class="nm">{esc(n)}</div>
      <div class="pts">{tot[n]:.1f}<small> pts</small></div>
      <div class="note">{notes[n]}</div></div>'''

page += f'''
  </div>

  <h2 class="sec">Weekly totals — where every point comes from</h2>
  <div class="tw"><table class="wktab">
    <thead><tr><th class="pl">Squad</th><th class="num">GW1</th><th class="num">GW2</th><th class="num">GW3</th><th class="num">Total</th></tr></thead>
    <tbody>{wk_body}</tbody>
  </table></div>
  <div class="legend">
    <span><b class="mono">xi</b> = starting XI points</span>
    <span><b class="mono">c</b> = captain bonus (doubled best XI player)</span>
    <span><b class="mono">a</b> = auto-subs (bench cover when a starter plays 0 min)</span>
  </div>

  <h2 class="sec">Weekly score by player</h2>
  <div class="legend" style="margin-bottom:14px">
    <span><b class="lg-cap">Gold ×2</b> = captain that week</span>
    <span>Dark = in the XI</span>
    <span><b class="lg-bench">Grey</b> = on the bench</span>
    <span><i>Italic</i> = never starts (structural filler)</span>
    <span>P<sub>start</sub> = model/override probability of a 60+ min start</span>
  </div>
  {squad_sections}

  <footer>
    <p><b>Method.</b> V2 decomposes each player's expected points from first principles: appearance + team clean-sheet probability + per-90 xG/xA (fixture-scaled) + a distributional defensive-contribution bonus + saves — never a single blended number. Clean sheets are a shared team event; the captain is simply the highest-EV starter each week.</p>
    <p><b>Auto-subs</b> now fire only on a true 0-minute blank (not the old 1−P(start), which wrongly counted cameos) — hence ~1 point a week, not four. <b>Corrections</b> in this run: auto-sub trigger, position fallback for players with no prior-season data, cameo appearance point, cameo DC discount, and the transfer bench-cover term.</p>
    <p class="mono" style="opacity:.7">Objective: maximise FPL points. No rank, template, ownership, or differential logic anywhere in the model.</p>
  </footer>
</div>'''

open(OUT, "w", encoding="utf-8").write(page)
print(f"wrote {OUT} ({len(page)} bytes)")
