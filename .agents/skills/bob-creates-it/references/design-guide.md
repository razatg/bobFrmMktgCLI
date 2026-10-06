# Account Design Guidance

Create account-scoped design guidance before generating static replacements.

## Evidence

1. Use the selected account's latest 15-day creative window by default (or the user's explicit period). Check the data manifest for that account, `creative_image_period`, and exact window before fetching; use one fetched result consistently for performance selection and design evidence. Run `./bob suggest-static-banners --force --input <processed-image-period>` for the selected account.
2. The command selects up to 20 unique `BEST` static assets above the configured impression threshold. When none exist, it may use the eligible `GOOD` fallback and must record that limitation.
3. Inspect every downloaded evidence image with the runtime's visual-input capability. Treat duplicate placements as one visual family.
4. Produce strategist JSON matching the schema in `banner-design-strategist-input.json` and finalize with:

```bash
./bob suggest-static-banners --force --input <processed-image-period> --strategy-json <strategy-json>
```

The final account artifacts are:

- `wiki/{customer_id}/design/DESIGN.md` — observed visual language and prescriptive generation rules.
- `wiki/{customer_id}/design/DESIGN_STRATEGY.md` — evidence, observations, and clearly labelled hypotheses.

Both links must appear in the account `Index.md`. Users may edit both documents in Artifacts; later generation consumes their latest saved text.

## Required quality

- Distinguish visual observation from performance inference.
- Record the source period and inspected assets.
- Cover composition, hierarchy, typography, palette, product treatment, logo treatment, ratio rules, copy density, safe-area guidance, and avoid rules.
- Never infer an advertiser's design language from another account in the same client.
- Do not write final guidance unless at least one evidence image was inspected.
