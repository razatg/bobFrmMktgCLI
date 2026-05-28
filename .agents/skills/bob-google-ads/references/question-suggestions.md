# Question Suggestions

Use when the user asks what questions to ask, or as the post-onboarding follow-up step.

## When to Load This File

- User says "suggest questions", "what can I ask", "what should I ask", "give me questions", "what can you do", "what's possible", "show me examples"
- After `python3 lib/datapull.py onboard` completes successfully (see post-onboarding step in SKILL.md)

## How to Present

**CLI commands are NEVER shown to the user.** This file is agent-internal only. When presenting questions, Bob speaks in pure natural language — the agent runs the underlying commands silently.

Pick the group most relevant to context:
- New setup → First Run group first
- Established account → Weekly Analysis first, then others on request

Present 4–5 questions as a short natural-language bullet list in Bob's voice. One sentence max per question. Offer to show more groups if the user wants.

If triggered by post-onboarding: lead with a single sentence saying Bob will pull data only after the user asks a question, then list First Run questions. No preamble beyond that.

---

## Question Bank

The CLI command and reference columns are agent-internal routing only — never surface them to the user.

### Group 1: First Run (Post-Bootstrap)

| Question to present to user | Agent: CLI command | Agent: Reference |
|---|---|---|
| What happened yesterday? | `aggregate --grain account_network_period` | `account-yesterday-vs-sdlw.md` |
| How did yesterday compare to the same day last week? | `aggregate --grain account_network_period` | `account-yesterday-vs-sdlw.md` |
| How did last week compare to the week before? | `compare-weeks` | `calendar-period-comparison.md` |
| How is this month tracking vs last month? | `compare-months` | `account-period-comparison.md` |
| What did the team change recently? | fetch `change_history` | `change-history-summary.md` |
| Which campaigns are dragging? | `compare-weeks --grain campaign` | `delta-diagnosis.md` |

### Group 2: Weekly Analysis

| Question to present to user | Agent: CLI command | Agent: Reference |
|---|---|---|
| How did last week compare to the week before? | `compare-weeks` | `calendar-period-comparison.md` |
| Give me the full account breakdown with all metrics | `compare-weeks --all-metrics` | `calendar-period-comparison.md` |
| How are the [Stable / Brand / etc.] campaigns doing week over week? | `slice-campaigns --name-contains "..." --period wow` | `campaign-segment-comparison.md` |
| What drove the change last week? | `compare-weeks` → auto-escalation | `delta-diagnosis.md` |

### Group 3: Creative

| Question to present to user | Agent: CLI command | Agent: Reference |
|---|---|---|
| Which creatives are underperforming? | `slice-creatives` | `creative-underperformance.md` |
| Which assets should I pause or replace? | `slice-creatives` | `creative-underperformance.md` |
| Can you suggest better copy for my low-performing assets? | `suggest-creative-copy` | `bob-creative-copy` skill |

### Group 4: Bid / Budget

| Question to present to user | Agent: CLI command | Agent: Reference |
|---|---|---|
| What should I do with my bids this week? | `bid-budget-recommend` | `bob-bid-budget` skill → `algorithm.md` |
| Show me the current bid and budget plan | read `wiki/{id}/action-items/bid-budget-YYYY-MM-DD.yaml` | `bob-bid-budget` skill → `mutation-plan.md` |
| Are the bid changes from last week working? | `bid-budget-retrospective --plan ...` | `bob-bid-budget` skill → `retrospective.md` |

### Group 5: Diagnostic

| Question to present to user | Agent: CLI command | Agent: Reference |
|---|---|---|
| Why did performance drop last week? | `compare-weeks` → delta diagnosis | `delta-diagnosis.md` |
| Which network is dragging the account? | `compare-weeks --grain account` | `delta-diagnosis.md` |
| What changed in [campaign name] recently? | fetch `change_history` → filter by campaign | `change-history-summary.md` |
| Which ad groups in [campaign] are underperforming? | `fetch --query adgroup_network_period` (Tier 3) | `delta-diagnosis.md` |
| How does May compare to April? | `compare-months --month 5 --vs 4` | `calendar-period-comparison.md` |

---

## Caveats (agent-internal)

- All groups except First Run require at least one bootstrap pull to have been run.
- If bootstrap hasn't been run, Bob tells the user in his own words that he will pull the needed data for the question — never exposes the command.
- If read access is missing, Bob says: "I need the Google Ads developer token before I can fetch data from Google Ads." Then stops.
- Bid/budget and creative copy questions route to their own skills; listed here for discovery only.
