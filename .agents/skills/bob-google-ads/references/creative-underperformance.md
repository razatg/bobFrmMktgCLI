# Creative Underperformance

Use for questions asking which creatives are underperforming after enough delivery.

## Intent

`creative_underperformance`

## Required Inputs

- `.bob/profile.json`
- `creative_period` processed slice (impression-filtered, 30-day window)

## CLI Commands

**Step 1 — Aggregate creative data (bootstrap fetches this; re-run if >7 days old):**
```bash
python3 lib/datapull.py aggregate --grain creative_period
# Output: data/processed/creative/<account>_<start>_<end>.csv
```

If bootstrap data is stale:
```bash
python3 lib/datapull.py fetch --query creative_period --days 30 --reason "creative underperformance review"
python3 lib/datapull.py aggregate --grain creative_period
```

**Step 2 — Run the underperformance slicer:**
```bash
python3 lib/datapull.py slice-creatives
# Output: printed table + pattern analysis
# Optional: --output FILE to save full flagged CSV
```

Do not filter the CSV manually or use pandas/grep to find LOW rows. `slice-creatives` does all filtering.

**Step 3 (optional) — Generate copy plan + agent prompt:**
```bash
python3 lib/datapull.py suggest-creative-copy
# Output:
#   wiki/action-items/creative-copy-YYYY-MM-DD.yaml    — plan with BEST examples + LOW-action candidates
#   wiki/action-items/creative-copy-YYYY-MM-DD-prompt.txt  — compact prompt for any agent (Codex, Claude, GPT)
```

See `references/creative-copy-suggest.md` for the full workflow.

**Step 4 (after agent fills suggestions and user approves) — Apply:**
```bash
python3 lib/datapull.py creative-copy-apply \
  --plan wiki/action-items/creative-copy-YYYY-MM-DD.yaml \
  --suggestions '[{"id":1,"text":"..."},...]'
# CLI shows approval table; user confirms y/n before anything is pushed to Google Ads
```

Never call `creative-copy-apply` without explicit user approval at the interactive prompt.

## What `slice-creatives` Does

1. Filters to `performance_label = LOW` AND `impressions ≥ creative_min_impressions` (profile default: 50,000). BEST, GOOD, LEARNING, and blank labels are excluded.
2. Computes campaign-level aggregate metrics (CTR%, CTI%, CPC) from all eligible creatives in the same campaign.
3. Flags each LOW creative:
   - **low-action** — 2 or more of: CTR% below 90% of campaign avg, CTI% below 90% of campaign avg, CPC above 110% of campaign avg. These need a decision (pause or replace).
   - **low-watch** — only 1 metric worse. Monitor for another week.
4. Pattern analysis on low-action set: asset type breakdown, field type breakdown, common name/ad-group tokens.

## How Bob Presents Results

Lead with the headline count, then the pattern finding, then the per-asset table.

**Example:**
> 166 Low-Action assets out of 504 LOW-label creatives. The pattern is clear — English-language TEXT ads in Bike campaigns are the main drag. HEADLINE and DESCRIPTION copy in ATL-Breakup and Generic-Cricket ad groups is underperforming on CTR and CTI against their campaign benchmarks. Here's what to act on:

Then show the low-action table from the CLI output.

## Suggested Actions

- **pause**: low-action asset — stop serving, review copy
- **replace**: pause candidate — suggest uploading a new variant in the same field_type
- **observe**: low-watch — monitor for one more week before acting

## Wiki / Artefact

After user confirms there are actionable findings, offer:

```
Save creative report to wiki? → wiki/analyses/creative-underperformance-<YYYY-MM-DD>.md
```

**Write the file directly from the output already printed in this conversation.** Do NOT re-run `slice-creatives`. Do NOT run `--output`. Do NOT read any CSV file. All numbers (counts, tables, patterns) are already on screen — copy them into the template below.

**Include every row of every table — no truncation.** The chat response may show 10 rows to avoid scroll; the wiki file must include all of them. A partial table makes the report unactionable.

After writing, add one line to `wiki/Index.md` under `## Analyses`:
```
- [Creative Underperformance — YYYY-MM-DD](analyses/creative-underperformance-YYYY-MM-DD.md) — <N> low-action (<pattern headline, e.g. "English TEXT, Bike campaigns">)
```

File structure:

```markdown
---
date: <YYYY-MM-DD>
intent: creative_underperformance
period: <start>–<end>
min_impressions: <creative_min_impressions from profile>
---

← [Wiki Index](../Index.md)

# Creative Underperformance Report: <YYYY-MM-DD>

## Summary
- **Total LOW (≥<min_imp> impressions):** <N>
- **Low-Action (2+ metrics worse):** <N text> + <N video/image>
- **Low-Watch (1 metric worse):** <N>

## Patterns
- Asset types: <from CLI "[Patterns]" line>
- Field types: <from CLI "[Patterns]" line>
- Common terms: <from CLI "[Patterns]" line>
- Top ad groups: <from CLI "[Patterns]" list>

## Low-Action Assets

### TEXT

| Asset | Field | CTR% | TypeAvg | CTI% | TypeAvg | CPC | TypeAvg |
|---|---|---|---|---|---|---|---|
<rows from TEXT LOW-ACTION table>

### VIDEO / IMAGE

| Asset name/ID | Type | CTR% | TypeAvg | CTI% | TypeAvg | CPC | TypeAvg |
|---|---|---|---|---|---|---|---|
<rows from VIDEO / IMAGE LOW table>

## Low-Watch (monitor 1 more week)
<top 10 from CLI output>

## Actions

### Pause / Replace
- <asset IDs/names with field_type from Low-Action table>

### Observe Next Week
- <Low-Watch assets>
```
