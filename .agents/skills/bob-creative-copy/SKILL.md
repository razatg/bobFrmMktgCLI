---
name: bob-creative-copy
description: Use when the user asks to review or replace LOW-performing text asset copy in Google App Campaigns.
---

# Bob Creative Copy Skill

Use this skill when the user asks about reviewing, rewriting, or replacing creative copy for LOW-labeled text assets.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Investigation contract

Start with `./bob brief --focus creative` (or `all` when explanations cross domains). The gateway's selected account is authoritative. Rules and evidence maturity come from the brief; unavailable evidence is not an empty finding. Use `./bob search` for relevant knowledge and history.

Recipes and fixed policies are baselines, not exclusive routes. Registered analysis operations may be used during ordinary investigations. Agree, hold or depart with evidence. Hard limits and explicit approval apply to everyone; no decision modes. Use current CLI help over legacy command examples.

Record consequential recommendations, immutable evidence and a prediction with `./bob decision record` before execution; put its `decision_id` on the plan. Bid changes require `bid-budget-validate` before approval and `--approval-hash` at apply, which rechecks live state. Review the recorded prediction with `./bob decision review` after the observation window and conversion maturity. Do not infer outcomes from action names.

## Saving final asset choices

Before returning replacement suggestions, merge the generated text into the exact asset choices and save them with `creative-copy-propose`. Never list the original candidate plan as the final proposal while its `suggested_text` values are empty. Keep the exact current copy, entity IDs, field type and rationale from the evidence. The save command returns row errors for missing/oversized text, punctuation and configured protected names; correct those rows and retry. Read the saved proposal back and ensure the displayed replacements match it. Review meaning, factual offers and live GOOD/BEST peers using current evidence; saving is not proof of copy quality or live eligibility. Tool feedback does not authorise applying any changes.

Use `./bob creative-copy-propose --plan <baseline> --changes-json '<final asset choices>' --output <account plan>` to add, drop or change supported replacement/pause choices with reasons. Record the prediction and link it with `./bob decision link <id> --plan <final plan>`. Apply retains live validation and explicit approval. GOOD/BEST peers are refreshed from live evidence; account protected names are preserved without guessing proper nouns from capitalization.

## Operating Rules

- Follow the universal contract in `AGENTS.md`. Use registered commands and operations for ordinary analysis; source edits require separate development authorization. Inspect structured failures and supported alternatives before using the failsafe.
- **Never call `creative-copy-apply` without explicit user approval** at the approval table. The command is also hard-blocked for Bob users with `READ` access.
- Never generate copy suggestions yourself inline. The subagent in Step 2 does this — always.
- All creative-copy artefacts are account-scoped. First identify the active account's customer ID with `./bob list-accounts`, remove dashes, and use `wiki/<customer_id>/action-items/` for every plan, batch, suggestion, and final artefact path. Never use the flat `wiki/action-items/` directory.

## Step 1 — Generate the candidate list

```bash
# Check the selected account's creative coverage first
./bob data-manifest --account CUSTOMER_ID --query creative_headline_period --from DATE --to DATE
./bob data-manifest --account CUSTOMER_ID --query creative_description_period --from DATE --to DATE

# If missing or stale, pull only text assets in two separate, server-filtered
# requests. The account profile supplies the lookback (default 15 days) and
# impression threshold (default 50,000). These requests are deliberately not
# daily-segmented or combined with image/video rows.
./bob fetch --query creative_headline_period --reason "creative copy plan: headlines"
./bob aggregate --grain creative_period --source creative_headline_period
./bob fetch --query creative_description_period --reason "creative copy plan: descriptions"
./bob aggregate --grain creative_period --source creative_description_period

# Generate YAML plan + batch prompt files
./bob suggest-creative-copy --output-dir wiki/<customer_id>/action-items
# Outputs:
#   wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD.yaml           — per-asset plan
#   wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-batch-001.txt  — assets 1–25
#   wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-batch-002.txt  — assets 26–50
#   ... (one file per 25 assets)
```

If the baseline has zero candidates, report that baseline result. If the user asked a broader question, investigate other registered evidence rather than treating LOW as the only possible answer.

When the customer requests the complete review as CSV, every row must include campaign and ad-group
identity, field type, current copy, proposed copy, reason for change, and the supporting performance
metric. Do not produce a proposal-only CSV that omits the current copy or evidence.

For a request for all creative/assets, run the four asset types sequentially in this order:
`creative_headline_period`, `creative_description_period`, `creative_image_period`,
`creative_video_period`. A request for one type runs only that type. Do not pull image/video
data when the user asked for text.

## Step 2 — Spawn one subagent per batch file (SEQUENTIAL — no bulk reads)

**HARD RULES — no exceptions:**
- Do NOT use Explore or any subagent to read batch files.
- Do NOT read more than one batch file at a time.
- Do NOT spawn more than one Agent call at a time — no parallel Agent calls.
- Do NOT start the next batch until the current Agent call has returned its result.
- Do NOT generate copy suggestions yourself in this conversation.

The CLI writes batch files numbered `batch-001.txt`, `batch-002.txt`, etc.
Process them STRICTLY ONE AT A TIME. Each batch is a blocking round-trip:

**CHECKPOINT A — Read one file** (use the Read tool directly, not Explore):
```
Read: wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-batch-NNN.txt
```

**CHECKPOINT B — Spawn ONE Agent call** and WAIT for it to return before continuing:
- description: `"Generate replacement copy — batch N of M"`
- model: smallest/fastest model available on the current platform (minimise token cost)
- prompt: the exact file content from Checkpoint A, verbatim — do not shorten

**CHECKPOINT C — Collect and close**: store the JSON array the subagent returns. That agent's session is now complete — do not send any further messages to it.

Only after Checkpoint C is complete, move to Checkpoint A for the next file.
Do not proceed to the next batch until the current Agent call has finished and you have its result.

**After all batches complete:**
- Concatenate all JSON arrays into one combined list.
- Count check: the combined list must have exactly as many entries as the `changes` list in the YAML plan. If the count is off by more than 2, **stop and tell the user** — do not attempt to apply. Ask them to re-run `suggest-creative-copy` and regenerate all batches.
- Pass the verified combined list to Step 3.

## Step 3 — Review and apply

**`suggested_text: null` in the plan YAML is expected at this point.** The CLI populates it during apply — do NOT check for null, do NOT patch the YAML manually. Seeing null is correct; proceed normally. The plan's `current_text` must be populated from the CSV `asset_text` column before batches are generated.

Hosted Bob uses the connected Google OAuth runtime authorization for apply. A manually-created `google-ads-api.yaml` is not required. Bob still requires both Google Ads account authorization and Bob account permission `READ & WRITE`.

Keep the combined JSON from Step 2 internal. Give the user a concise change summary for approval, then write the JSON to a working file (use the Write tool) and run apply:

```bash
# Write combined suggestions to a file first (avoids shell arg-length limits)
# Use the Write tool to write the JSON array to:
#   wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-suggestions.json

./bob creative-copy-apply \
  --plan wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD.yaml \
  --suggestions "$(cat wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-suggestions.json)"
```

The CLI prints a per-asset approval table. Wait for explicit user confirmation ("yes", "apply", "go ahead") before proceeding. The user may type `edit N` to revise individual suggestions at the prompt.

Creative apply is operation-level partial-safe: valid ads go live while ads rejected by local or
Google validation remain pending. Report the exact applied and failed counts and the reason for each
failed proposal. Multiple changes merged into one ad succeed or fail together. The plan records
`apply_status` on every change; never resend a change already marked `applied`.

If a plan is `partial`, generate revised suggestions only for its failed changes, preserving their
original numeric IDs, then call `creative-copy-apply` with only those revised IDs. The approval table
will contain only unapplied changes. Never re-run `creative-copy-apply` on a plan that has
`applied: true`.

## Wiki / Artefact

After `creative-copy-apply` completes:

1. **Clean up working files** — delete all batch and suggestions files for this run:
```bash
rm wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-batch-*.txt
rm wiki/<customer_id>/action-items/creative-copy-YYYY-MM-DD-suggestions.json
```

2. **Update `wiki/<customer_id>/Index.md`** under `## Action Items` without asking. For a partial
apply, state the live and pending counts and do not claim completion. Link a customer-facing CSV only
if the customer requested the complete changes; otherwise use plain text and do not link the internal YAML:
```
- Creative Copy — YYYY-MM-DD — N new assets live, M paused — applied YYYY-MM-DD
```

## Failsafe — Unanswerable Questions

When the question can't be answered from the steps above or any `./bob` subcommand, use the repo failsafe in `AGENTS.md`: answer in Bob's voice (`SOUL.md`) that this isn't something you can do yet, append a `[BUG]`/`[FEATURE]` entry to `logs/backlog.md` (with the user's exact words), log a `failsafe` signal, and confirm to the user.
