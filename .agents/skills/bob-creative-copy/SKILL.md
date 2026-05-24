---
name: bob-creative-copy
description: Use when the user asks to review or replace LOW-performing text asset copy in Google App Campaigns.
---

# Bob Creative Copy Skill

Use this skill when the user asks about reviewing, rewriting, or replacing creative copy for LOW-labeled text assets.

## Personality

Read `SOUL.md` before answering. Every response must sound like Bob wrote it.

## Operating Rules

- **Do not read or modify source files.** Agent scope: run CLI tools, read data files, write to `wiki/` only.
- **Check before fetching.** Use `ls` to verify raw and processed files cover the date window before fetching.
- **Always pass `--reason` when calling `fetch`.** Log what triggered the pull.
- **Never call `creative-copy-apply` without explicit user approval** at the approval table.
- Never generate copy suggestions yourself inline. The subagent in Step 2 does this — always.

## Step 1 — Generate the candidate list

```bash
# Check processed creative data exists
ls data/processed/creative/

# If missing or older than 7 days, re-fetch:
python3 lib/datapull.py fetch --query creative_period --days 30 --reason "creative copy plan"
python3 lib/datapull.py aggregate --grain creative_period

# Generate YAML plan + batch prompt files
python3 lib/datapull.py suggest-creative-copy
# Outputs:
#   wiki/action-items/creative-copy-YYYY-MM-DD.yaml           — per-asset plan
#   wiki/action-items/creative-copy-YYYY-MM-DD-batch-001.txt  — assets 1–25
#   wiki/action-items/creative-copy-YYYY-MM-DD-batch-002.txt  — assets 26–50
#   ... (one file per 25 assets)
```

If `suggest-creative-copy` outputs "0 assets" there are no LOW-action TEXT assets — tell the user and stop.

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
Read: wiki/action-items/creative-copy-YYYY-MM-DD-batch-NNN.txt
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

**`suggested_text: null` in the plan YAML is expected at this point.** The CLI populates it during apply — do NOT check for null, do NOT patch the YAML manually. Seeing null is correct; proceed normally.

Show the user the combined JSON from Step 2. Then write it to a file (use the Write tool) and run apply:

```bash
# Write combined suggestions to a file first (avoids shell arg-length limits)
# Use the Write tool to write the JSON array to:
#   wiki/action-items/creative-copy-YYYY-MM-DD-suggestions.json

python3 lib/datapull.py creative-copy-apply \
  --plan wiki/action-items/creative-copy-YYYY-MM-DD.yaml \
  --suggestions "$(cat wiki/action-items/creative-copy-YYYY-MM-DD-suggestions.json)"
```

The CLI prints a per-asset approval table. Wait for explicit user confirmation ("yes", "apply", "go ahead") before proceeding. The user may type `edit N` to revise individual suggestions at the prompt.

Never re-run `creative-copy-apply` on a plan that has `applied: true`.

## Wiki / Artefact

After `creative-copy-apply` completes:

1. **Clean up working files** — delete all batch and suggestions files for this run:
```bash
rm wiki/action-items/creative-copy-YYYY-MM-DD-batch-*.txt
rm wiki/action-items/creative-copy-YYYY-MM-DD-suggestions.json
```

2. **Update `wiki/Index.md`** under `## Action Items` without asking:
```
- [Creative Copy — YYYY-MM-DD](action-items/creative-copy-YYYY-MM-DD.yaml) — N new assets live, M paused — applied YYYY-MM-DD
```

## Failsafe — Unanswerable Questions

If the question cannot be answered using the CLI tools above:

1. **Respond in Bob's voice** following `SOUL.md` — honest, direct, Australian. Tell the user this isn't something you can do yet and to check back in a few days. One or two sentences, no corporate hedging.
2. **Append to `logs/backlog.md`** under `## Bug Reports` or `## Feature Requests`:
   ```markdown
   ### [BUG or FEATURE] YYYY-MM-DD — <short title>
   **User said:** "<exact user input>"
   **What happened:** <what Bob did or couldn't do>
   **What's needed:** <fix or feature description>
   ```
   Use **BUG** when Bob routed or responded incorrectly. Use **FEATURE** when the capability is genuinely missing.
3. Confirm to the user it was saved to `logs/backlog.md`.
