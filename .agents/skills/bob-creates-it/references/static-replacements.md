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

## Design and generate

Read the account's editable `DESIGN.md` and `DESIGN_STRATEGY.md`. If either is missing or the evidence is stale, use [design-guide.md](design-guide.md). Codex inspects each selected source image and proposes a specific edit. Once the user agrees to the method, save a confirmed internal brief inside Bob's state root:

```json
{
  "customer_id": "1234567890",
  "selection": "campaign",
  "model": "gemini-3.1-flash-image",
  "goal": "Refresh the selected campaign images with clearer visual hierarchy",
  "confirmed": true,
  "replacements": [
    {"asset_id": "123", "prompt": "Keep the product and required brand elements; simplify the headline area."}
  ]
}
```

Generate at most 20 sources per call with `./bob create-static-replacements --manifest <source-manifest> --brief <brief.json> --run-id <run-id>`. Omit `model` in the brief to use the catalog default; use the approved Pro model only for a brief that needs its strengths. For a larger agreed scope, use several calls with the same source manifest and run ID. Gemini creates review-only PNGs using the client's key; the generator checks integrity, size, dimensions, and duplicates. Codex must then visually inspect the outputs against the agreed brief. A weak result can be regenerated in the same run as `v2`, `v3`, etc. Do not describe technical QA as proof that the creative will perform better.

## Publish after a separate request

“Make all live” means the pending outputs in the latest run Bob presented for the selected account. A named instruction applies only that candidate. Use the run's apply plan and the existing `static-variants-apply` validation and approval gate. Confirm that every requested placement is represented before applying; if coverage is incomplete, stop and report the missing placements. Generation, viewing, and editing design guidance are not publication approval.

## User-facing artifacts

Show generated files in `creative-runs/{run-id}/outputs/` and the account's editable design guidance when relevant. Keep briefs, source manifests, references, provider responses, and apply plans internal.
