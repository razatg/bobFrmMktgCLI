# Bob release notes — 19 November 2026

**Built and checked locally; awaiting final staging review and deployment.**

This update gives Bob more context for recommendations and a lasting record of decisions, their evidence and expected results. Existing chat and creative workflows remain the starting point.

## What’s new and how to use it

### Reuse earlier work
Ask “What happened last week?” or “Show me that creative proposal again.” Bob first searches saved account reports and artifacts, checks that their dates and evidence match, and links suitable existing work. It fills gaps or refreshes stale evidence when needed. You do not need to ask Bob to search first.

Saved bid and budget proposals are searchable too. Ask “Continue the T3 proposal.” Bob should recover and inspect the saved proposal before suggesting a rebuild. You do not need to supply or save an approval hash; Bob recalculates it from the exact plan. Your explicit approval is still required before changes are applied.

### Recommendations without an extra live check
Asking which bids or budgets to change no longer triggers an execution-validation request to Google Ads. Saved marketing targets and preferred waiting periods inform the recommendation. Bob checks current campaign settings when applying the exact proposal you approve; an execution timeout does not invalidate the earlier analysis.

Creative proposals also retain the existing suggestion format. If you approve 26 out of 32 candidates, Bob can save those exact 26 with their supporting evidence for review and execution.

Descriptions without a full stop can still be saved and applied; Bob reviews punctuation as a writing choice. Reporting also reuses complete saved date ranges, keeps primary conversions distinct from installs, and requests whole-period reach rather than adding weekly unique users. Older long-period reach reports may need rebuilding before reuse.

### Recommendations with more context
Bob can bring together performance, creative results, recent changes, account goals and earlier decisions before recommending a next step. It can investigate beyond the usual recommendation when the evidence supports it, or recommend waiting.

**Ask:** “Performance got worse last week. Should we change bids, budget or creatives? Explain why, and tell me if we should wait.”

Bob identifies missing evidence rather than treating unavailable data as a clean bill of health.

### Goals and priorities
An Admin can record the account’s objective, ordered priorities, targets, budget, constraints and review date under **Clients → select a client → Accounts → Goals**. Bob receives these when preparing its recommendations.

**Ask:** “What would you change this week, and why?” Saved goals are included automatically; you do not need to mention them.

The form includes a CPI/CPA selector, currency labels and usual-approach fields. Campaign-specific context belongs in account knowledge or the current chat.

Fill this in as the standing brief for the account. Use one clear outcome and put the most important priority first. For example:

**Objective** — the outcome you want, such as “Grow completed first purchases efficiently.”

**Priorities in order** — enter each on a new line, for example:

```text
Efficiency
Completed first purchases
Coverage in priority cities
```

**Performance targets** — select Cost per install or Cost per in-app conversion. For an illustrative account, enter a target cost of 180 and monthly budget target of 12000000, using the displayed account currency. These are desired outcomes, not automatic spending controls. Enter plain numbers without commas.

**Usual approach** — existing acquisition cost reference, typical adjustment and preferred wait values carry over. For example: acquisition cost reference 200, typical adjustment 10%, preferred time between changes 14 days. These guide Bob rather than vetoing a different recommendation. Clearing a reference leaves it unspecified; the baseline recipe still has default reference values.

**Context and preferences** — use one line per thought, for example:

```text
Prefer smaller experiments when evidence is uncertain.
We can tolerate higher acquisition costs during launches.
```

For a temporary campaign preference, tell Bob in chat: “Leave the launch campaigns alone for this review.” For a standing preference, add it to the account’s knowledge notes (KT), for example: “Launch campaigns are managed separately; check with us before suggesting changes.” Campaign search and exclusion selection are not part of Goals.

**Names to preserve in creative copy** — enter exact brand or product names, each on its own line. These remain copy checks.

**Review goals on** — choose when to reconsider the goals, for example 30 November 2026. This does not schedule a job.

Click **Save goals**. Saving changes the account brief, not live ads. If strategic goals are blank, Bob uses account reference values, evidence, account notes and earlier decisions. It should ask when an unstated priority would materially change the recommendation.

#### How this plays out

Illustrative scenario: acquisition cost is above target but completed purchases are growing. Efficiency is the first priority. The usual adjustment is 10% and preferred wait is 14 days.

1. Ask Bob: “Performance got worse last week. What should we do?”
2. Bob uses the objective and ordered priorities to frame the trade-off. It checks the cost target, budget, recent changes, account knowledge, current instructions and relevant evidence.
3. A recent bid change is a reason to consider waiting. Bob weighs conversion delay and current evidence rather than rejecting action solely because 14 days have not passed.
4. Bob may propose a 15% adjustment if evidence supports it. It must explain the departure, trade-off and risk, then state the expected outcome and review window. The proposal displays warnings about departures and respects the campaign scope agreed for the review.
5. You review the exact proposal. Nothing changes in Google Ads until the final proposal is explicitly approved.
6. After the observation period, ask Bob to review the recorded prediction. It reports supported, contradicted or inconclusive and uses that result in later recommendations.

Use chat to discuss priorities; have an Admin save lasting account settings. See the settings limitations below before using the new form.

### Decisions you can revisit
Bob has a decision journal for recommendations, including decisions to wait, rejected suggestions and overrides. Records can retain the evidence, expected outcome and subsequent execution results so a later conversation can revisit them.

**Ask:** “What did we recommend for this campaign last time, and what evidence supported it?”

### Check whether a decision worked
You can request a review of a recorded prediction after its observation period and conversion delay. The review reports whether the evidence supports it, contradicts it or is inconclusive.

**Ask:** “Review the last recorded budget decision. Did the results match the prediction?”

Reviews run on request. They do not automatically run later, and a matching result does not prove the change caused it.

### Find earlier work
Bob can search saved analyses, account notes and decision records for the selected account.

**Ask:** “Find our earlier analysis of this campaign and explain what has changed since then.”

### More checks before changes
Bob verifies work using the relevant skill and available evidence: calculated outputs for analysis, saved proposals for copy and budgets, and rendered images/video plus audio for creative review. It corrects recoverable tool failures and rechecks, and explains material uncertainty. There is no universal automatic answer gate. Technical execution checks and explicit approval remain enforced.

Copy proposal saves return row-specific errors for missing text, character limits, punctuation and protected names. Bob fixes those rows and retries before presenting the saved draft. Successful saving does not certify creative quality or authorise publication.

**Ask:** “Suggest replacement copy for the weakest text ads and show me the proposal for review.”

Review the proposal before approving it. Asking for a recommendation does not authorise a change to Google Ads. Revised proposals need fresh approval.

## Before release

- **Settings fixes:** account-name saves preserve omitted settings, and goal saves refresh cached values so navigating between tabs retains them.
- **Review experience:** CSV proposals are still displayed as raw text; use Download for easier inspection. Failed chat requests can leave a stale “thinking” message.
- Local regression checks passed, but full staging conversations, approval flows and team acceptance are still pending. These notes describe the build, not a deployed release or a proven improvement in recommendation quality.

## Two end-to-end examples

These are example journeys to try after release, not results from a live account.

### 1. From a performance drop to a reviewed change

1. **Select the right account in Chat.** Ask: “Performance got worse last week. Investigate the cause and recommend whether to change bids, budget or creatives—or wait.”
2. **Read the diagnosis.** Bob brings together available evidence, recent changes and earlier decisions. Ask: “What supports that recommendation, and what information is missing?”
3. **Request a concrete proposal.** If a bid or budget change is supported, say: “Show me the exact changes, expected outcome and when we should review them. Record the decision and its evidence.” If waiting is the recommendation, ask Bob to record why and what would trigger another look.
4. **Review, then approve.** Check the account, affected campaigns, proposed values and limits. Approve the specific final proposal only when satisfied. A proposal alone changes nothing.
5. **Check the result.** Ask: “What actually applied, and did anything fail or remain uncertain?” Keep the decision reference Bob provides for the later review.

### 2. From an earlier decision to a follow-up verdict

1. **Return to the same account**, even in a new conversation. Ask: “Find our last recorded budget decision for this campaign. What did we expect, and what actually applied?”
2. **Confirm the record.** Check that Bob found the intended decision and its original evidence. If there are several, identify the one you mean.
3. **Request the review.** Ask: “Has the observation period and conversion delay passed? If so, compare the results with the recorded prediction and save the review.”
4. **Read the verdict.** Bob reports supported, contradicted or inconclusive. Missing data, immature conversions or other changes can make the result inconclusive; that is not proof of success or failure.
5. **Choose the next step.** Ask: “Given this review and our current priorities, should we continue, wait or prepare a new proposal?” Any new change goes through its own review and approval. Nothing is automatically scheduled or applied.

## Example of a recorded decision

This is fictional, abbreviated JSON illustrating the saved record, not an account result. A record also stores the selected account, goals snapshot, model/code versions and immutable evidence references. Each account has a SQLite decision journal; the original evidence is retained separately by content hash.

```json
{
  "situation": "A campaign is exhausting budget early; conversion data is mature.",
  "recommendation": "Test a 15% budget increase instead of the usual 10%.",
  "alternatives": ["Hold", "Use the usual 10% adjustment"],
  "departure": {
    "usual_change_pct": 10,
    "proposed_change_pct": 15,
    "reason": "The cited analysis supports testing additional volume.",
    "risk": "Additional spend may raise acquisition cost."
  },
  "prediction": {
    "metric": "in_app_conversions",
    "direction": "higher",
    "baseline": 100,
    "days": 7,
    "maturity_days": 3,
    "entity": {"campaign_id": "123456789"}
  },
  "human": null,
  "execution": null,
  "review": null
}
```

Before execution, Bob links the decision to the exact proposal you review. Approval and actual execution results are attached later. After the observation window and conversion delay, ask “Review that budget decision.” Bob saves supported, contradicted or inconclusive against its prediction; the result does not establish causation.
