# Static image source and generation adapter

Use this adapter after agreeing the account, source scope, creative goal, and review criteria in chat. The same generator handles LOW images, every currently linked image in a campaign, and named image assets. The user does not need to know these route names.

## Select sources

- **LOW performers:** Default to the latest 15 days unless the user specifies another window. Check `data-manifest` for the selected account, `creative_image_period`, and exact dates before fetching. The account's configured impression cutoff is part of this performance query; do not claim to have assessed assets below it. Aggregate that image query for the same window. Use its exact processed file with `./bob suggest-static-variants --selection low --input <processed-image-period>`.
- **Every image in a campaign:** Resolve the exact campaign ID. `creative_image_inventory` is a current-link snapshot with no performance or impression filter. Check today's pull in `data-manifest` before fetching; if absent, fetch it for today's date. Aggregate with `./bob aggregate --grain creative_period --source creative_image_inventory --from <date> --to <date> --customer <id>`. Pass the exact processed CSV path printed by that command to `./bob suggest-static-variants --selection campaign --campaign-id <id> --input <processed-file>`. The aggregate carries source metadata so preparation can validate the data regardless of its directory. Do not use the LOW manifest for this request.
- **Named image assets:** Resolve IDs in the selected account's current image inventory and run `./bob suggest-static-variants --selection assets --asset-ids <comma-separated-ids> --input <processed-inventory>`.

The manifest's selection describes how sources were found; it does not override creative intent. `selection: assets` can represent either explicitly named files or the resolved images from named campaigns/ad groups. When the user asked to refresh/redesign those images, follow the manifest's `generation_route: concept`: group the inspected sources into genuinely coherent creative families and agree one master per family. Do not produce one same-dimension replacement per source. Only `selection: low` may use `generation_route: low_edit`.

The source manifest records the exact selection and downloaded source files. Verify its count and download status before promising full coverage. If a source cannot be retrieved, tell the user which image is missing and continue only with an explicitly agreed smaller scope. One image appearing in several placements is one visual source; retain the placement record for any later apply plan.

Use the manifest path emitted by `suggest-static-variants` directly; do not copy or hand-edit the manifest to work around path checks. Gemini source images may be JPG, PNG, or WebP. The generator detects the MIME from the image bytes and leaves output MIME selection to the configured Gemini model, then validates and stores the result as PNG.

Missing ad placements do not block review-only generation. The generated candidate remains reviewable, while its apply plan must mark publication as blocked until the exact ad group/ad placement is available. Never create a publish change with empty placement IDs.

If the configured Gemini request fails, report its error and stop generation. Do not silently switch to a different image provider.

## LOW edit

Use this only with `selection: low`. Inspect the source and make a controlled, visibly distinct modification while preserving its proposition, approved copy, key subjects, brand treatment, broad composition, and native dimensions. The requested improvement must be obvious at normal feed size; do not accept a pixel-for-pixel restaging or an imperceptible polish. `DESIGN.md` and `DESIGN_STRATEGY.md` may inform the edit but do not block it.

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

- Apply [creative-direction.md](creative-direction.md) before writing the brief. Treat ordinary user creative input as soft direction that may be improved through expert visual and copy judgment. Exact instructions and factual, offer, legal, brand, language, scope, or approval constraints remain hard.
- Classify the creative distance before writing the brief. A LOW edit stays recognisable, a ratio adaptation preserves the approved concept while recomposing it, and a fresh concept uses references for identity and factual grounding while creating a materially new visual structure unless the user explicitly asks for a close adaptation.
- Build each replacement `prompt`, concept `instruction`, or AI-adaptation `instruction` from the minimum sufficient context: the user's outcome and exact required copy; the reference-image roles to retain or change; only the account design rules that directly govern this output's brand treatment, imagery, hierarchy, composition, or ratio; and hard exclusions that prevent a known failure. A detail belongs only when omitting it could materially change the output or permit an incorrect invention.
- In a fresh-concept brief, separate hard constraints from the creative objective, state what each reference contributes, and leave composition, framing, subject arrangement, and reading path open unless the user constrained them. Do not instruct the model to preserve a source composition simply because it was successful or visually strong.
- Use campaign/ad-group context only when it changes the audience, occasion, message, or scene. Use `DESIGN.md` for applicable generation rules and consult `DESIGN_STRATEGY.md` only to resolve evidence, confidence, or ambiguity. Never pass either full document, performance tables, unrelated ratios, historical examples, or workflow prose to the image model.
- Apply context in this priority: hard user constraints and exact approved copy; expert creative interpretation of the user's objective; reference roles explicitly retained or changed; relevant account design guidance; optional campaign/ad-group context. Phrase the result as succinctly as possible without compromising fidelity or creative quality.
- Ask only about a material choice that cannot be resolved from the request, source evidence, or account guidance. Do not impose a fixed upload checklist.
- Request only the agreed concepts, formats, and counts. Do not create extra ratios merely because Google Ads supports them.
- Use adaptation-aware composition as soft guidance: leave useful background flexibility and keep critical elements legible, but do not force the model into a rigid central safe-area box.
- Treat every generated file as review-only. If a required element cannot be generated faithfully, report the failure instead of silently replacing or inventing it.
- Visually inspect every output against the source, brief, and design guidance. Technical file validation does not establish creative quality or likely performance.

Write each temporary confirmed brief to `.bob/creative-briefs/<run-id>-<stage>.json`, creating the directory when needed. This resolves into the conversation's private state in hosted Bob. Do not put the input brief under `wiki/`: the account wiki is shared artifact storage and is intentionally not trusted as an executable brief source. Source manifests may remain in their account-scoped wiki location.

Create the task's run once with `./bob create-static-replacements --manifest <source-manifest> --brief .bob/creative-briefs/<run-id>-<stage>.json --run-id <run-id> --new-run`. Every later stage, feedback edit, regeneration, or retry for that task must call the same command with the same `--run-id` and without `--new-run`. The command rejects accidental creation and accidental replacement of a run. Start another run only when the user explicitly asks for a separate task, concept, or artifact. Omit `model` to use the catalog default; use the approved Pro model only when the brief needs it. Gemini creates review-only PNGs using the client's key; the generator checks integrity, size, dimensions, and duplicates. Visual inspection is the next part of the same request: do not wait for the user to ask for it or ask them to trigger it. A weak result can be regenerated in the same run as `v2`, `v3`, etc. Do not describe technical QA as proof that the creative will perform better.

Before presenting a run, inspect every pending output and write one private review JSON covering exactly these checks: `brief_fidelity`, `copy_accuracy`, `brand_fidelity`, `creative_transformation`, `composition`, `visual_integrity`, and `design_guidance`. Interpret `creative_transformation` by route: a LOW edit remains recognisable but the requested improvement is readily noticeable beside the source at normal feed size; an adaptation preserves the approved idea while fitting the new ratio; a fresh concept is not a reskin and has a materially new focal structure and reading path. Fail a LOW output that merely restages the source or changes details too subtly to notice without close inspection. Fail a fresh concept when it largely repeats the source layout, subject arrangement, framing, copy panel, offer stack, or reading order without an explicit user request to do so. Each value is `passed` or `failed`; a failed output needs at least one concise issue, while a passed output has no unresolved issues. Submit the batch with `./bob create-static-replacements --run-id <run-id> --visual-review <review.json>`. The command rejects incomplete reviews, keeps failed versions out of the review artifact, and blocks adaptation or publishing until visual review passes.

```json
{"reviews":[{"name":"master-concept-v1.png","checks":{"brief_fidelity":"passed","copy_accuracy":"passed","brand_fidelity":"passed","creative_transformation":"passed","composition":"passed","visual_integrity":"passed","design_guidance":"passed"},"issues":[]}]}
```

## Publish after a separate request

“Make all live” means the pending outputs in the latest run Bob presented for the selected account. A named instruction applies only that candidate. Use the run's apply plan and the existing `static-variants-apply` validation and approval gate. Confirm that every requested placement is represented before applying; if coverage is incomplete, stop and report the missing placements. Generation, viewing, and editing design guidance are not publication approval.

## User-facing artifacts

Link one `creative-runs/{run-id}/index.md` artifact from the account index. That run page presents the selected source previews and current LOW replacements, masters, or adaptations as a gallery. Each output must identify its production method and link to its detail page. The detail page contains the sanitized Gemini request, including the text prompt, for AI generation; for deterministic adaptation it names the tool/script and states that no AI prompt was used. Output images remain directly retrievable from the run page but do not appear as separate entries in Artifact navigation. Keep briefs, source manifests, provider responses, and apply plans internal.

For the hosted reply, copy the generator's final `[[artifact:wiki/...|Open the full creative review]]` marker exactly as plain text. Do not place it inside `[label](...)`, do not emit `[[ARTIFACT: ...]]`, and do not add separate chat markers for each image.
