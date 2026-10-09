---
name: bob-creates-it
description: "Use for visual Google Ads creative requests: find, refresh, adapt, generate, revise, or publish image and video assets from account evidence or user references. The LOW static replacement workflow is one supported route."
---

# Bob Creates It

Read `SOUL.md` before answering. Keep the workflow chat-driven: do not ask the user to click generation, approval, or publishing buttons.

## Creative loop

1. **Understand.** Resolve the selected account, requested surface (static image, video, or other), source (account assets, named files, uploaded reference, or script), scope, desired change, and whether the user wants drafts or a live change. Do not translate “all images in this campaign” into “LOW images.”
2. **Agree the method.** Inspect the relevant sources and account design guidance. Tell the user which sources will be used, the proposed creative change, output count and format, and how the results will be checked. Confirm material choices before generation; a user who has already specified the method need not repeat it. For performance-based selection, use the latest 15 days by default and state the configured impression cutoff.
3. **Execute.** Use the available, documented capability for the selected surface. Static image sources and generation are described in [references/static-replacements.md](references/static-replacements.md). For a new surface, inspect available tools and propose the concrete method before running it. Do not invent a CLI command or claim a provider capability that is unavailable.
4. **Verify and iterate.** Check source coverage, output integrity, native size, duplicates, brand guidance, requested edits, and any Google Ads limits. Visually inspect generated images; revise a weak candidate with an immutable version in the same run. Technical checks alone do not establish creative quality or future performance.
5. **Present.** Show the finished outputs in Artifacts and describe the creative decisions briefly. The user can request named revisions in chat. Apply to Google Ads only after a separate, explicit chat instruction and the deterministic apply validation.

This is one loop with different source selectors and media adapters. LOW static replacement is a performance selector. Campaign refresh and named-asset refresh use the image inventory. Video and script-to-creative requests may enter the loop for planning; execute only when a corresponding media adapter and output checks are available. Do not reroute visual creative requests to the read-only Wings It analysis fallback.

## Account guidance and provider

The Gemini credential is configured at client level; the approved model IDs and default live in `lib/bob/creates_it/models.yaml`, not Admin. Use the default image model for ordinary generation; use the approved Pro image model when the agreed brief needs complex graphic design, high-fidelity product detail, or precise text. Name only an allowlisted model in the confirmed brief. Video is disabled until its adapter and checks are built. `DESIGN.md`, `DESIGN_STRATEGY.md`, source evidence, runs, and outputs stay in the selected account. Before generating or replacing assets, check that both design documents exist and are current. If either is missing or stale, create/update both from inspected account evidence using [references/design-guide.md](references/design-guide.md) first; do not generate until that prerequisite is complete. If there is not enough inspected evidence to ground the documents, stop and explain the limitation. Codex inspects source and generated images when visual input is available; Gemini generates static image files in the hosted workflow.

## Non-negotiable boundaries

- Performance labels and numbers come only from Bob's deterministic creative workflow. A source inventory is not a performance report.
- Never generate before a selected account is authoritative.
- Never expose provider secrets, briefs, manifests, prompts, reference folders, or internal paths to the user.
- Present only reviewable output artifacts. The user controls revisions and publishing in chat; do not add workflow buttons.
- A generation request never grants Google Ads mutation permission. Run the existing approval-gated apply workflow only after an explicit chat instruction such as “make all live” or “make `<name>` live”.
- “Make all live” means only pending outputs in the latest run presented in the selected account. Never include another account or an older run.
