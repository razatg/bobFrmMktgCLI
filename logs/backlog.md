# Bob — Backlog

Feature requests and bug reports. Each entry has enough context to build a fix or implement a feature later.

Add entries under **Bug Reports** when Bob did something wrong. Add entries under **Feature Requests** when a user asked for something Bob can't do yet.

---

## Bug Reports

### [BUG] 2026-05-26 — campaign week aggregate skipped W21 raw slice for Rapido Demand
**User said:** "can you share diffs in top top campaigns for the same period"
**What happened:** Bob fetched raw `campaign_network_period` files for Rapido Demand for `2026-05-18` to `2026-05-24` and `2026-05-11` to `2026-05-17`, but `aggregate --grain campaign_network_period` only wrote the W20 processed slice and `compare-weeks --week 21 --vs 20 --year 2026 --grain campaign` still reported both weeks as missing.
**What's needed:** The campaign aggregate and compare-week lookup need to recognise freshly fetched closed-week campaign slices for the active account so Bob can rank top campaign movers.

### [BUG] 2026-05-25 — compare-weeks failed to detect existing W21 processed slice for Rapido Demand
**User said:** "I meant the last week and last to last week comparsion not this iso week which has just started so iso week 21 vs 20"
**What happened:** Bob fetched and aggregated `account_network_period` for Rapido Demand W21 (`2026-05-18` to `2026-05-24`), which created `/data/processed/3546923408/account-network/354-692-3408_2026-05-18_2026-05-24.csv`, but `python3 lib/datapull.py compare-weeks --week 21 --vs 20 --year 2026 --grain account` still reported the W21 processed file as missing.
**What's needed:** `compare-weeks` needs to look up the active account's processed week files correctly so closed-week comparisons work after a successful fetch and aggregate.

### [BUG] 2026-05-25 — Partial week comparison fetch failed for Rapido Demand
**User said:** "can you compare this week vs the last week"
**What happened:** Bob switched to the Rapido Demand account and attempted live `account_network_period` fetches for 2026-05-25 and 2026-05-18, but both GARF pulls failed so the comparison could not be produced.
**What's needed:** Bob needs a reliable path to fetch and compare partial current-week windows for a selected account, or a clearer recoverable error flow when GARF fails on valid account/date requests.

### [BUG] 2026-05-22 — Approval phrase routed to failsafe instead of bid-budget-apply
**User said:** "okay go ahead and make live"
**What happened:** Bob logged this as an unanswerable question instead of recognising it as approval to apply the current bid/budget plan.
**What's needed:** "okay go ahead", "make it live", "apply it", "yes do it" after a bid/budget plan has been shown should route to `bid-budget-apply`, not the failsafe.

### [BUG] 2026-05-21 — "What happened yesterday?" logged as unanswerable when data was missing
**User said:** "what happened yesterday?"
**What happened:** Bob hit the failsafe instead of offering to fetch the missing account_network_period data.
**What's needed:** When the route is clear (yesterday-vs-sdlw) but processed files are missing, Bob should offer to run bootstrap/fetch rather than fail to backlog.

### [BUG] 2026-05-22 — User correction mid-conversation logged as unanswerable question
**User said:** "no yeterdau is the 21st" / "what happened yesterday the 21st?"
**What happened:** Bob logged a user correction and rephrased follow-up as unanswerable questions. These are conversational repairs, not new questions.
**What's needed:** Mid-conversation corrections ("no", "I meant", "actually") should not trigger backlog logging — Bob should reinterpret and retry the corrected question.

### [BUG] 2026-05-29 — account/campaign totals dropped Users from reach
**User said:** "two issues really: [Image #1] * user level data missing * analysis mode should be allowed to write a bug report in logs/backlog.md"
**What happened:** Bob’s account/campaign comparison path showed `Users` as `0` because the raw network-period slices were not carrying `reach` through into the total account/campaign rows, while the network/ad group slices should not surface `reach` at all.
**What's needed:** Select `reach` for the account/campaign total query path, keep it `NA` for network/ad group breakdowns, and fail fast on stale raw slices that predate the reach fix.

### [FEATURE] 2026-05-29 — allow analysis-mode backlog writes
**User said:** "analysis mode should be allowed to write a bug report in logs/backlog.md"
**What happened:** Analysis mode blocked appending a bug report even though the Bob skill expects backlog logging for bugs and feature requests.
**What's needed:** Add `logs/backlog.md` to the analysis-mode write allowlist so bug reports can be recorded without developer mode.

---

## Feature Requests

(none yet)
