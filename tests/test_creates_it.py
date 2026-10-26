"""Static replacement generation boundary tests."""

from __future__ import annotations

import io
import base64
import csv
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from lib.bob.creates_it import adapt, generate
from lib.bob.performance import aggregate as performance_aggregate
from lib.bob.static_banners import variants
from lib.bob.platform.core import render_query
from datetime import date


def png_bytes(size=(64, 64), color=(20, 150, 70)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class CreatesItTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.customer = "1234567890"
        self.wiki = self.root / "wiki" / self.customer
        (self.wiki / "design").mkdir(parents=True)
        (self.wiki / "design" / "DESIGN.md").write_text("# Design\n\nUse a clear hero.\n")
        (self.wiki / "design" / "DESIGN_STRATEGY.md").write_text("# Strategy\n\nShort copy wins.\n")
        self.source = self.root / "sources" / "low.png"
        self.source.parent.mkdir()
        self.source.write_bytes(png_bytes((80, 60)))
        self.source_manifest = self.root / "low-manifest.json"
        self.source_manifest.write_text(json.dumps({
            "customer_id": self.customer,
            "assets": [{"asset_id": "asset-1", "local_path": str(self.source),
                        "campaign_name": "Campaign", "ad_group_name": "Group",
                        "ad_group_id": "123", "ad_id": "456"}],
        }))
        self.brief = self.root / "brief.json"
        self.brief.write_text(json.dumps({
            "confirmed": True,
            "replacements": [{"asset_id": "asset-1", "prompt": "Use less copy."}],
        }))
        self.provider = self.root / "provider.json"
        self.provider.write_text(json.dumps({
            "provider": "gemini", "api_key": "secret-key",
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _review(self, run: Path, reviews: list[dict]) -> None:
        review_path = self.root / "visual-review.json"
        review_path.write_text(json.dumps({"reviews": reviews}))
        args = SimpleNamespace(
            manifest=None,
            brief=None,
            run_id=run.name,
            visual_review=str(review_path),
        )
        env = {"BOB_SELECTED_CUSTOMER_ID": self.customer}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(generate, "STATE_ROOT", self.root), \
             patch.object(generate, "account_wiki_dir", lambda _: self.wiki):
            generate.create_static_replacements(args)

    def _run(self, caller, run_id="run-test-001", review=True, new_run=None):
        run = self.wiki / "creative-runs" / run_id
        if new_run is None:
            new_run = not (run / "manifest.json").exists()
        args = SimpleNamespace(
            manifest=str(self.source_manifest), brief=str(self.brief),
            run_id=run_id, new_run=new_run,
        )
        env = {"BOB_SELECTED_CUSTOMER_ID": self.customer, "BOB_CREATIVE_PROVIDER_CONFIG": str(self.provider)}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(generate, "STATE_ROOT", self.root), \
             patch.object(generate, "account_wiki_dir", lambda _: self.wiki):
            generate.create_static_replacements(args, caller=caller)
        if review:
            manifest = json.loads((run / "manifest.json").read_text())
            pending = [
                item for item in manifest["candidates"]
                if item.get("review_status") == "pending"
                and item.get("visual_review", {}).get("status") == "pending"
            ]
            checks = {name: "passed" for name in generate.VISUAL_REVIEW_CHECKS}
            self._review(run, [
                {"name": item["name"], "checks": checks, "issues": []}
                for item in pending
            ])
        return run

    def test_generation_is_account_scoped_exact_size_and_secret_free(self):
        calls = []
        def caller(api_key, model, prompt, source, ratio):
            calls.append((api_key, model, prompt, source, ratio))
            return png_bytes((160, 120)), "image/png"

        run = self._run(caller)
        output = next((run / "outputs").glob("*.png"))
        with Image.open(output) as image:
            self.assertEqual(image.size, (80, 60))
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["customer_id"], self.customer)
        self.assertEqual(manifest["status"], "ready_for_review")
        self.assertNotIn("secret-key", (run / "manifest.json").read_text())
        self.assertEqual(calls[0][0:2], ("secret-key", "gemini-3.1-flash-image"))
        self.assertIn("Use less copy", calls[0][2])
        self.assertIn("visibly distinct controlled evolution", calls[0][2])
        self.assertIn("obvious at normal feed size", calls[0][2])
        self.assertIn("do not reproduce the source layout or styling pixel-for-pixel", calls[0][2])
        self.assertNotIn("materially new focal idea", calls[0][2])
        self.assertNotIn("Use a clear hero", calls[0][2])
        self.assertNotIn("Short copy wins", calls[0][2])
        self.assertTrue((run / "references" / "source-asset-1.png").is_file())
        account_index = (self.wiki / "Index.md").read_text()
        self.assertIn("## Design", account_index)
        self.assertIn("## Action Items", account_index)
        self.assertIn("creative-runs/run-test-001/index.md", account_index)
        action_items = account_index.split("## Action Items", 1)[1].split("## Design", 1)[0]
        design = account_index.split("## Design", 1)[1]
        self.assertIn("creative-runs/run-test-001/index.md", action_items)
        self.assertNotIn("creative-runs/run-test-001/index.md", design)
        self.assertIn("[DESIGN.md](design/DESIGN.md)", design)
        self.assertIn("[DESIGN_STRATEGY.md](design/DESIGN_STRATEGY.md)", design)
        self.assertIn("[Creative Review — ", account_index)
        self.assertNotIn("[run-test-001]", account_index)
        self.assertIn(output.name, (run / "index.md").read_text())

        detail = run / "details" / f"{output.stem}.md"
        detail_text = detail.read_text()
        request_section = detail_text.split("## Generation request", 1)[1]
        request_text = request_section.split("```json\n", 1)[1].split("\n```", 1)[0]
        request = json.loads(request_text)
        self.assertEqual(request["model"], "gemini-3.1-flash-image")
        self.assertEqual(request["input"][0], {
            "type": "image",
            "reference": "source-asset-1.png",
            "mime_type": "image/png",
        })
        self.assertIn("Use less copy", request["input"][1]["text"])
        self.assertNotIn("data", request["input"][0])
        self.assertNotIn("secret-key", detail_text)
        self.assertIn('"method": "ai_generation"', detail_text)
        self.assertIn('"prompt_used": true', detail_text)
        self.assertIn("Production: gemini generation", (run / "index.md").read_text())
        self.assertIn("View generation details", (run / "index.md").read_text())

    def test_generation_prints_one_canonical_run_artifact_marker(self):
        output = StringIO()
        with redirect_stdout(output):
            self._run(lambda *_: (png_bytes((80, 60)), "image/png"))
        self.assertIn(
            "[[artifact:wiki/1234567890/creative-runs/run-test-001/index.md|"
            "Open the full creative review]]",
            output.getvalue(),
        )

    def test_visual_review_is_required_and_failed_output_is_not_presented(self):
        run = self._run(
            lambda *_: (png_bytes((80, 60)), "image/png"),
            review=False,
        )
        manifest = json.loads((run / "manifest.json").read_text())
        candidate = manifest["candidates"][0]
        self.assertEqual(manifest["status"], "visual_review_pending")
        self.assertEqual(candidate["visual_review"], {"status": "pending"})
        self.assertFalse((self.wiki / "Index.md").exists())
        self.assertNotIn(candidate["name"], (run / "index.md").read_text())
        plan = json.loads((run / "apply-plan.yaml").read_text())
        self.assertEqual(plan["changes"], [])
        self.assertIn("visual review must pass", plan["blocked_candidates"][0]["reason"])

        checks = {name: "passed" for name in generate.VISUAL_REVIEW_CHECKS}
        checks["creative_transformation"] = "failed"
        self._review(run, [{
            "name": candidate["name"],
            "checks": checks,
            "issues": ["The requested LOW edit is not noticeable at normal feed size."],
        }])
        reviewed = json.loads((run / "manifest.json").read_text())
        self.assertEqual(reviewed["status"], "visual_review_failed")
        self.assertEqual(reviewed["candidates"][0]["visual_review"]["status"], "failed")
        self.assertNotIn(candidate["name"], (run / "index.md").read_text())
        self.assertFalse((self.wiki / "Index.md").exists())

    def test_visual_review_rejects_incomplete_rubric(self):
        run = self._run(
            lambda *_: (png_bytes((80, 60)), "image/png"),
            review=False,
        )
        manifest = json.loads((run / "manifest.json").read_text())
        with self.assertRaises(SystemExit):
            self._review(run, [{
                "name": manifest["candidates"][0]["name"],
                "checks": {"composition": "passed"},
                "issues": [],
            }])

    def test_brief_can_choose_approved_pro_model(self):
        brief = json.loads(self.brief.read_text())
        brief["model"] = "gemini-3-pro-image"
        self.brief.write_text(json.dumps(brief))
        called = []
        run = self._run(lambda _key, model, *_: (called.append(model) or png_bytes((80, 60)), "image/png"))
        self.assertEqual(called, ["gemini-3-pro-image"])
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["candidates"][0]["model"], "gemini-3-pro-image")

    def test_unapproved_model_stops_before_provider_call(self):
        brief = json.loads(self.brief.read_text())
        brief["model"] = "unlisted-image-model"
        self.brief.write_text(json.dumps(brief))
        with self.assertRaises(SystemExit):
            self._run(lambda *_: self.fail("provider must not be called"))

    def test_regeneration_versions_without_overwriting(self):
        caller = lambda *_: (png_bytes((80, 60), (20, 30, 40)), "image/png")
        run = self._run(caller)
        first = next((run / "outputs").glob("*-v1.png"))
        first_hash = first.read_bytes()
        self._run(lambda *_: (png_bytes((80, 60), (50, 60, 70)), "image/png"))
        self.assertEqual(first.read_bytes(), first_hash)
        self.assertEqual(len(list((run / "outputs").glob("*.png"))), 2)
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual([item["name"] for item in manifest["candidates"]], [
            "static-asset-1-v1.png", "static-asset-1-v2.png",
        ])
        self.assertEqual([item["review_status"] for item in manifest["candidates"]], [
            "superseded", "pending",
        ])
        apply_plan = json.loads((run / "apply-plan.yaml").read_text())
        self.assertEqual(len(apply_plan["changes"]), 1)
        self.assertTrue(apply_plan["changes"][0]["replacement_image"].endswith("static-asset-1-v2.png"))

    def test_run_creation_and_continuation_are_explicit(self):
        with self.assertRaises(SystemExit):
            self._run(lambda *_: (png_bytes((80, 60)), "image/png"), new_run=False)
        run = self._run(
            lambda *_: (png_bytes((80, 60), (20, 30, 40)), "image/png"),
            new_run=True,
        )
        with self.assertRaises(SystemExit):
            self._run(
                lambda *_: (png_bytes((80, 60), (50, 60, 70)), "image/png"),
                new_run=True,
            )
        self.assertEqual(len(list((run / "outputs").glob("*.png"))), 1)

    def test_account_index_moves_legacy_creative_rows_out_of_design(self):
        self.wiki.joinpath("Index.md").write_text(
            "# Bob — Wiki Index\n\n## Action Items\n\n## Design\n\n"
            "<!-- creative-run:older-run -->\n"
            "- [Older review](creative-runs/older-run/index.md) — 1 review output\n\n"
            "- [Account Design Guidance — 2026-10-01](design/DESIGN.md) — old\n\n"
            "## Backlog\n"
        )
        self._run(lambda *_: (png_bytes((80, 60)), "image/png"))
        text = self.wiki.joinpath("Index.md").read_text()
        action_items = text.split("## Action Items", 1)[1].split("## Design", 1)[0]
        design = text.split("## Design", 1)[1].split("## Backlog", 1)[0]
        self.assertIn("creative-runs/older-run/index.md", action_items)
        self.assertIn("creative-runs/run-test-001/index.md", action_items)
        self.assertNotIn("creative-runs/", design)
        self.assertEqual(design.count("design/DESIGN.md"), 1)
        self.assertEqual(design.count("design/DESIGN_STRATEGY.md"), 1)

    def test_regeneration_rejects_duplicate_of_prior_candidate(self):
        image = png_bytes((80, 60), (20, 30, 40))
        run = self._run(lambda *_: (image, "image/png"))
        with self.assertRaises(SystemExit):
            self._run(lambda *_: (image, "image/png"))
        self.assertEqual([path.name for path in (run / "outputs").glob("*.png")], [
            "static-asset-1-v1.png",
        ])

    def test_account_mismatch_stops_before_provider_call(self):
        data = json.loads(self.source_manifest.read_text())
        data["customer_id"] = "9999999999"
        self.source_manifest.write_text(json.dumps(data))
        with self.assertRaises(SystemExit), patch.dict(os.environ, {
            "BOB_SELECTED_CUSTOMER_ID": self.customer,
            "BOB_CREATIVE_PROVIDER_CONFIG": str(self.provider),
        }, clear=False), patch.object(generate, "STATE_ROOT", self.root), \
             patch.object(generate, "account_wiki_dir", lambda _: self.wiki):
            generate.create_static_replacements(
                SimpleNamespace(manifest=str(self.source_manifest), brief=str(self.brief), run_id="run-test-002"),
                caller=lambda *_: self.fail("provider must not be called"),
            )

    def test_extract_output_rejects_missing_image(self):
        with self.assertRaises(SystemExit):
            generate._extract_output_image({"interaction": {"output_text": "no image"}})

    def test_generated_output_is_never_stretched_across_materially_different_ratios(self):
        with self.assertRaises(ValueError):
            adapt.normalize_generated_png(
                png_bytes((100, 100)), self.root / "wrong-ratio.png", (1200, 628)
            )
        self.assertFalse((self.root / "wrong-ratio.png").exists())

    def test_gemini_source_inputs_accept_jpeg_png_and_webp_without_forcing_output_mime(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "interaction": {
                        "output": [{
                            "data": base64.b64encode(png_bytes()).decode(),
                            "mime_type": "image/png",
                        }]
                    }
                }).encode()

        for extension, image_format, expected_mime in (
            ("jpg", "JPEG", "image/jpeg"),
            ("png", "PNG", "image/png"),
            ("webp", "WEBP", "image/webp"),
        ):
            with self.subTest(format=image_format):
                source = self.root / f"source.{extension}"
                Image.new("RGB", (24, 16), (25, 100, 175)).save(source, format=image_format)
                requests = []

                def opener(request, timeout):
                    requests.append(json.loads(request.data))
                    self.assertEqual(timeout, 120)
                    return Response()

                image, mime = generate._call_gemini(
                    "test-key", "gemini-3.1-flash-image", "edit", source, "3:2", opener=opener
                )
                self.assertEqual(mime, "image/png")
                self.assertTrue(image.startswith(b"\x89PNG"))
                self.assertEqual(requests[0]["input"][0]["mime_type"], expected_mime)
                self.assertNotIn("mime_type", requests[0]["response_format"])

    def test_shared_wiki_symlink_is_trusted_for_source_files_only(self):
        state = self.root / "conversation-state"
        shared = self.root / "shared-state"
        manifest = shared / "wiki" / self.customer / "creative-sources" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}")
        state.mkdir()
        (state / "wiki").symlink_to(shared / "wiki", target_is_directory=True)
        through_workspace_link = state / "wiki" / self.customer / "creative-sources" / "manifest.json"
        with patch.object(generate, "STATE_ROOT", state), patch.dict(os.environ, {
            "BOB_SHARED_STATE_ROOT": str(shared),
        }, clear=False):
            resolved = generate._safe_state_file(
                str(through_workspace_link), "static source manifest", allow_shared=True
            )
            self.assertEqual(resolved, manifest.resolve())
            with self.assertRaises(SystemExit):
                generate._safe_state_file(str(through_workspace_link), "replacement brief")

    def test_private_state_symlink_is_trusted_for_replacement_brief(self):
        state = self.root / "conversation-state"
        workspace = self.root / "workspace"
        private_brief = state / ".bob" / "creative-briefs" / "run-001-edit.json"
        private_brief.parent.mkdir(parents=True)
        private_brief.write_text('{"confirmed": true}')
        workspace.mkdir()
        (workspace / ".bob").symlink_to(state / ".bob", target_is_directory=True)
        through_workspace_link = workspace / ".bob" / "creative-briefs" / "run-001-edit.json"
        with patch.object(generate, "STATE_ROOT", state):
            self.assertEqual(
                generate._safe_state_file(str(through_workspace_link), "replacement brief"),
                private_brief.resolve(),
            )

    def test_missing_placement_allows_review_candidate_and_blocks_publish(self):
        source = json.loads(self.source_manifest.read_text())
        source["selection"] = "low"
        source["assets"][0].pop("ad_group_id")
        source["assets"][0].pop("ad_id")
        self.source_manifest.write_text(json.dumps(source))
        self.brief.write_text(json.dumps({
            "customer_id": self.customer,
            "selection": "low",
            "mode": "low_edit",
            "confirmed": True,
            "replacements": [{"asset_id": "asset-1", "prompt": "Localize the headline."}],
        }))
        run = self._run(lambda *_: (png_bytes((80, 60)), "image/png"))
        manifest = json.loads((run / "manifest.json").read_text())
        plan = json.loads((run / "apply-plan.yaml").read_text())
        self.assertEqual(manifest["status"], "ready_for_review")
        self.assertFalse(manifest["candidates"][0]["publish_ready"])
        self.assertEqual(plan["changes"], [])
        self.assertEqual(plan["blocked_candidates"][0]["asset_id"], "asset-1")
        output = StringIO()
        with patch.object(variants, "_require_write_permission"), redirect_stdout(output):
            variants.static_variants_apply(SimpleNamespace(plan=str(run / "apply-plan.yaml")))
        self.assertIn("cannot publish", output.getvalue())
        self.assertIn("asset-1", output.getvalue())

    def test_campaign_refresh_generates_master_then_approved_adaptations(self):
        source = json.loads(self.source_manifest.read_text())
        source["selection"] = "campaign"
        source["assets"][0]["width"] = 80
        source["assets"][0]["height"] = 60
        source["assets"][0]["duplicate_placements"] = [
            {"campaign_id": "c1", "ad_group_id": "11", "ad_id": "101"},
            {"campaign_id": "c1", "ad_group_id": "22", "ad_id": "202"},
        ]
        self.source_manifest.write_text(json.dumps(source))
        self.brief.write_text(json.dumps({
            "customer_id": self.customer,
            "selection": "campaign",
            "mode": "concept",
            "stage": "masters",
            "user_request": "Refresh every image in campaign c1",
            "confirmed": True,
            "concepts": [{
                "concept_id": "campaign-c1",
                "source_asset_ids": ["asset-1"],
                "instruction": "Simplify the layout.",
            }],
        }))
        prompts = []
        def caller(_key, _model, prompt, _source, _ratio):
            prompts.append(prompt)
            return png_bytes((1400, 1400)), "image/png"

        run = self._run(caller)
        self.assertIn("Simplify the layout", prompts[0])
        self.assertNotIn("LOW-performing", prompts[0])
        self.assertIn("materially new focal idea", prompts[0])
        self.assertIn("rather than reusing a reference layout", prompts[0])
        self.assertNotIn("Follow the instruction exactly", prompts[0])
        self.assertIn("creative_transformation", generate.VISUAL_REVIEW_CHECKS)
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "masters_ready")
        self.assertEqual(manifest["selection"], "campaign")
        self.assertEqual(json.loads((run / "apply-plan.yaml").read_text())["changes"], [])
        master = manifest["candidates"][0]
        with Image.open(run / "outputs" / master["name"]) as image:
            self.assertEqual(image.size, (1200, 1200))
        self.brief.write_text(json.dumps({
            "customer_id": self.customer,
            "selection": "campaign",
            "mode": "concept",
            "stage": "adaptations",
            "user_request": "Use the approved master",
            "confirmed": True,
            "adaptations": [
                {
                    "master_name": master["name"],
                    "formats": ["square", "vertical"],
                    "method": "python",
                },
                {
                    "master_name": master["name"],
                    "formats": ["horizontal"],
                    "method": "ai",
                    "instruction": "Recompose the approved concept for a wide placement.",
                },
            ],
        }))
        adaptation_calls = []
        self._run(lambda *_args: (adaptation_calls.append(_args) or png_bytes((1600, 900)), "image/png"))
        self.assertEqual(len(adaptation_calls), 1)
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "adaptations_ready")
        self.assertEqual(
            {item.get("format") for item in manifest["candidates"] if item.get("candidate_type") == "adaptation"},
            {"horizontal", "vertical"},
        )
        horizontal = next(
            item for item in manifest["candidates"] if item.get("format") == "horizontal"
        )
        with Image.open(run / "outputs" / horizontal["name"]) as image:
            self.assertEqual(image.size, (1200, 628))
        self.assertEqual(horizontal["qa"]["adaptation_method"], "ai_recomposition")
        vertical = next(
            item for item in manifest["candidates"] if item.get("format") == "vertical"
        )
        horizontal_detail = (run / str(horizontal["detail_page"])).read_text()
        vertical_detail = (run / str(vertical["detail_page"])).read_text()
        self.assertIn('"method": "ai_recomposition"', horizontal_detail)
        self.assertIn('"prompt_used": true', horizontal_detail)
        self.assertIn('"method": "deterministic_python_adaptation"', vertical_detail)
        self.assertIn('"tool": "adapt_master_png"', vertical_detail)
        self.assertIn('"prompt_used": false', vertical_detail)
        self.assertIn("No AI prompt was used", vertical_detail)
        changes = json.loads((run / "apply-plan.yaml").read_text())["changes"]
        self.assertEqual({(item["ad_group_id"], item["ad_id"]) for item in changes},
                         {("11", "101"), ("22", "202")})

    def test_low_edit_does_not_require_design_documents(self):
        (self.wiki / "design" / "DESIGN.md").unlink()
        (self.wiki / "design" / "DESIGN_STRATEGY.md").unlink()
        run = self._run(lambda *_: (png_bytes((160, 120)), "image/png"))
        self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "ready_for_review")

    def test_concept_requires_design_documents_and_user_expectation(self):
        source = json.loads(self.source_manifest.read_text())
        source["selection"] = "campaign"
        self.source_manifest.write_text(json.dumps(source))
        self.brief.write_text(json.dumps({
            "customer_id": self.customer,
            "selection": "campaign",
            "mode": "concept",
            "stage": "masters",
            "confirmed": True,
            "concepts": [{"concept_id": "one", "source_asset_ids": ["asset-1"]}],
        }))
        with self.assertRaises(SystemExit):
            self._run(lambda *_: self.fail("provider must not be called"))

    def test_static_selection_uses_label_only_for_low_mode(self):
        rows = [
            {"asset_type": "IMAGE", "asset_id": "1", "campaign_id": "c1",
             "performance_label": "LOW", "impressions": "60"},
            {"asset_type": "IMAGE", "asset_id": "2", "campaign_id": "c1",
             "performance_label": "GOOD", "impressions": "0"},
            {"asset_type": "IMAGE", "asset_id": "3", "campaign_id": "c2",
             "performance_label": "BEST", "impressions": "100"},
        ]
        def ids(selection, **selectors):
            args = SimpleNamespace(**{"selection": selection, "campaign_id": "", "asset_ids": "", **selectors})
            return [row["asset_id"] for row in variants._select_static_rows(rows, args, 50)]
        self.assertEqual(ids("low"), ["1"])
        self.assertEqual(ids("campaign", campaign_id="c1"), ["1", "2"])
        self.assertEqual(ids("assets", asset_ids="2,3"), ["2", "3"])

    def test_current_inventory_query_has_no_performance_cutoff(self):
        query = render_query("creative_image_inventory", date(2026, 10, 5), date(2026, 10, 5))
        self.assertIn("ad_group_ad_asset_view.enabled = TRUE", query)
        self.assertNotIn("metrics.impressions >=", query)
        self.assertNotIn("segments.date BETWEEN", query)

    def test_inventory_aggregation_keeps_zero_impression_image(self):
        raw = self.root / "inventory-raw.csv"
        with raw.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_id",
                "asset_id", "asset_type", "image_url",
            ])
            writer.writeheader()
            writer.writerow({"customer_id": self.customer, "campaign_id": "10",
                             "campaign_name": "Campaign", "ad_group_id": "20", "ad_id": "30",
                             "asset_id": "40", "asset_type": "IMAGE", "image_url": "https://example.invalid/a.png"})
        raw.with_suffix(".meta.json").write_text(json.dumps({"query_name": "creative_image_inventory"}))
        output = self.root / "inventory-processed.csv"
        args = SimpleNamespace(grain="creative_period", source=None,
                               goal=None, input=str(raw), input_paths=None, customer=self.customer,
                               output=str(output), from_date="2026-10-05", to="2026-10-05")
        with patch.object(performance_aggregate, "load_profile", return_value={"creative_min_impressions": 50000}):
            performance_aggregate.aggregate(args)
        with output.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset_id"], "40")
        self.assertEqual(rows[0]["ad_id"], "30")
        output_metadata = json.loads(output.with_suffix(".meta.json").read_text())
        self.assertEqual(output_metadata["source_query"], "creative_image_inventory")

    def test_creative_aggregation_rejects_source_metadata_conflict(self):
        raw = self.root / "inventory-raw.csv"
        raw.write_text("customer_id,campaign_id,asset_id\n1234567890,1,2\n")
        raw.with_suffix(".meta.json").write_text(json.dumps({"query_name": "creative_image_inventory"}))
        args = SimpleNamespace(grain="creative_period", source="creative_image_period",
                               goal=None, input=str(raw), input_paths=None, customer=self.customer,
                               output=str(self.root / "processed.csv"), from_date=None, to=None)
        with patch.object(performance_aggregate, "load_profile", return_value={}):
            with self.assertRaises(SystemExit):
                performance_aggregate.aggregate(args)

    def test_apply_match_requires_exact_ad_when_asset_is_shared(self):
        def row(ad_id):
            image = SimpleNamespace(asset="customers/123/assets/asset-1")
            ad = SimpleNamespace(ad=SimpleNamespace(id=ad_id, app_ad=SimpleNamespace(images=[image])))
            return SimpleNamespace(ad_group_ad=ad)
        rows = [row("a1"), row("a2")]
        match, _ = variants._matching_app_ad(rows, "customers/123/assets/asset-1", "a2")
        self.assertEqual(match.ad.id, "a2")
        with self.assertRaises(ValueError):
            variants._matching_app_ad(rows, "customers/123/assets/asset-1", "")

    def test_campaign_preparation_keeps_good_and_low_images_in_separate_inventory(self):
        source_dir = self.root / "arbitrary-output-location"
        source_dir.mkdir()
        source = source_dir / f"{self.customer}_2026-10-05_2026-10-05_image_inventory.csv"
        fields = ["customer_id", "campaign_id", "campaign_name", "ad_group_id",
                  "ad_group_name", "ad_id", "asset_id", "asset_type", "performance_label",
                  "image_width", "image_height", "impressions", "image_url"]
        with source.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for asset_id, label in (("1", "LOW"), ("2", "GOOD")):
                writer.writerow({"customer_id": self.customer, "campaign_id": "c1",
                                 "campaign_name": "Campaign", "ad_group_id": "g1", "ad_id": asset_id,
                                 "asset_id": asset_id, "asset_type": "IMAGE",
                                 "performance_label": label, "image_width": 80,
                                 "image_height": 60, "impressions": 0})
        source.with_suffix(".meta.json").write_text(json.dumps({
            "source_query": "creative_image_inventory", "grain": "creative_period",
            "customer_id": self.customer,
        }))
        args = SimpleNamespace(selection="campaign", campaign_id="c1", asset_ids="",
                               customer=self.customer, input=str(source), min_impressions=None)
        with patch.object(variants, "load_profile", return_value={"creative_min_impressions": 50000}), \
             patch.object(variants, "account_wiki_dir", lambda _: self.wiki):
            variants.suggest_static_variants(args)
        manifests = list((self.wiki / "design" / "creative-sources").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        prepared = json.loads(manifests[0].read_text())
        self.assertEqual(prepared["selection"], "campaign")
        self.assertEqual({item["asset_id"] for item in prepared["assets"]}, {"1", "2"})
        self.assertEqual(prepared["generation_route"], "concept")
        self.assertEqual(prepared["generation_contract"]["route"], "concept")
        self.assertIn("one 1200x1200 master per agreed concept", prepared["generation_contract"]["output_size_rule"])
        self.assertNotIn("native dimensions", prepared["generation_contract"]["output_size_rule"])

    def test_campaign_preparation_rejects_non_inventory_source_metadata(self):
        source_dir = self.root / "arbitrary-output-location"
        source_dir.mkdir()
        source = source_dir / "processed.csv"
        source.write_text("customer_id,campaign_id,asset_id,asset_type\n1234567890,c1,1,IMAGE\n")
        source.with_suffix(".meta.json").write_text(json.dumps({
            "source_query": "creative_image_period", "grain": "creative_period",
            "customer_id": self.customer,
        }))
        args = SimpleNamespace(selection="campaign", campaign_id="c1", asset_ids="",
                               customer=self.customer, input=str(source), min_impressions=None)
        with self.assertRaises(SystemExit):
            variants.suggest_static_variants(args)

    def test_partial_apply_retry_skips_placements_already_replaced(self):
        first = {"asset_id": "1", "ad_group_id": "10", "ad_id": "100",
                 "replacement_image": "/tmp/first.png", "action": "replace"}
        second = {"asset_id": "1", "ad_group_id": "20", "ad_id": "200",
                  "replacement_image": "/tmp/first.png", "action": "replace"}
        plan_path = self.root / "apply-plan.yaml"
        plan_path.write_text(json.dumps({
            "applied": False,
            "changes": [first, second],
            "apply_results": [{"status": "replaced", "plan_key": variants._apply_change_key(first)}],
        }))
        _plan, pending, _path = variants._load_static_variant_apply_changes(
            SimpleNamespace(plan=str(plan_path))
        )
        self.assertEqual(pending, [second])


if __name__ == "__main__":
    unittest.main()
