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

## Part 3 — Telling the model things it can't see (team news)

When you know something the data doesn't — a returnee easing back in, a manager quote, a confirmed
benching — edit the override file from your phone:

1. GitHub mobile app → your repo → open **`data/state/human_input.json`**.
2. Tap the **pencil** (edit), add or change a line, for example:
   ```
   "Kinský": { "p_start": 0.95, "note": "confirmed Spurs #1 for GW1" }
   ```
3. Tap **Commit changes**.

The next run (automatic or manual) picks it up. Keep the JSON punctuation intact (quotes, colons,
commas) — copy the format of the examples already in the file if unsure.

---

## Adjusting the schedule
The check runs daily at **07:00 UTC** — one line in `.github/workflows/weekly.yml`:
`cron: "0 7 * * *"`. Change the `7` to a different UTC hour if you want the daily check (and so the
pre-deadline email) to land at a different time. The email itself is always timed to the real
deadline, so you rarely need to touch this.
