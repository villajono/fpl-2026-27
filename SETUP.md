# iPhone Setup — get the weekly report emailed automatically

Once this is set up (about 10 minutes, one time), you do **nothing** each week. Every Saturday at
8am UK time, GitHub's cloud runs the whole system and **emails the report to your phone**. You can
also trigger it any time with one tap from the GitHub mobile app.

---

## Part 1 — One-time email setup (do this once)

The cloud needs permission to send you email through your Gmail. Google requires a special
"App Password" for this (your normal password won't work). Steps:

### 1a. Turn on 2-Step Verification (if it isn't already)
- On your iPhone, go to **myaccount.google.com** → **Security**.
- Under "How you sign in to Google", make sure **2-Step Verification** is **On**. (If not, turn it on — you need it for the next step.)

### 1b. Create an App Password
- Still in **Security**, search or scroll to **App passwords** (or go to **myaccount.google.com/apppasswords**).
- App name: type `FPL Bot` → tap **Create**.
- Google shows a **16-character password** (like `abcd efgh ijkl mnop`). **Copy it** (ignore the spaces).

### 1c. Add three secrets to your GitHub repo
- Open **github.com/villajono/fpl-2026-27** (log in).
- Tap **Settings** (top of the repo) → in the left menu, **Secrets and variables** → **Actions**.
- Tap **New repository secret** and add these **three**, one at a time:

  | Name (exactly) | Value |
  |---|---|
  | `MAIL_USERNAME` | your Gmail address, e.g. `jonowen73@gmail.com` |
  | `MAIL_PASSWORD` | the 16-character App Password from step 1b (spaces optional) |
  | `MAIL_TO` | where to send it — your email (can be the same Gmail) |

That's the whole setup. **You're done.**

---

## Part 2 — How it runs

- **Automatically:** every **Saturday 8am UK**, you'll get an email titled "⚽ FPL Weekly Report"
  with both teams' decisions, formatted to read cleanly on your phone.
- **Manually (one tap):** open the **GitHub mobile app** → your repo → **Actions** tab →
  **Weekly FPL Report** → **Run workflow**. The email arrives a minute later.
- **Backup copy:** the report is also saved as `report_latest.txt` in the repo, viewable in the
  GitHub app any time — even if email ever fails.

If you skip Part 1, everything still runs and saves `report_latest.txt` to the repo; you just won't
get the email until the secrets are added.

---

## Part 3 — Telling the model things it can't see (team news)

When you have knowledge the data doesn't — a World Cup returnee easing back in, a manager quote, a
confirmed benching — edit the override file from your phone:

1. GitHub mobile app → your repo → open **`data/state/human_input.json`**.
2. Tap the **pencil** (edit), add or change a line, for example:
   ```
   "Kinský": { "p_start": 0.95, "note": "confirmed Spurs #1 for GW1" }
   ```
3. Tap **Commit changes**.

The next run (automatic or manual) picks it up and the report reflects your input. Keep the JSON
punctuation intact (quotes, colons, commas) — if you're unsure, copy the format of the examples
already in the file.

---

## Adjusting the time
The schedule is one line in `.github/workflows/weekly.yml`: `cron: "0 7 * * 6"` (07:00 UTC Saturday).
Change the `7` to a different UTC hour, or the `6` to a different day (0=Sun … 6=Sat). Edit it in the
GitHub app, commit, done.
