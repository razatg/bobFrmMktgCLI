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

Bob is a performance marketing analyst that lives in your terminal. You ask questions about your Google Ads app campaigns in plain English — Bob pulls the data, does the maths, and tells you what's happening and what to do about it.

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

- A **Mac** or **Windows** (Windows Terminal with WSL, or Git Bash — see setup notes below)
- A **Google Ads account** running App Campaigns
- A **Google Ads API credentials file** — a `.yaml` file that gives Bob read access to your account. Your developer can set this up, or follow the [Google Ads API quickstart](https://developers.google.com/google-ads/api/docs/get-started/introduction). Bob never stores your credentials — it reads the file fresh each time.

---

## Getting started

**Step 1 — Download the project**

Click the green **Code** button on this page → **Download ZIP**. Unzip it somewhere easy to find (Desktop is fine).

Or if you use Git:
```
git clone <this repo URL>
cd bobFrmMktgCLI
```

---

**Step 2 — Run setup**

**On Mac** — open Terminal, navigate to the folder, and run:
```
bash setup.sh
```

This installs everything Bob needs. If Python isn't on your machine it'll install it automatically via Homebrew. Takes about a minute.

**On Windows** — open Windows Terminal (or Git Bash), navigate to the folder, and run:
```
bash setup.sh
```

If you're using plain Windows Terminal without WSL or Git Bash, install Python first from [python.org](https://www.python.org/downloads/) (tick "Add Python to PATH" during install), then run:
```
pip install -r requirements.txt
```
And use `python lib/datapull.py` in place of `./bob` for all commands below.

---

**Step 3 — Connect your Google Ads account**

```
./bob onboard
```

Bob will walk you through it — your account ID, currency, primary goal (installs or in-app events), and where your credentials file lives. Takes about 2 minutes.

---

**Step 4 — Pull your first data**

```
./bob bootstrap
```

Fetches a snapshot of your recent campaign data — yesterday, last week, this month. Bob pulls pre-summarised numbers directly from Google Ads; nothing is stored raw on your machine beyond what's needed to answer questions.

You're ready.

---

## What you can ask

Once bootstrap is done, open a conversation with Bob (via Claude Code or any agent that reads `CLAUDE.md`) and ask in plain English.

### Yesterday & this week

- *What happened yesterday?*
- *How did yesterday compare to the same day last week?*
- *How is this week tracking so far?*

### Week over week

- *How did last week compare to the week before?*
- *What drove the change last week?*
- *How are the Brand campaigns doing week over week?*

### Month over month

- *How is this month tracking vs last month?*
- *How did May compare to April?*

### Campaigns

- *Which campaigns are dragging?*
- *How are the Stable campaigns performing?*
- *What caused the drop in installs last week?*
- *Which network is spending the most?*

### Creatives

- *Which creatives are underperforming?*
- *Which assets should I pause or replace?*
- *Can you suggest better copy for the low-performing assets?*

### Bids & budgets

- *What should I do with my bids this week?*
- *Show me the bid and budget recommendation plan.*
- *Apply the bid changes.*
- *Are last week's bid changes working?*

### Team activity

- *What did the team change this week?*
- *What changed in [campaign name] recently?*

### Not sure where to start?

- *Suggest some questions to ask.*

---

## Managing multiple accounts

Bob supports multiple Google Ads accounts.

```
./bob onboard          ← add another account
./bob switch-account   ← switch between accounts
./bob list-accounts    ← see all your accounts
```

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

**"command not found: ./bob"** — Run `bash setup.sh` first.

**"config not found" or credential errors** — Run `./bob check-config` to see what's missing. Most likely you need to point Bob to your credentials file — run `./bob onboard` again.

**Data looks stale** — Run `./bob bootstrap` to pull a fresh snapshot.

**Something Bob can't answer** — Bob will say so in plain English and log it for future improvement. Logged questions live in `logs/backlog.md`.
