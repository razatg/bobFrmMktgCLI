---
name: bob-creates-it
description: "Use for visual Google Ads creative requests: find, refresh, adapt, generate, revise, or publish image and video assets from account evidence or user references. The LOW static replacement workflow is one supported route."
---

# Bob Creates It

Read `SOUL.md` before answering. Keep the workflow chat-driven: do not ask the user to click generation, approval, or publishing buttons.

## Creative loop

1. **Understand.** Resolve the selected account, requested surface (static image, video, or other), source (account assets, named files, uploaded reference, or script), scope, desired change, and whether the user wants drafts or a live change. Do not translate “all images in this campaign” into “LOW images.”
2. **Agree the method.** Inspect the relevant sources and account design guidance. Apply [creative-direction.md](references/creative-direction.md) when interpreting the concept, visual treatment, or copy. Tell the user which sources will be used, the proposed creative change, output count and format, and how the results will be checked. Except for a LOW edit, stop and wait for the user to approve that proposed direction before generation. The initial request is not approval; skip the pause only when the user explicitly approves an already-presented direction. For performance-based selection, use the latest 15 days by default and state the configured impression cutoff.
3. **Execute.** Use the available, documented capability for the selected surface. Static image sources and generation are described in [references/static-replacements.md](references/static-replacements.md). For a new surface, inspect available tools and propose the concrete method before running it. Do not invent a CLI command or claim a provider capability that is unavailable.
4. **Verify and iterate.** Check source coverage, output integrity, native size, duplicates, brand guidance, requested edits, and any Google Ads limits. Visually inspect generated images; revise a weak candidate with an immutable version in the same run. Technical checks alone do not establish creative quality or future performance.
5. **Present.** Show the finished outputs through the single creative-run review artifact and describe the creative decisions briefly. In hosted chat, copy the exact artifact marker printed by the generator as plain text; never wrap it in a Markdown link, emit a generic `[[ARTIFACT: ...]]` envelope, or link every output separately. The user can request named revisions in chat. Apply to Google Ads only after a separate, explicit chat instruction and the deterministic apply validation.

This is one loop with different source selectors and media adapters. LOW static replacement is a performance selector. Campaign refresh and named-asset refresh use the image inventory. Video and script-to-creative requests may enter the loop for planning; execute only when a corresponding media adapter and output checks are available. Do not reroute visual creative requests to the read-only Wings It analysis fallback.

## Static routes

- **LOW edit:** keep the selected LOW image, its proposition, composition, brand treatment, and native dimensions recognisable. Make the small requested change and present the result. Account design documents may inform this edit but do not block it.
- **Generic concept:** campaign/ad-group refreshes, new creative, and user-reference requests require current account `DESIGN.md`, current `DESIGN_STRATEGY.md`, and user intent supplied as text, an explicit reference image, or both. Campaign and ad-group names/IDs are useful context, not mandatory inputs. Generate one square master per agreed concept or creative family, present those masters, and wait for approval before adapting them to other ratios.

Choose the route from the user's intent before preparing sources. Use LOW edit only when the user explicitly asks about LOW/underperforming assets and the deterministic source selection is `low`. Words such as “refresh”, “redesign”, “new creative”, or “change all images” use the generic concept route even when the resulting source manifest uses `selection: assets`. Source count, native dimensions, or an image shared across placements never converts a generic refresh into one LOW-style edit per source.

For a generic concept, repeated placements are distribution metadata, not separate generation jobs. Prefer one master for a genuinely shared concept; do not force unrelated ad groups into one concept merely to reduce output count.

## Account guidance and provider

The Gemini credential is configured at client level; the approved model IDs and default live in `lib/bob/creates_it/models.yaml`, not Admin. Use the default image model for ordinary generation; use the approved Pro image model when the agreed brief needs complex graphic design, high-fidelity product detail, or precise text. Name only an allowlisted model in the confirmed brief. Video is disabled until its adapter and checks are built. `DESIGN.md`, `DESIGN_STRATEGY.md`, source evidence, runs, and outputs stay in the selected account. Generic concept generation requires both design documents to exist and be current. If either is missing or stale, create/update both from inspected account evidence using [references/design-guide.md](references/design-guide.md) first; do not generate the master until that prerequisite is complete. If there is not enough inspected evidence to ground them, stop and explain the limitation. LOW edits may proceed from the source image and user instruction without rebuilding account guidance. Codex inspects source and generated images when visual input is available; Gemini generates static image files in the hosted workflow.

## Non-negotiable boundaries

- Performance labels and numbers come only from Bob's deterministic creative workflow. A source inventory is not a performance report.
- Never generate before a selected account is authoritative.
- Never expose provider secrets, briefs, manifests, prompts, reference folders, or internal paths to the user.
- Present only reviewable output artifacts. The user controls revisions and publishing in chat; do not add workflow buttons.
- A generation request never grants Google Ads mutation permission. Run the existing approval-gated apply workflow only after an explicit chat instruction such as “make all live” or “make `<name>` live”.
- “Make all live” means only pending outputs in the latest run presented in the selected account. Never include another account or an older run.
