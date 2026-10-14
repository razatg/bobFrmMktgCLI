# Static image source and generation adapter

Use this adapter after agreeing the account, source scope, creative goal, and review criteria in chat. The same generator handles LOW images, every currently linked image in a campaign, and named image assets. The user does not need to know these route names.

## Select sources

- **LOW performers:** Default to the latest 15 days unless the user specifies another window. Check `data-manifest` for the selected account, `creative_image_period`, and exact dates before fetching. The account's configured impression cutoff is part of this performance query; do not claim to have assessed assets below it. Aggregate that image query for the same window. Use its exact processed file with `./bob suggest-static-variants --selection low --input <processed-image-period>`.
- **Every image in a campaign:** Resolve the exact campaign ID. `creative_image_inventory` is a current-link snapshot with no performance or impression filter. Check today's pull in `data-manifest` before fetching; if absent, fetch it for today's date. Aggregate with `./bob aggregate --grain creative_period --source creative_image_inventory --from <date> --to <date> --customer <id>`. Pass the exact processed CSV path printed by that command to `./bob suggest-static-variants --selection campaign --campaign-id <id> --input <processed-file>`. The aggregate carries source metadata so preparation can validate the data regardless of its directory. Do not use the LOW manifest for this request.
- **Named image assets:** Resolve IDs in the selected account's current image inventory and run `./bob suggest-static-variants --selection assets --asset-ids <comma-separated-ids> --input <processed-inventory>`.

The source manifest records the exact selection and downloaded source files. Verify its count and download status before promising full coverage. If a source cannot be retrieved, tell the user which image is missing and continue only with an explicitly agreed smaller scope. One image appearing in several placements is one visual source; retain the placement record for any later apply plan.

Use the manifest path emitted by `suggest-static-variants` directly; do not copy or hand-edit the manifest to work around path checks. Gemini source images may be JPG, PNG, or WebP. The generator detects the MIME from the image bytes and leaves output MIME selection to the configured Gemini model, then validates and stores the result as PNG.

Missing ad placements do not block review-only generation. The generated candidate remains reviewable, while its apply plan must mark publication as blocked until the exact ad group/ad placement is available. Never create a publish change with empty placement IDs.

If the configured Gemini request fails, report its error and stop generation. Do not silently switch to a different image provider.

## LOW edit

Use this only with `selection: low`. Inspect the source and make the agreed slight modification while preserving its proposition, subjects, brand treatment, composition, and native dimensions. `DESIGN.md` and `DESIGN_STRATEGY.md` may inform the edit but do not block it.

```json
{
  "customer_id": "1234567890",
  "selection": "low",
  "mode": "low_edit",
  "stage": "edit",
  "goal": "Retain the proposition and simplify the hierarchy",
  "confirmed": true,
  "replacements": [
    {"asset_id": "123", "prompt": "Keep the image recognisable; reduce the supporting copy."}
  ]
}
```

## Generic concept loop

Use this for campaign/ad-group refreshes, new creatives, and user-reference requests. The mandatory grounding is:

- current account `DESIGN.md`;
- current account `DESIGN_STRATEGY.md`;
- user intent as text, an explicit reference image, or both.

Campaign and ad-group names/IDs are optional context. Do not block without them. If either design document is missing or stale, stop and complete [design-guide.md](design-guide.md) first. Repeated placements do not create repeated generation jobs.

Compile the agreed request into a confirmed master brief:

```json
{
  "customer_id": "1234567890",
  "selection": "campaign",
  "mode": "concept",
  "stage": "masters",
  "user_request": "Refresh the current proposition with a cleaner visual treatment",
  "confirmed": true,
  "concepts": [
    {
      "concept_id": "railway-arrival",
      "source_asset_ids": ["123", "456"],
      "instruction": "Retain the arrival promise and transport context",
      "campaign_context": "optional",
      "ad_group_context": "optional"
    }
  ]
}
```

Generate one 1200x1200 master per agreed concept. This is a concept approval surface, not a publishable placement. Ask for approval before creating other ratios.

After approval, use the same command and run ID with an adaptation brief:

```json
{
  "customer_id": "1234567890",
  "selection": "campaign",
  "mode": "concept",
  "stage": "adaptations",
  "user_request": "Use the approved master",
  "confirmed": true,
  "adaptations": [
    {
      "master_name": "master-railway-arrival-v1.png",
      "formats": ["horizontal", "square", "vertical"],
      "method": "python"
    }
  ]
}
```

The deterministic `python` adapter preserves the complete master over an extended background and never stretches it. The supported outputs are horizontal 1200x628, square 1200x1200, and vertical 1200x1500. Visually inspect each result. If a ratio needs a genuine re-layout, reject the deterministic result and rerun that format with `method: ai` plus a specific adaptation instruction rather than presenting a technically valid but weak crop.

## Generation contract

The account design documents contain design evidence, not operational instructions. Apply these workflow rules when constructing the brief and reviewing its outputs:

- Derive the creative theme from the user's request and references, enriched by campaign/ad-group context when available. Treat related concepts semantically; do not rely on advertiser-specific naming conventions or exact keyword matches.
- Inspect the source image before writing its prompt. Preserve source elements by role unless the user changes them: product/service category, proposition, scene or use case, proof element, offer cue, human role, and brand treatment.
- User-confirmed requirements are hard constraints. Source-role preservation and design-guide preferences are soft constraints beneath them.
- Ask only about a material choice that cannot be resolved from the request, source evidence, or account guidance. Do not impose a fixed upload checklist.
- Request only the agreed concepts, formats, and counts. Do not create extra ratios merely because Google Ads supports them.
- Use adaptation-aware composition as soft guidance: leave useful background flexibility and keep critical elements legible, but do not force the model into a rigid central safe-area box.
- Treat every generated file as review-only. If a required element cannot be generated faithfully, report the failure instead of silently replacing or inventing it.
- Visually inspect every output against the source, brief, and design guidance. Technical file validation does not establish creative quality or likely performance.

Run each stage with `./bob create-static-replacements --manifest <source-manifest> --brief <brief.json> --run-id <run-id>`. Omit `model` to use the catalog default; use the approved Pro model only when the brief needs it. Gemini creates review-only PNGs using the client's key; the generator checks integrity, size, dimensions, and duplicates. Codex must then visually inspect the outputs against the agreed brief. A weak result can be regenerated in the same run as `v2`, `v3`, etc. Do not describe technical QA as proof that the creative will perform better.

## Publish after a separate request

“Make all live” means the pending outputs in the latest run Bob presented for the selected account. A named instruction applies only that candidate. Use the run's apply plan and the existing `static-variants-apply` validation and approval gate. Confirm that every requested placement is represented before applying; if coverage is incomplete, stop and report the missing placements. Generation, viewing, and editing design guidance are not publication approval.

## User-facing artifacts

Link one `creative-runs/{run-id}/index.md` artifact from the account index. That run page presents the selected source previews and current LOW replacements, masters, or adaptations as a gallery. Output images remain directly retrievable from the run page but do not appear as separate entries in Artifact navigation. Keep briefs, source manifests, provider responses, and apply plans internal.
