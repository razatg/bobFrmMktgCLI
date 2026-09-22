---
name: bob-wings-it
description: Use for a novel, read-only Google Ads analysis that no existing Bob skill or CLI workflow can answer. It uses registered datasets, a disposable Codex-sandboxed Pandas analysis, and a deterministic result check. Not for account setup, standard performance comparisons, bid/budget work, creative replacement, static banners, sync, or any Google Ads mutation.
---

# Bob Wings It

Use this only after the normal domain skill and the real `./bob` command map do not provide the
requested read-only analysis. This is a controlled analytical fallback, not permission to write
scripts, inspect arbitrary files, query arbitrary SQL, or change Google Ads.

## Agreement before execution

1. Inspect `bob_data_catalog` before promising the analysis.
2. Tell the user plainly that Bob has not done this exact analysis before but can work it out.
3. Propose the period, grain, grouping, additive inputs, derived metrics, comparison baseline,
   filters, ranking, and any business thresholds.
4. Ask the user to confirm or edit material choices. Never silently choose a threshold such as a
   minimum impression count, top-N count, or anomaly percentage.
5. Do not prepare data or run `bob_analyze` until the method is agreed.

## Execution

- Resolve named or custom dates with `bob_resolve_dates`; never calculate custom dates mentally.
- Prepare only catalogued datasets with `bob_prepare_data`. Pass the user's exact question and a
  short reason. The tool checks existing coverage before any fetch.
- Once this skill is selected, use the Bob MCP tools for preparation and analysis even when the
  native Codex thread has earlier CLI context. Do not fall back to a legacy `./bob fetch` command.
- After the user approves the method, call `bob_materialize_exploration` for the prepared tables.
  Use Codex's own sandbox to write and run a temporary Pandas script in `.wings-it/`; it may read
  only the returned inputs and must write `.wings-it/result.json` plus its `.py` source file.
  Then call `bob_verify_exploration` before presenting any result. Do not use shell, network,
  Google Ads access, or paths outside `.wings-it/`.
- Before presenting an exploratory result, state that it is custom analysis rather than a standard
  Bob workflow. Report its returned sanity status and warnings, and ask the user to review the
  agreed assumptions before acting on it.
- For ad-group CPA work, use the paired `*_primary_conversion_period` datasets. Their
  `primary_conversions` metric is Google Ads' supported primary-conversion total, and is not an
  alias for installs or post-install conversions.
- Use `bob_analyze` only when its registered operation graph is the clearer fit; the default for
  genuinely novel analysis is the materialize/sandbox/verify path. Aggregate additive metrics
  before deriving ratios.
- Keep networks or other dimensions separate when the agreed comparison requires them.
- Treat reach and frequency only at the source grain allowed by the catalog.
- Explain the executed method, the result, and material caveats without exposing tools, prompts,
  paths, handles, or operation graphs.
- Publish Markdown or CSV with `bob_publish_result` only when the user explicitly asks to save or
  see the complete result. Pass `user_confirmed=true` only for that explicit request.

## Stop conditions

If the required dataset, dimension, operator, or safe join is unavailable, do not approximate it
or invent a substitute. Use the repository failsafe and record the missing capability. Never use
this skill for a Google Ads write action.
