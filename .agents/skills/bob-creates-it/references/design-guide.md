# Account Design Guidance

Use this procedure when `DESIGN.md` or `DESIGN_STRATEGY.md` is missing or stale. The result must be account-specific guidance grounded in inspected images, not a generic banner template.

## Prepare the evidence

1. Use the selected account's latest 15-day creative window by default, or the user's explicit period.
2. Check `data-manifest` for the exact account, `creative_image_period` query, and window before fetching. Use one fetched result consistently for performance selection and design evidence.
3. Run `./bob suggest-static-banners --force --input <processed-image-period>`. It selects up to 20 unique eligible `BEST` static assets above the configured impression threshold. When none exist it may use `GOOD`, but the final strategy must state that limitation.
4. Open `banner-design-strategist-input.json`. Inspect every asset whose `download_status` is `downloaded`; do not infer visual properties from its filename, campaign name, metrics, or URL. Treat repeated placements of the same source image as one visual family.

The command's metrics determine which images are evidence. They do not prove why an image performed well.

## Inspect each image

Create one `creative_observations` entry per downloaded asset. Use the exact `asset_id` from the strategist input and record:

- `asset_id`: exact source identifier.
- `visual_description`: literal description of the visible scene and major elements.
- `composition`: framing, focal point, balance, reading path, text zone, foreground/background separation, and use of whitespace.
- `hierarchy`: the order in which claim, proof, product, offer, branding, and action are perceived.
- `typography`: observable type style, weight, scale, casing, contrast, alignment, and role. Do not claim an exact font family unless it is independently known.
- `palette`: dominant, secondary, accent, background, text, and contrast behaviour. Use approximate colour values only when visually supportable.
- `product_treatment`: how the product, service, device, person, or use-case proof is shown.
- `logo_treatment`: placement, scale, clear space, background treatment, and consistency. State `not visible` when appropriate.
- `copy_density`: visible text volume, number of claims, headline length, supporting copy, offer text, and CTA text.
- `safe_area`: margins and regions that remain readable or visually stable when adapted.
- `ratio_adaptation`: what the composition suggests for its current ratio; do not invent rules for unobserved ratios.
- `message_cta`: literal visible message and CTA roles without treating them as causal performance findings.
- `evidence_note`: why this observation is reusable, or why it may be a one-off. Label any performance explanation as a hypothesis.

Observations describe what is visible. Statements such as “this layout won because…” are hypotheses unless the available evidence isolates that variable.

## Synthesize across the evidence

After the per-image pass, compare the visual families. A design rule should normally be supported by more than one inspected family. A useful exception may be retained when it is clearly labelled as limited evidence.

Produce these top-level fields:

- `status`: use `complete` only after all downloaded images were inspected.
- `image_inspected_count`: number of unique downloaded images actually inspected.
- `raw_asset_count` and `unique_image_count`: copy from the strategist input.
- `creative_observations`: the per-image records above.
- `duplicate_groups`: copy the supplied placement evidence; do not treat repeated placement as a new visual.
- `winning_patterns`: recurring visible patterns, each stating its supporting assets or prevalence and avoiding causal claims.
- `visual_language`: generation-ready statements describing the account's recurring visual grammar.
- `brand_colors`: observed colour roles. Each value should include the observed value or description plus confidence/evidence.
- `typography_signals`: observed typographic roles and confidence; use descriptive characteristics when the exact font is unknown.
- `component_patterns`: recurring components such as product frames, price cards, badges, illustration devices, photography treatments, or CTA containers.
- `brand_signals`: recurring logo, product, shape, illustration, photography, and other recognisable brand treatments.
- `token_confidence_notes`: what is directly observed, what is approximate, and what requires approved brand documentation.
- `composition_rules`: account-specific rules for framing, focal point, reading path, whitespace, and foreground/background separation.
- `imagery_rules`: account-specific subject, scene, product, human, illustration, or photography treatment.
- `ratio_rules`: rules only for ratios represented in the evidence, keyed by `horizontal`, `square`, or `vertical`.
- `message_hierarchy`: recurring order and visual weight of claim, proof, product, branding, offer, and action.
- `copy_density_rules`: observed limits and patterns for claims, headline length, supporting text, offers, and CTA copy.
- `safe_area_guidance`: evidence-backed margin, cropping, text-zone, logo-zone, and adaptation guidance.
- `cta_rules`: observed CTA presence, wording role, prominence, and container treatment.
- `brand_and_product_rules`: how branding and the product/service proof coexist.
- `visual_style`: account-specific treatment of contrast, depth, shape, photography, illustration, texture, and motion cues.
- `avoid`: contradictions, failure patterns, or unsupported treatments that should not be introduced.
- `future_generation_contract_notes`: the account-specific rules a later generation brief would otherwise miss: how to turn audience, occasion, use case, and optional campaign/ad-group context into a theme; which reference-image roles must be preserved; user requirements > source fidelity > design preferences; fidelity limits that must not be guessed; and unresolved constraints. Include only rules supported by the inspected account evidence.

Do not put these fields under an `observations` wrapper. The finalizer consumes them as top-level keys.

## Required JSON shape

```json
{
  "status": "complete",
  "image_inspected_count": 2,
  "raw_asset_count": 3,
  "unique_image_count": 2,
  "creative_observations": [
    {
      "asset_id": "123",
      "visual_description": "Literal visual description",
      "composition": "Observed layout and reading path",
      "hierarchy": "Observed information order",
      "typography": "Observed type treatment and confidence",
      "palette": "Observed colour roles and contrast",
      "product_treatment": "Observed product or service proof",
      "logo_treatment": "Observed logo treatment or not visible",
      "copy_density": "Observed copy volume and roles",
      "safe_area": "Observed stable margins and text zones",
      "ratio_adaptation": "Evidence-backed ratio observation",
      "message_cta": "Observed message and CTA roles",
      "evidence_note": "Reusable pattern or clearly labelled hypothesis"
    }
  ],
  "duplicate_groups": [],
  "winning_patterns": ["Pattern with evidence scope"],
  "visual_language": ["Generation-ready account rule"],
  "brand_colors": {"primary": {"value": "observed value", "confidence": "high", "note": "evidence"}},
  "typography_signals": {"headline": {"fontWeight": "bold", "note": "observed across named assets"}},
  "component_patterns": ["Recurring component"],
  "brand_signals": ["Recurring brand treatment"],
  "token_confidence_notes": ["Confidence boundary"],
  "composition_rules": ["Account-specific composition rule"],
  "imagery_rules": ["Account-specific imagery rule"],
  "ratio_rules": {"square": "Observed square-layout rule"},
  "message_hierarchy": ["Observed hierarchy rule"],
  "copy_density_rules": ["Observed copy-density rule"],
  "safe_area_guidance": ["Observed safe-area rule"],
  "cta_rules": ["Observed CTA rule"],
  "brand_and_product_rules": ["Observed brand/product rule"],
  "visual_style": ["Observed visual-style rule"],
  "avoid": ["Evidence-backed or explicitly precautionary avoid rule"],
  "future_generation_contract_notes": ["Account-specific unresolved constraint"]
}
```

The example demonstrates structure only. Never copy its placeholder content into an account strategy.

## Quality gate

Before finalizing, verify that:

- every downloaded asset has exactly one observation with its exact `asset_id`;
- every required top-level field is present and non-empty;
- observations and hypotheses are distinguishable;
- exact brand tokens are not claimed from uncertain visual evidence;
- ratio guidance is limited to inspected evidence;
- the documents contain no other advertiser's design language;
- the resulting rules are specific enough to change a generation prompt;
- `DESIGN.md` gives a later agent enough account-specific guidance to control content density, theme selection, reference fidelity, constraint priority, and avoid rules without reopening the evidence images; where the evidence cannot support one of those areas, the limitation is stated instead of filled with boilerplate;
- limitations and unresolved choices are explicit rather than filled with generic advice.

Finalize with:

```bash
./bob suggest-static-banners --force --input <processed-image-period> --strategy-json <strategy-json>
```

The final account artifacts are:

- `wiki/{customer_id}/design/DESIGN_STRATEGY.md`: evidence, per-image observations, synthesis, hypotheses, confidence, and limitations.
- `wiki/{customer_id}/design/DESIGN.md`: only the account-specific, generation-ready rules distilled from that strategy.

Both links must appear in the account `Index.md`. Users may edit both documents in Artifacts; later generation consumes their latest saved text.
