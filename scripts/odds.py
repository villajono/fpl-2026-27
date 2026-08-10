#!/usr/bin/env python3
"""
odds.py — bookmaker-odds fixture inputs (Pinnacle via The Odds API), key-ready, mock-testable.

WHY: bookmaker markets are more efficient than any xG model for a specific matchup, so for the
near-term fixtures we replace the model's attacking multiplier and clean-sheet probability with
odds-derived values. Pinnacle is preferred for its low overround (~2-3% vs 5-8% mainstream).

WHAT WE PULL (The Odds API "featured" markets — free tier — for Pinnacle):
  - 1X2 (h2h)         result probabilities
  - Over/Under 2.5    total-goals expectation
Pinnacle has NO dedicated clean-sheet market, so CS is DERIVED: 1X2 + O/U are inverted to implied
home/away expected goals (lambda) via independent Poissons, then CS(team) = exp(-lambda_opponent).
Overround is removed from every market first (multiplicative normalisation).

GATING: off by default so pre-season squad work stays deterministic. Active only when a live key is
present (env ODDS_API_KEY) or mock odds are explicitly enabled (env FPL_USE_MOCK_ODDS=1). When active
but a given fixture has no published odds (e.g. GW+4 and beyond), fixture_inputs() returns None and
the caller falls back to the xG model.
"""
from __future__ import annotations
import os, json, math, urllib.request, urllib.parse
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "data" / "state"
MOCK_FILE = STATE / "mock_odds.json"
_KEYFILE = STATE / "odds_key.txt"                       # gitignored local key file (never committed)
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
if not ODDS_API_KEY and _KEYFILE.exists():
    ODDS_API_KEY = _KEYFILE.read_text(encoding="utf-8").strip()
USE_MOCK = os.environ.get("FPL_USE_MOCK_ODDS") == "1"
USE_FD = os.environ.get("FPL_USE_FD_ODDS") == "1"     # market-average odds (football-data.co.uk), no key
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "soccer_epl"
FD_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
LEAGUE_AVG_GOALS_PER_TEAM = 1.40           # PL long-run ~2.8 goals/game; centres att_mult on ~1.0

# football-data.co.uk team names -> our short codes (their naming differs from The Odds API's).
FD_NAME2SHORT = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE", "Brighton": "BHA",
    "Chelsea": "CHE", "Coventry": "COV", "Crystal Palace": "CRY", "Everton": "EVE", "Fulham": "FUL",
    "Hull": "HUL", "Ipswich": "IPS", "Leeds": "LEE", "Leicester": "LEI", "Liverpool": "LIV",
    "Man City": "MCI", "Man United": "MUN", "Newcastle": "NEW", "Nott'm Forest": "NFO",
    "Sheffield United": "SHU", "Southampton": "SOU", "Sunderland": "SUN", "Tottenham": "TOT",
    "West Ham": "WHU", "Wolves": "WOL", "Burnley": "BUR",
}

# The Odds API team names -> our short codes. Extend as needed; unknown names are skipped.
NAME2SHORT = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton and Hove Albion": "BHA", "Brighton": "BHA", "Chelsea": "CHE", "Crystal Palace": "CRY",
    "Everton": "EVE", "Fulham": "FUL", "Ipswich Town": "IPS", "Leeds United": "LEE", "Leeds": "LEE",
    "Leicester City": "LEI", "Liverpool": "LIV", "Manchester City": "MCI", "Manchester United": "MUN",
    "Newcastle United": "NEW", "Nottingham Forest": "NFO", "Southampton": "SOU",
    "Tottenham Hotspur": "TOT", "Tottenham": "TOT", "West Ham United": "WHU", "West Ham": "WHU",
    "Wolverhampton Wanderers": "WOL", "Wolves": "WOL", "Sunderland": "SUN", "Burnley": "BUR",
    "Coventry City": "COV", "Coventry": "COV", "Hull City": "HUL", "Hull": "HUL",
}


# ============================================================= core maths
def remove_overround(odds_dict):
    """Decimal odds -> fair probabilities summing to 1 (multiplicative margin removal)."""
    raw = {k: 1.0 / v for k, v in odds_dict.items() if v and v > 1.0}
    tot = sum(raw.values())
    return {k: p / tot for k, p in raw.items()} if tot > 0 else {}


def _pois_pmf(k, lam): return math.exp(-lam) * lam ** k / math.factorial(k)
def _pois_cdf(k, lam): return sum(_pois_pmf(i, lam) for i in range(k + 1))


def _mu_from_over25(p_over):
    """Total goals ~ Poisson(mu); solve mu so P(total>=3) == p_over."""
    lo, hi = 0.2, 7.0
    for _ in range(60):
        mu = (lo + hi) / 2
        (lo, hi) = (mu, hi) if (1 - _pois_cdf(2, mu)) < p_over else (lo, mu)
    return (lo + hi) / 2


def implied_lambdas(p_home, p_over):
    """Invert 1X2 (home-win prob) + O/U 2.5 (over prob) -> (lambda_home, lambda_away).
    mu = lam_h+lam_a from the total; supremacy delta solved so P(home win) matches (indep Poissons)."""
    mu = _mu_from_over25(p_over)
    def p_home_win(delta):
        lh, la = (mu + delta) / 2, (mu - delta) / 2
        return sum(_pois_pmf(h, lh) * _pois_pmf(a, la) for h in range(10) for a in range(h))
    lo, hi = -mu + 1e-6, mu - 1e-6
    for _ in range(60):
        d = (lo + hi) / 2
        (lo, hi) = (d, hi) if p_home_win(d) < p_home else (lo, d)
    delta = (lo + hi) / 2
    return (mu + delta) / 2, (mu - delta) / 2


# ============================================================= odds source (live or mock)
_TABLE = None    # {(team_short, opp_short, home_bool): {"lam_team":x, "lam_opp":y, "source":s}}
_CACHE = {}


def _parse_fixture(team, opp, home, m):
    """m: {'1x2':{home,draw,away}, 'ou25':{over,under}} -> lambdas for the TEAM (home flag)."""
    p = remove_overround(m["1x2"]); po = remove_overround(m["ou25"])
    if not p or not po: return None
    lam_h, lam_a = implied_lambdas(p.get("home", 0.4), po.get("over", 0.5))
    lam_team, lam_opp = (lam_h, lam_a) if home else (lam_a, lam_h)
    return dict(lam_team=lam_team, lam_opp=lam_opp)


def _load_mock():
    if not MOCK_FILE.exists(): return {}
    d = json.load(open(MOCK_FILE, encoding="utf-8")); out = {}
    for fx in d.get("fixtures", []):
        t, o, h = fx["team"], fx["opp"], bool(fx["home"])
        lm = _parse_fixture(t, o, h, fx)
        if lm:
            out[(t, o, h)] = dict(**lm, source="Pinnacle 1X2+O/U (mock)")
            out[(o, t, not h)] = dict(lam_team=lm["lam_opp"], lam_opp=lm["lam_team"], source="Pinnacle 1X2+O/U (mock)")
    return out


def _load_live():
    """Fetch Pinnacle 1X2 + totals from The Odds API. Key-ready; returns {} on any failure."""
    out = {}
    try:
        for market in ("h2h", "totals"):
            q = urllib.parse.urlencode(dict(apiKey=ODDS_API_KEY, regions="eu", markets=market,
                                            oddsFormat="decimal", bookmakers="pinnacle"))
            with urllib.request.urlopen(f"{ODDS_API_BASE}/sports/{SPORT}/odds?{q}", timeout=20) as r:
                data = json.load(r)
            for ev in data:
                th = NAME2SHORT.get(ev.get("home_team")); ta = NAME2SHORT.get(ev.get("away_team"))
                if not th or not ta: continue
                bk = next((b for b in ev.get("bookmakers", []) if b["key"] == "pinnacle"), None)
                if not bk: continue
                key = (th, ta)
                slot = out.setdefault(key, {})
                for mk in bk.get("markets", []):
                    if mk["key"] == "h2h":
                        d = {("home" if o["name"] == ev["home_team"] else "away" if o["name"] == ev["away_team"] else "draw"): o["price"] for o in mk["outcomes"]}
                        slot["1x2"] = d
                    elif mk["key"] == "totals":
                        line = next((o for o in mk["outcomes"] if abs(o.get("point", 0) - 2.5) < 0.01), None)
                        pts = {o["name"].lower(): o["price"] for o in mk["outcomes"] if abs(o.get("point", 0) - 2.5) < 0.01}
                        if pts: slot["ou25"] = pts
        table = {}
        for (th, ta), m in out.items():
            if "1x2" in m and "ou25" in m:
                lm = _parse_fixture(th, ta, True, m)
                if lm:
                    table[(th, ta, True)] = dict(**lm, source="Pinnacle 1X2+O/U (live)")
                    table[(ta, th, False)] = dict(lam_team=lm["lam_opp"], lam_opp=lm["lam_team"], source="Pinnacle 1X2+O/U (live)")
        return table
    except Exception:
        return {}


def _load_footballdata():
    """No-key, no-signup: the market AVERAGE 1X2 + O/U 2.5 from football-data.co.uk's fixtures.csv.
    Averaging across ~10 books is at least as sharp as any single book once overround is removed.
    Covers the upcoming round (so GW+1, sometimes GW+2). Returns {} on any failure -> xG fallback."""
    import csv, io
    try:
        with urllib.request.urlopen(FD_FIXTURES_URL, timeout=20) as r:
            rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig", "replace"))))
    except Exception:
        return {}
    table = {}
    for x in rows:
        if (x.get("Div") or "").strip() != "E0": continue          # Premier League only
        th = FD_NAME2SHORT.get((x.get("HomeTeam") or "").strip())
        ta = FD_NAME2SHORT.get((x.get("AwayTeam") or "").strip())
        if not th or not ta: continue
        def f(k):
            try: return float(x.get(k) or 0) or None
            except Exception: return None
        h, d, a, ov, un = f("AvgH"), f("AvgD"), f("AvgA"), f("Avg>2.5"), f("Avg<2.5")
        if not (h and d and a and ov and un): continue
        lm = _parse_fixture(th, ta, True, {"1x2": {"home": h, "draw": d, "away": a}, "ou25": {"over": ov, "under": un}})
        if lm:
            src = "Market avg 1X2+O/U (football-data)"
            table[(th, ta, True)] = dict(**lm, source=src)
            table[(ta, th, False)] = dict(lam_team=lm["lam_opp"], lam_opp=lm["lam_team"], source=src)
    return table


def set_source(name):
    """Switch odds source at runtime: 'fd' (market avg), 'mock', or 'off'. Clears caches.
    A live ODDS_API_KEY always takes precedence regardless of this setting."""
    global USE_MOCK, USE_FD, _TABLE, _CACHE
    USE_MOCK, USE_FD = (name == "mock"), (name == "fd")
    _TABLE, _CACHE = None, {}


def enabled():
    return bool(ODDS_API_KEY) or (USE_MOCK and MOCK_FILE.exists()) or USE_FD


def source_label():
    if ODDS_API_KEY: return "Pinnacle (live)"
    if USE_MOCK and MOCK_FILE.exists(): return "Pinnacle (mock)"
    if USE_FD: return "market average (football-data.co.uk)"
    return "off"


def _table():
    global _TABLE
    if _TABLE is None:
        if ODDS_API_KEY: _TABLE = _load_live()                     # Pinnacle via The Odds API (key)
        elif USE_MOCK and MOCK_FILE.exists(): _TABLE = _load_mock()
        elif USE_FD: _TABLE = _load_footballdata()                 # market average, no key
        else: _TABLE = {}
    return _TABLE


def fixture_inputs(team, opp, home):
    """-> dict(att_mult, cs_prob, sv_mult, source) for this specific fixture, or None if no odds.
    att_mult scales xG/xA (team's implied goals); cs_prob = exp(-opp lambda); sv_mult scales GK saves."""
    if not enabled(): return None
    key = (team, opp, bool(home))
    if key in _CACHE: return _CACHE[key]
    row = _table().get(key)
    if not row:
        _CACHE[key] = None; return None
    lam_t, lam_o = row["lam_team"], row["lam_opp"]
    res = dict(att_mult=lam_t / LEAGUE_AVG_GOALS_PER_TEAM, cs_prob=math.exp(-lam_o),
               sv_mult=lam_o / LEAGUE_AVG_GOALS_PER_TEAM, source=row["source"],
               lam_team=round(lam_t, 2), lam_opp=round(lam_o, 2))
    _CACHE[key] = res; return res


if __name__ == "__main__":
    os.environ["FPL_USE_MOCK_ODDS"] = "1"; USE_MOCK = True
    _TABLE = None; _CACHE = {}
    print(f"odds enabled: {enabled()} | fixtures in table: {len(_table())}")
    for (t, o, h) in sorted(_table())[:8]:
        fi = fixture_inputs(t, o, h)
        print(f"  {t} vs {o} ({'H' if h else 'A'}): att×{fi['att_mult']:.2f}  CS {fi['cs_prob']:.2f}  "
              f"sv×{fi['sv_mult']:.2f}  (lam {fi['lam_team']}/{fi['lam_opp']})  [{fi['source']}]")
