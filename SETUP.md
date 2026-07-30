# iPhone Setup — get the weekly report emailed automatically

Once this is set up (about 10 minutes, one time), you do **nothing** each week. The cloud runs the
whole system and **emails the report to your phone before every deadline** — Friday-night, Saturday,
or midweek, whatever day it falls on. You can also trigger it any time with one tap.

---

## Part 1 — One-time email setup (do this once)

The cloud needs permission to send you email through your Gmail. Google requires a special
"App Password" for this (your normal password won't work). Steps:

### 1a. Turn on 2-Step Verification (if it isn't already)
- On your iPhone, go to **myaccount.google.com** → **Security**.
- Make sure **2-Step Verification** is **On**. (If not, turn it on — you need it for the next step.)

### 1b. Create an App Password
- Go to **myaccount.google.com/apppasswords**.
- App name: type `FPL Bot` → tap **Create**.
- Google shows a **16-character password** (like `abcd efgh ijkl mnop`). **Copy it** (spaces don't matter).

### 1c. Add three secrets to your GitHub repo
- Open **github.com/villajono/fpl-2026-27** (log in).
- Tap **Settings** → in the left menu, **Secrets and variables** → **Actions**.
- Tap **New repository secret** and add these **three**, one at a time:

  | Name (exactly) | Value |
  |---|---|
  | `MAIL_USERNAME` | your Gmail address, e.g. `jonowen73@gmail.com` |
  | `MAIL_PASSWORD` | the 16-character App Password from step 1b |
  | `MAIL_TO` | where to send it — your email (can be the same Gmail) |

That's the whole setup. **You're done.**

---

## Part 2 — How it runs (deadline-aware — never misses a deadline)

The cloud checks every day, but only **emails you once per gameweek, the morning before that
gameweek's actual deadline** — whatever day it is. FPL deadlines aren't always Saturday: some are
**Friday night** (GW1 this season is **Fri 21 Aug, 6:30pm**) and a few are **midweek**. The system
reads the real deadline each day and times your email so you always have hours to act.

- **Automatically:** one email per gameweek, ~the day before the deadline, titled
  "⚽ FPL — deadline approaching". The report header shows the exact deadline and a live countdown.
- **Manually (one tap, any time):** GitHub mobile app → your repo → **Actions** tab → **Weekly FPL
  Report** → **Run workflow**. This always emails immediately — handy to test, or re-check before a
  deadline.
- **Backup copy:** every run also saves `report_latest.txt` to the repo, readable in the GitHub app
  any time — even if email ever fails (a failed send auto-retries the next day).

If you skip Part 1, everything still runs and saves the report to the repo; you just won't get the
email until the secrets are added.

---

## Part 3 — Overriding "will they start?" from your phone (the form)

When you know something the data doesn't — a returnee, a manager quote, a confirmed benching — use
the simple form. No typing player names, no JSON, no typos possible — everything is dropdowns.

### One-time setup (2 minutes)
1. **Turn on GitHub Pages:** repo → **Settings** → **Pages** → under "Build and deployment":
   Source = **Deploy from a branch**, Branch = **main**, folder = **/ (root)** → **Save**. Wait ~1 min.
2. **Open the form** on your iPhone: **https://villajono.github.io/fpl-2026-27/form.html**
3. First time only, it asks for a **GitHub token** so it can save your choices. Tap the "Create one
   here" link → tick **repo** → **Generate token** → copy → paste into the form → **Save token**.
   (The token is stored only on your phone, never in the page.)
4. **Add to Home Screen:** in Safari tap **Share → Add to Home Screen**, name it "FPL". One-tap app.

### Using it (30 seconds, any week)
- Pick **Club** → **Player** (the list fills in for that club) → **Will they start next gameweek?**
  (Definitely / Likely / 50-50 / Unlikely / Won't) → optional **Note** → **Save override**.
  You'll see "GW_N override saved ✓".
- Your active overrides show at the top, each with a **Remove** button.
- **Overrides apply to the next gameweek only** and clear automatically once that gameweek is played.
  If the same call still applies next week, just re-add it — it keeps you actively confirming rather
  than stale overrides lingering unnoticed.

The next report run reads your overrides and adjusts each player's P(starts) accordingly.

---

## Adjusting the schedule
The check runs daily at **07:00 UTC** — one line in `.github/workflows/weekly.yml`:
`cron: "0 7 * * *"`. Change the `7` to a different UTC hour if you want the daily check (and so the
pre-deadline email) to land at a different time. The email itself is always timed to the real
deadline, so you rarely need to touch this.
