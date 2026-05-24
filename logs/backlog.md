# Bob — Backlog

Feature requests and bug reports. Each entry has enough context to build a fix or implement a feature later.

Add entries under **Bug Reports** when Bob did something wrong. Add entries under **Feature Requests** when a user asked for something Bob can't do yet.

---

## Bug Reports

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

---

## Feature Requests

(none yet)
