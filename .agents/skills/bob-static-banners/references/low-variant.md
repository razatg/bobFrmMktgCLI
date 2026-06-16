# LOW Static Variant Workflow

Prepares and generates **preview-only** same-size replacement variants for LOW static image assets. Applying a replacement to Google Ads is a separate approval-gated flow (below).

Use this after the creative-underperformance process has highlighted LOW static image assets. `slice-creatives` remains the source of truth for LOW detection; do not manually filter CSVs in the agent.

## Workflow

1. Prepare LOW static candidates:
   ```bash
   ./bob suggest-static-variants
   ```

   This writes:
   - `wiki/{customer_id}/design/low-static-variants/YYYY-MM-DD/manifest.json`
   - downloaded source images under the same directory when URLs are available

2. Pick the flagged static image candidate the user wants to regenerate. Any LOW static image/banner candidate is eligible, regardless of horizontal, square, vertical, or unknown ratio.

3. Read:
   - candidate row from the manifest
   - `wiki/{customer_id}/design/banner-design.md`
   - linked `wiki/{customer_id}/design/DESIGN.md`

4. Inspect the LOW source image before prompt construction using the agent/runtime's available visual-input capability. In Codex this may be `view_image`; in another runtime it may be an uploaded image, multimodal message, or equivalent vision tool. The source image is the visual reference for product/service category, scene role, proof container, offer or value cue, logo treatment, and other source elements.

5. Ask the user for hard SLA constraints before every regeneration. The question should be concrete and based on the inspected source, for example:
   - logo or brand treatment to preserve
   - product or service category to preserve
   - exact copy or legal text to preserve
   - product, app, landing-page, package, or proof treatment to preserve
   - anything that may be changed freely

6. Build the generation prompt from:
   - source image as a visual reference input
   - LOW campaign and ad group metadata
   - exact native width and height from the source asset
   - inferred creative theme from metadata plus source visual context
   - user-approved hard SLAs
   - soft preservation rules for similar elements by role
   - `DESIGN.md` design-guide rules

7. Generate exactly one replacement variant at the flagged asset's native dimensions. Do not create extra sizes or ratio expansions. If the image model returns the same aspect ratio at a different pixel size, resize the preview output to the exact source dimensions and keep the generated source copy.

8. Run spec-only QA:
   - output file exists
   - image can be read by local tooling
   - final width equals source width
   - final height equals source height
   - output path is recorded
   - no Google Ads upload, pause, or replacement command ran

   Do not run a second subjective visual-inspection QA pass as the acceptance check. Creative quality and brand fidelity are user preview decisions; hard SLA gaps should be documented in the note if visible during generation/review.

9. Write a markdown note beside the output with:
   - source URL and local source path
   - campaign/ad group metadata
   - hard SLAs supplied by the user
   - soft preservation rules
   - exact prompt
   - output paths
   - spec QA result
   - preview-only status

10. Apply only after the user explicitly approves making the preview live. Use the apply flow below; never treat preview generation itself as approval to upload.

## Rules

- Generate only for LOW static `IMAGE` candidates above the configured impression threshold.
- Text assets stay in the creative-copy workflow.
- Video and media bundle assets are review-only for now.
- Never generate from `DESIGN.md` alone; use source image + metadata + hard SLA constraints.
- Never assume horizontal replacement. Replace the flagged banner in its own native dimensions, whatever the ratio.
- Never call a Google Ads mutation command during preview generation.

## Apply Flow

Use only after the user has approved a generated static replacement preview for upload.

Direct single-asset apply:
```bash
./bob static-variants-apply \
  --manifest wiki/{customer_id}/design/low-static-variants/YYYY-MM-DD/manifest.json \
  --asset-id <LOW_ASSET_ID> \
  --replacement <generated-final-png-or-jpg>
```

Batch apply plan:
```yaml
manifest: wiki/{customer_id}/design/low-static-variants/YYYY-MM-DD/manifest.json
changes:
  - asset_id: "<LOW_ASSET_ID>"
    replacement_image: "<generated-final-png-or-jpg>"
    action: replace
applied: false
```

Then:
```bash
./bob static-variants-apply --plan <plan.yaml>
```

Apply behavior:
- validates the replacement file is PNG or JPEG
- validates replacement dimensions match the source asset dimensions when the manifest has width and height
- validates file size is at most 5MB
- shows an approval table and waits for `y`
- uploads the replacement as a new Google Ads image asset
- finds the app ad in the source ad group whose `app_ad.images` contains the LOW source asset
- replaces only that image asset reference with the new image asset reference
- updates the plan in place when `--plan` is used

Apply rules:
- Never run `static-variants-apply` without explicit user approval to make the image live.
- Prefer `--dry-run` first when validating a new plan shape.
- Do not remove the old asset globally; replace only the image reference in the matched app ad.
- If the source image asset is not found in the app ad, stop and report the error rather than uploading another guess.
