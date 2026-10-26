# Image-to-video generation

Use this adapter after agreeing a video concept, source, scope and review criteria. It creates review-only account-scoped videos; it does not publish a Google Ads asset.

## Storyboard first

Create one `creative-runs/<run-id>/index.md` storyboard artifact before generation. It is the single editable planning and review surface for the run. Include narrative sections, pictorial panels, exact required copy, visual reference roles, dialogue and voice assignment, SFX, music direction, output plan and status. Do not create a new artifact for each storyboard revision.

Narrative sections follow the scene, not an arbitrary time grid. Keep straightforward, coherent action in the fewest longer continuous clips needed to tell the story. Mark only high-risk actions as `high`: moving vehicles, rapid interaction, complex hand contact, multiple changing subjects, or any action whose failure would invalidate the ad. Generate a high-risk action as its own controlled clip; do not split ordinary action merely to make equal-length chunks.

Make the panels low-fidelity only when the source itself is enough to agree action; otherwise make high-fidelity, clean panels from the approved source. Each scene panel states the visual, camera, speaker, exact dialogue and voice. The final panel is the deterministic end card. Present the board and wait for explicit approval such as “approve this storyboard.” Then compile the current artifact into a private confirmed brief and run `./bob video-create --brief <private brief> --run-id <run-id>`. The command snapshots that brief. A later artifact edit cannot alter an already approved or in-flight generation.

Each paid provider result is a durable run checkpoint: approved pictorial panels, raw video, then optional music. If deterministic finishing or review fails, retry the same confirmed brief and run ID. Bob validates and reuses matching checkpoints instead of calling a provider again. Changing an approved scene panel, source, visual prompt, model, or output setting creates a new visual fingerprint and requires a new video generation. Changing music, copy, logo, CTA, or end-card timing reuses the completed visual checkpoint.

## Master and adaptation

The first executable route creates one fixed-duration `9:16` master. Its duration is declared by the selected allowlisted model in the creative catalog; it is not a Gemini request parameter. When a supplied reference contains copy, logo, CTA, offer, legal text, or UI, clean the storyboard scene panels first. Give Omni the approved opening and closing scene panels, their visual progression, cast, exact spoken lines and voice assignments. Require a continuous full-frame scene; do not send overlays, logos, copy, CTA, music or timing directions to the model. Omni produces the native scene audio. Validate the raw video against that fixed duration before finishing. Apply exact approved text, CTA, and a supplied brand logo only in the opaque final 1–2 second end card. If an exact logo is required but no approved logo file is available, stop before generation; never recreate the logo with AI.

After the master passes visual review and the user explicitly approves it, create a `16:9` FFmpeg adaptation. It retains the intact portrait video over an extended background; it never stretches pixels. If that arrangement is creatively weak, stop and propose a separate ratio-specific AI master instead of calling a crop successful.

## Sound

Specify SFX, dialogue, and music separately in the storyboard. Dialogue belongs to the named visible character and is generated natively with the scene. Lyria supplies optional backing music after video generation. Give providers no timestamps. Deterministic finishing ducks music below native dialogue and applies the end card; it must never trim, extend, or otherwise change the visual duration.

If a video or music provider returns a policy block, preserve every completed checkpoint and relay the returned policy message plainly. Do not guess at a safe rewrite, silently remove sound, change providers, or retry variants. Ask the user for a revised direction for the blocked stage and wait for approval. A music revision retries music and finishing only; a video revision needs a new video generation from the approved panels.

## Review

Before presentation, inspect every pending output using exactly these checks: `storyboard_fidelity`, `temporal_coherence`, `brand_fidelity`, `copy_accuracy`, `composition`, `audio_fit`, and `visual_integrity`. Confirm that the visible speaker matches the assigned voice and line, the Captain/product role is clear, no baked reference copy/logo/CTA survives before the deterministic end card, and the final overlay is exact and legible.

Technical validation establishes duration, aspect ratio, streams and file integrity. It does not establish visual quality. A failed check needs a concise issue and must not be shown as passed. Present the single run artifact only after all pending outputs have a completed review.
