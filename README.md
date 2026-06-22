# Bob Frm Mktg

```
                    .-""""""""-.
                   /  ___  ___  \
                  | | [_] [_] | |      "Righto mate, let's see
                  | |  _______  | |     what the data says."
                  | | |_______| | |
                   \  `-_____-'  /
                    '----------'
                     /  |   |  \
                    /   |   |   \
                        |   |
                       _|   |_
                      (_|   |_)

              Bob — Performance Marketing Analyst
```

Bob is a performance marketing analyst that lives in your AI assistant. You ask questions about your Google Ads app campaigns in plain English — Bob pulls the data, does the maths, and tells you what's happening and what to do about it.

No dashboards. No spreadsheets. Just answers.

---

## How it works

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │   YOU          BOB                          GOOGLE ADS          │
  │                                                                 │
  │    │   "What happened yesterday?"                               │
  │    │ ─────────────────► │                                       │
  │                         │                                       │
  │                         ├── Seen this recently?                 │
  │                         │   (checks your local wiki)            │
  │                         │                                       │
  │                         ├── Got the data already?               │
  │                         │   (checks local files)                │
  │                         │                                       │
  │                         │   If not:          │                  │
  │                         │ ──────────────────►│                  │
  │                         │   Pull the numbers │                  │
  │                         │ ◄──────────────────│                  │
  │                         │                                       │
  │                         ├── Run the analysis                    │
  │                         │                                       │
  │    │  "Installs down 12%. Search is the culprit."               │
  │    │ ◄────────────────── │                                       │
  │                         │                                       │
  │    │  "Want me to save this to your wiki?"                      │
  │    │ ◄────────────────── │                                       │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

  Your data never leaves your machine. Bob reads from Google Ads
  and saves summaries locally — nothing is sent to any server.
```

---

## Before you start

You'll need:

- A **Mac or Windows** machine
- One of these AI desktop apps: **[Claude](https://claude.ai/download)**, **[Codex](https://openai.com/codex)**, or **[Antigravity](https://antigravity.ai)** — Bob lives inside whichever one you use. Not sure how to install one? Ask your office IT person — or open any AI chat (ChatGPT, Claude.ai, Gemini) and ask it to walk you through the install.
- A **Google Ads account** running App Campaigns
- A **Google Ads developer token** from **Google Ads > Admin > API Center** so Bob can download reporting data. Write access is optional and can be added later with a separate Google Cloud OAuth client JSON.

---

## Getting started

**Step 1 — Download Bob**

Download Bob from GitHub using **Code → Download ZIP**, then unzip it somewhere easy to find (Desktop is fine).

On the first run, Bob can download Python automatically if your machine doesn't already have it. Keep an internet connection on for setup.

Some AI apps run terminal commands in a restricted sandbox. Your browser may have internet while the AI's command runner does not. If setup asks for network/escalated command access, approve it so Bob can install its Python packages from the Python package index.

If setup fails while installing packages like `garf-executors`, `garf-google-ads`, or `google-ads`, it usually means the AI app's command runner could not reach the package index. It does not mean Bob is broken. Allow network access for setup, then ask Bob to "fix setup".

---

**Step 2 — Open the folder in your AI app**

This is the key step. Bob only works when your AI assistant has the project folder open — that's what gives it the context to act as Bob rather than a generic assistant.

- **Claude desktop app** — File → Open Folder → select the `bobFrmMktgCLI` folder
- **Codex** — Open the `bobFrmMktgCLI` folder as a project
- **Antigravity** — Open the `bobFrmMktgCLI` folder

Once the folder is open, the AI reads the project instructions automatically and becomes Bob.

---

**Step 3 — Say "set me up"**

Just type that in the chat. Bob will:
- Get itself ready on your machine
- Walk you through connecting your Google Ads account
- Suggest useful first questions

You don't need to install Python yourself. Bob handles the first-time setup and talks you through each step conversationally. Bob only pulls Google Ads data after you ask a performance question.

---

## What Bob can do

Once set up, just ask in plain English — Bob works out what you mean and reads the answer straight from your Google Ads data. Here's the full range.

### Daily & weekly check-ins

- *What happened yesterday?*
- *How did yesterday compare to the same day last week?*
- *How is this week tracking so far?*
- *How did last week compare to the week before?*

### Month & specific-period comparisons

- *How is this month tracking vs last month?*
- *How did May compare to April?*
- *Compare week 20 with week 19.*
- *May month-to-date vs April month-to-date.*

### What changed — and why

- *What caused the drop in installs last week?*
- *Why did my cost per install go up?*
- *Which network drove it — Search, Display, YouTube or Play?*

Bob works top-down — account → network → campaign → ad group — and overlays what the team changed around that time, so you get the cause, not just the number.

### Zoom into a group of campaigns

- *How are the Stable campaigns performing?*
- *Compare all the Brand campaigns week over week.*
- *Which campaigns are dragging?*

### Creatives — find the duds and fix them

- *Which creatives are underperforming?* — diagnosis with the why
- *Which assets should I pause or replace?*
- *Suggest better copy for the low-performing text assets.* — Bob drafts replacements and pushes them live once you approve
- *Build me a static banner design guide from my best performers.*
- *Make fresh versions of my low-performing banners.* — same-size replacements, shown to you as a preview before anything goes live

### Bids & budgets

- *What should I do with my bids and budgets this week?*
- *Show me the recommendation plan.*
- *Apply the changes.* — only ever after you say go
- *Are last week's bid changes working?* — a follow-up check a week or two later

### Team activity

- *What did the team change this week?*
- *What changed in [campaign name] recently?*

### Accounts & setup

- *Set me up.* / *Add another account.*
- *Switch to [account name].* / *Which account am I on?*
- *Check my config.* / *Setup failed — sort it out.*

### Share with your team

- *Hey Bob, sync.* — shares your saved analyses and notes with teammates through a shared folder (like Dropbox). Pull their updates, push yours. No login, no GitHub.

### Keep Bob sharp

- *Review your mistakes.* — Bob looks back over where it tripped up and writes a short improvement plan. Nothing changes until you approve it.

### Not sure where to start?

- *Suggest some questions to ask.*

Bob never invents numbers — every figure comes from a live read of your account. If something isn't possible yet, Bob will tell you straight and note it down to learn later.

---

## Where Bob saves things

Every analysis can be saved to a **wiki** — a folder of plain text files inside this project. Bob asks at the end of each session whether you want to save.

```
  wiki/
  └── your-account-id/
      ├── Index.md              ← everything in one place
      ├── analyses/             ← performance reports
      └── action-items/         ← bid/budget and creative plans
```

It's your running record of what you checked and when — searchable, shareable, no login required.

---

## Troubleshooting

**Setup failed or something isn't installing** — Tell Bob "setup failed" and paste the error. Bob will diagnose it.

**"Config not found" or credential errors** — Tell Bob "check my config". Most likely you need to point Bob to your credentials file.

**Data looks stale** — Tell Bob "pull fresh data".

**Something Bob can't answer** — Bob will say so in plain English and log it for future improvement. Logged questions live in `logs/backlog.md`.

---

## Development

*For contributors working on Bob's code — end users can ignore this section.*

`lib/datapull.py` is the engine. A lightweight smoke test pins its deterministic core (metric formulas, the zero-denominator → `NA` rule, period-date windows, and aggregation) so those invariants can't drift silently.

**Run the test** (pure stdlib, no extra dependencies, runs offline):

```
./.venv/bin/python tests/test_core.py      # or: python -m unittest -v tests.test_core
```

**Enable the pre-commit hook** (one-time, per clone) so the test runs automatically on every commit and blocks it on failure:

```
git config core.hooksPath scripts/hooks
```

The hook (`scripts/hooks/pre-commit`) is sub-second and uses `.venv/bin/python` if present, falling back to system `python3`. Bypass in an emergency with `git commit --no-verify`.

The test locks *stable, documented contracts* — not implementation details — so ordinary edits won't trip it. If you change a formula or period window **on purpose**, update the matching expected value in `tests/test_core.py`; the failing assertion is the deliberate checkpoint. Each assertion is commented with the formula it guards (see `CLAUDE.md`).
