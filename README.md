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
- A **Google Ads API credentials file** — a `.yaml` file that gives Bob read access to your account. Your developer can set this up, or follow the [Google Ads API quickstart](https://developers.google.com/google-ads/api/docs/get-started/introduction). Bob never stores your credentials — it reads the file fresh each time.

---

## Getting started

**Step 1 — Download the project**

Click the green **Code** button on this page → **Download ZIP**. Unzip it somewhere easy to find (Desktop is fine).

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
- Install everything needed on your machine (Python, dependencies)
- Walk you through connecting your Google Ads account
- Pull your first data snapshot

You don't need to run anything yourself — Bob handles it all and talks you through each step conversationally.

---

## What you can ask

Once set up, just ask in plain English. Examples:

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

Bob supports multiple Google Ads accounts. Just tell Bob in the chat:

- *"Add another account"*
- *"Switch to [account name]"*
- *"Which account am I on?"*

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
