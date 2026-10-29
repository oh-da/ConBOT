# Running ConBOT on GitHub Actions

ConBOT runs once a day in GitHub Actions, scans the conferences that are due,
and emails you over SMTP. No server needed.

The workflow is [`.github/workflows/scan.yml`](../.github/workflows/scan.yml).

## How it works

```
cron (05:17 UTC) ─► restore state ─► conbot scan --all ─► email ─► save state
                         ▲                                            │
                         └──────────── `bot-state` branch ◄───────────┘
```

- **Schedule**: the workflow fires daily. ConBOT's own state machine decides
  which conferences are actually due (MONTHLY = every 30 days, BIWEEKLY = 14,
  URGENT = daily), so most days only a few conferences (or none) are scanned.
- **State**: the runner's disk is wiped after each run, so the SQLite database
  is exported to JSON (`current.json`, `audit.json`, `history.json`) and
  committed to an orphan branch called `bot-state`. The next run restores it
  into a fresh SQLite file. The branch is created automatically on the first run.
- **Email**: plain SMTP using only the standard library. Gmail works with an
  app password.

## Setup

1. **Merge to the default branch.** GitHub only runs scheduled workflows (and
   shows the "Run workflow" button) for the workflow file on the default branch.

2. **Create an SMTP password.** For Gmail: turn on 2-step verification, then
   create an app password at <https://myaccount.google.com/apppasswords>.

3. **Add repository secrets** (Settings → Secrets and variables → Actions → *Secrets*):

   | Secret | Value |
   |---|---|
   | `SMTP_USERNAME` | e.g. `you@gmail.com` |
   | `SMTP_PASSWORD` | the app password |
   | `RECIPIENT_EMAIL` | where alerts should go |
   | `OPENAI_API_KEY` | *(optional)* enables LLM change summaries |

4. **Add repository variables** if you are not using Gmail (same page → *Variables*):

   | Variable | Default | Notes |
   |---|---|---|
   | `SMTP_HOST` | `smtp.gmail.com` | |
   | `SMTP_PORT` | `587` | 587 = STARTTLS, 465 = implicit TLS |
   | `SENDER_EMAIL` | the SMTP username | From address |

5. **Check Workflow permissions** (Settings → Actions → General): the workflow
   asks for `contents: write` so it can push `bot-state`. If your organisation
   restricts the default token to read-only, allow write access for this repo.

6. **Test the email**: Actions → *ConBOT scan* → *Run workflow* → `test-email`.

7. **Take the baseline**: run the workflow once with `scan`. The first scan of
   each conference records its current page and sends one email per conference
   (six with the shipped config). After that you only hear about changes, plus
   a "no changes" email each time a conference is scanned.

## Manual runs

Actions → *ConBOT scan* → *Run workflow*:

| Action | What it does |
|---|---|
| `scan` | Same as the nightly run: scans conferences that are due |
| `force-scan` | Scans every active conference regardless of schedule |
| `test-email` | Sends a test email and nothing else |

## Changing things

- **Schedule**: edit the `cron` line in `scan.yml`.
- **Conferences**: edit `config/conferences.yaml`. New ids are picked up on the
  next run, ids you remove stop being scanned (their history stays in the
  state), and changing a conference's first URL resets its baseline.
- **Reset everything**: delete the `bot-state` branch.

## Limitations

- Only the **first URL** of each conference in `conferences.yaml` is fetched.
  `secondary_urls` and `link_discovery` are not used yet.
- Two conferences (TRB, ITS World Congress) are flagged `js_required` and are
  fetched with headless Chromium, which the workflow installs on every run
  (about a minute).
- Some sites may refuse requests from GitHub's data-centre IPs. A failed fetch
  shows up as a failed run plus an error email (first failure, then every 7th
  consecutive one), and is retried on the next run.
- GitHub may disable scheduled workflows after 60 days without repository
  activity. If the daily emails stop, check the Actions tab and re-enable it.
- `bot-state` gains one small commit per run that changes anything. It is
  state, not source: don't merge it.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Run fails at "Check required secrets" | `SMTP_USERNAME`, `SMTP_PASSWORD` or `RECIPIENT_EMAIL` not set |
| `SMTP authentication failed` | Gmail needs an app password, not your account password |
| `Permission denied` pushing `bot-state` | Workflow permissions are read-only (see setup step 5) |
| Every run re-sends baseline emails | `bot-state` branch missing or not being pushed; check the "Save state" step |
| Run is green but nothing arrives | No conference was due; use `force-scan` to check |

Run it locally the same way the workflow does:

```bash
pip install .
export SMTP_USERNAME=... SMTP_PASSWORD=...
conbot scan --all -r you@example.com -c config/conferences.yaml -d ./conbot.db
```
