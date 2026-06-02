---
name: bob-static-banners
description: Use when creating or refreshing the quarterly static banner design guide from best-performing Google Ads image assets.
---

# Bob Static Banners Skill

Use this skill when the user asks for a static ads studio, static banner guide, banner design playbook, or fresh static creative direction.

## Scope

V2 creates a split output:
- `banner-design-strategy.md` for evidence and reasoning
- `DESIGN.md` for the reusable generation spec
- `banner-design.md` as a short landing page that links to both

It does not generate images, upload assets, pause assets, or mutate Google Ads.

## Workflow

1. Prepare image evidence:
   ```bash
   ./bob suggest-static-banners --force
   ```

   This writes a strategist packet and an asset manifest. It does not write the final guide.

2. The prepare command writes:
   - `wiki/{customer_id}/design/banner-design-strategist-input.json`
   - `wiki/{customer_id}/design/static-banner-assets/YYYY-MM-DD/manifest.json`
   - downloaded image files under the same `static-banner-assets/YYYY-MM-DD/` directory when URLs are available

3. If the CLI says image URLs are missing, refetch `creative_period` with the updated query, aggregate it, and rerun prepare. Do not create the final guide from metrics alone.

4. Spawn the custom subagent in `.codex/agents/static-banner-strategist.toml` with:
   - the strategist input JSON
   - each downloaded image as an image input where available
   - source URLs only for assets that failed local download

   The subagent must inspect actual creative images, treat repeated placements as one unique visual family, and return JSON only.

5. Save the subagent response to:
   `wiki/{customer_id}/design/banner-design-strategy.json`

6. Finalize the guide:
   ```bash
   ./bob suggest-static-banners --force --strategy-json wiki/{customer_id}/design/banner-design-strategy.json
   ```

   This writes:
   - `wiki/{customer_id}/design/banner-design-strategy.md`
   - `wiki/{customer_id}/design/DESIGN.md`
   - `wiki/{customer_id}/design/banner-design.md`

## Rules

- Use `performance_label=BEST` static image assets as primary references.
- If BEST assets are unavailable, GOOD assets may be used only as secondary fallback context.
- Deduplicate repeated creatives before strategy so each unique visual is inspected once and duplicate placements are kept only as supporting evidence.
- Keep the skill generic, but generated artifacts advertiser-specific by default: when creatives are inspected, derive the advertiser's visible brand system, product styling, and recurring design tokens into the output files.
- Treat the guide as valid for 90 days.
- Future generation requires campaign, ad group, and a user brief. Never generate banners from the guide alone.
- Future generation is conditional: start from the guide and brief, then explicitly state any element the model cannot faithfully reproduce instead of assuming a fixed upload bundle.
- Do not call any Google Ads mutation command.
- Do not write the final strategy guide or `DESIGN.md` unless the strategist inspected at least one image.
- `--data-only-diagnostic` is allowed only for debugging missing image URLs and must not be treated as a design guide.

## Output

`banner-design-strategy.md` must include:

- Google image specs for horizontal, vertical, and square.
- Winner references grouped by ratio.
- Campaign/ad group context and metrics.
- Image URLs and dimensions where available.
- Per-creative visual observations from the strategist.
- Duplicate placement evidence kept separate from unique creative observations.
- Cross-creative “what is working” patterns from actual inspected banners.
- A short note linking to `DESIGN.md` for future generation use.

`DESIGN.md` must include:

- An advertiser-specific design-system style spec, not performance tables.
- Advertiser-specific brand tokens and signals derived from reviewed creatives first, then refined by any supplied brand assets if available.
- Prescriptive visual-language rules derived from the inspected creatives.
- Composition, hierarchy, component, imagery, and ratio guidance.
- Content and CTA rules.
- Do's and don'ts.
- A conditional fidelity rule: if a required element cannot be faithfully generated, the model must say exactly what is missing.
