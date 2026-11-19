"""Video storyboard lifecycle tests."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from lib.bob.creates_it import video, video_media


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (90, 160), (10, 120, 70)).save(buffer, format="PNG")
    return buffer.getvalue()


class VideoCreatesItTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.customer = "1234567890"
        self.wiki = self.root / "wiki" / self.customer
        self.briefs = self.root / "briefs"; self.briefs.mkdir()
        self.provider = self.root / "provider.json"
        self.provider.write_text(json.dumps({"provider": "gemini", "api_key": "secret"}))
        self.source = self.root / "source.png"; self.source.write_bytes(png_bytes())
        self.env = {"BOB_SELECTED_CUSTOMER_ID": self.customer, "BOB_CREATIVE_PROVIDER_CONFIG": str(self.provider)}

    def tearDown(self):
        self.tmp.cleanup()

    def _brief(self, **changes):
        value = {
            "customer_id": self.customer,
            "stage": "storyboard",
            "title": "Chai ride",
            "duration_seconds": 6,
            "aspect_ratio": "9:16",
            "preview_confirmed": True,
            "storyboard_fidelity": "low_fidelity",
            "source_image": str(self.source),
            "storyboard": [
                {"title": "Chai stall", "action": "Steam rises while the commuter notices the Captain.", "risk": "standard"},
                {"title": "Ride solution", "action": "The stationary Captain acknowledges the commuter.", "risk": "high"},
            ],
            "copy": {"headline": "Chai se pehle ride."},
            "end_card": {"start_seconds": 4.8},
            "panels": [
                {"title": "Chai order", "visual": "Customer at the chai stall.", "camera": "Stable portrait frame.", "speaker": "Customer", "voice": "adult Indian male voice", "dialogue": "Bhaiya, ek chai dena.", "kind": "scene"},
                {"title": "Captain arrives", "visual": "Captain arrives beside customer.", "camera": "Keep both men readable.", "speaker": "Captain", "voice": "adult Indian male voice", "dialogue": "Sir, aapki ride.", "kind": "scene"},
                {"title": "End card", "visual": "Branded product window.", "camera": "Static full-frame end card.", "kind": "end_card"},
            ],
            "sfx": ["chai-stall ambience"],
            "music": {},
        }
        value.update(changes)
        return value

    def _write_brief(self, value, name="brief.json"):
        path = self.briefs / name
        path.write_text(json.dumps(value))
        return path

    def _scene_brief(self, **changes):
        value = self._brief(copy={}, end_card={})
        value["panels"] = value["panels"][:-1]
        value.update(changes)
        return value

    def _run(self, args, **kwargs):
        with patch.dict(os.environ, self.env, clear=False), \
             patch.object(video, "STATE_ROOT", self.root), \
             patch.object(video, "account_wiki_dir", lambda _: self.wiki):
            video.create_video(args, **kwargs)

    def _approved_master(self, run_id, value, name="master.json"):
        prompt = self._write_brief({**value, "stage": "prompt", "confirmed": True, "accepted_omissions": ["timing", "sfx", "music"]}, f"prompt-{name}")
        self._run(SimpleNamespace(brief=str(prompt), run_id=run_id, visual_review=None))
        run = self.wiki / "creative-runs" / run_id
        prompt_hash = json.loads((run / "manifest.json").read_text())["prompt_hash"]
        return self._write_brief({**value, "stage": "master", "confirmed": True, "prompt_confirmed": True, "prompt_hash": prompt_hash}, name)

    def test_storyboard_is_one_editable_run_artifact(self):
        brief = self._write_brief(self._brief())
        self._run(SimpleNamespace(brief=str(brief), run_id="video-run-001", visual_review=None))
        run = self.wiki / "creative-runs" / "video-run-001"
        index = (run / "index.md").read_text()
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertTrue(index.startswith("<!-- bob-video-storyboard -->"))
        self.assertIn("high-risk action; inspect closely", index)
        self.assertEqual(manifest["status"], "storyboard_ready")
        self.assertIn("creative-runs/video-run-001/index.md", (self.wiki / "Index.md").read_text())

    def test_prompt_uses_saved_storyboard_after_a_small_confirmed_brief(self):
        board = self._write_brief(self._scene_brief(), "saved-board.json")
        self._run(SimpleNamespace(brief=str(board), run_id="saved-run", visual_review=None))
        run = self.wiki / "creative-runs" / "saved-run"
        original = json.loads((run / "manifest.json").read_text())
        direction = {"stage": "prompt", "confirmed": True, "video_prompt": "Keep the arrival calm.", "accepted_omissions": ["timing", "music"]}
        unapproved = self._write_brief({**direction, "confirmed": False}, "unapproved-prompt.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(unapproved), run_id="saved-run", visual_review=None))
        missing_approval = self._write_brief({**direction, "accepted_omissions": []}, "missing-guidance-approval.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(missing_approval), run_id="saved-run", visual_review=None))
        prompt = self._write_brief(direction, "small-prompt.json")
        self._run(SimpleNamespace(brief=str(prompt), run_id="saved-run", visual_review=None))
        updated = json.loads((run / "manifest.json").read_text())
        index = (run / "index.md").read_text()
        self.assertEqual(updated["storyboard_hash"], original["storyboard_hash"])
        self.assertEqual(updated["status"], "prompt_ready")
        self.assertIn("<FIRST_FRAME>@Image1", updated["generation_prompt"])
        self.assertIn("<IMAGE_REF_0>@Image2", updated["generation_prompt"])
        self.assertIn("Captain arrives beside customer", updated["generation_prompt"])
        self.assertIn("chai-stall ambience", updated["generation_prompt"])
        self.assertNotIn("Music or jingle timing", updated["generation_prompt"])
        self.assertNotIn("natural pacing guidance", updated["generation_prompt"])
        displayed = json.loads(index.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(displayed, {"type": "text", "text": updated["generation_prompt"]})
        self.assertEqual(sorted(path.name for path in run.glob("*.md")), ["index.md"])

    def test_prompt_blocks_a_board_with_no_timing_sound_or_music_decision(self):
        board = self._write_brief(self._scene_brief(sfx=[], music={}), "silent-board.json")
        self._run(SimpleNamespace(brief=str(board), run_id="silent-run", visual_review=None))
        prompt = {"stage": "prompt", "confirmed": True, "video_prompt": "Keep the scene continuous."}
        without_waiver = self._write_brief(prompt, "silent-prompt.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(without_waiver), run_id="silent-run", visual_review=None))
        manifest_path = self.wiki / "creative-runs" / "silent-run" / "manifest.json"
        self.assertEqual(json.loads(manifest_path.read_text())["status"], "storyboard_ready")
        waived = self._write_brief({**prompt, "accepted_omissions": ["timing", "sfx", "music"]}, "silent-approved.json")
        self._run(SimpleNamespace(brief=str(waived), run_id="silent-run", visual_review=None))
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["accepted_omissions"], ["timing", "sfx", "music"])
        self.assertIn("Accepted storyboard omissions", (manifest_path.parent / "index.md").read_text())
        manifest.pop("accepted_omissions")
        manifest_path.write_text(json.dumps(manifest))
        legacy_master = self._write_brief({**self._scene_brief(sfx=[], music={}), "stage": "master", "confirmed": True,
                                           "prompt_confirmed": True, "video_prompt": prompt["video_prompt"],
                                           "prompt_hash": manifest["prompt_hash"]}, "legacy-master.json")
        video_caller = Mock()
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(legacy_master), run_id="silent-run", visual_review=None), caller=video_caller)
        video_caller.assert_not_called()

    def test_master_snapshots_only_confirmed_storyboard_then_requires_visual_review(self):
        storyboard = self._write_brief(self._brief())
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-002", visual_review=None))
        master_value = self._brief(
            source_image=str(self.source),
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        )
        unapproved = self._write_brief({**master_value, "stage": "master", "confirmed": True}, "unapproved.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(unapproved), run_id="video-run-002", visual_review=None))
        master = self._approved_master("video-run-002", master_value)
        index = (self.wiki / "creative-runs" / "video-run-002" / "index.md").read_text()
        self.assertIn("Omni text input for approval", index)
        self.assertIn('"type": "text"', index)
        self.assertIn("Captain arrives beside customer", index)
        self.assertIn("Chai order", index)
        stale = self._write_brief({**json.loads(master.read_text()), "prompt_hash": "stale"}, "stale.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=str(stale), run_id="video-run-002", visual_review=None))
        def fake_video(*_): return b"video", "video/mp4", "interaction-001"
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "render_overlay"), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            self._run(
                SimpleNamespace(brief=str(master), run_id="video-run-002", visual_review=None),
                caller=fake_video,
                image_caller=lambda *_: (png_bytes(), "image/png"),
            )
        run = self.wiki / "creative-runs" / "video-run-002"
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "video_review_pending")
        self.assertTrue((run / manifest["approved_brief"]).is_file())
        self.assertEqual(manifest["master_checkpoint"]["interaction_id"], "interaction-001")
        self.assertNotIn("secret", (run / "details" / "master-9x16-v1.md").read_text())
        silent_review = self._write_brief({"reviews": [{
            "name": "master-9x16-v1.mp4", "checks": {name: "passed" for name in video.VIDEO_REVIEW_CHECKS}, "issues": [],
        }]}, "silent-review.json")
        with self.assertRaises(SystemExit):
            self._run(SimpleNamespace(brief=None, run_id="video-run-002", visual_review=str(silent_review)))
        review = self._write_brief({"reviews": [{
            "name": "master-9x16-v1.mp4",
            "checks": {name: "passed" for name in video.VIDEO_REVIEW_CHECKS},
            "audio_listened": True,
            "audio_notes": "Both speakers and the full soundtrack were audible and matched the storyboard.",
            "issues": [],
        }]}, "review.json")
        self._run(SimpleNamespace(brief=None, run_id="video-run-002", visual_review=str(review)))
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "video_master_ready")

    def test_every_scene_panel_and_native_jingle_reach_the_approved_prompt(self):
        brief = self._brief(music={"direction": "Whisper the hook, then sing it softly", "lyrics": "Chai se pehle ride.", "timing": "approximately 4.1–6.0s"})
        brief["panels"][0]["timing"] = "[0–2s]"
        brief["panels"][0]["sfx"] = ["tea cups clink"]
        brief["panels"][1]["timing"] = "[2–3.5s]"
        brief["panels"][1]["sfx"] = ["bike brakes softly"]
        brief["panels"].insert(2, {
            "title": "Reaction", "timing": "[3.5–4.8s]", "visual": "Customer gives a restrained smile.",
            "camera": "Hold a two-shot.", "kind": "scene",
        })
        storyboard = self._write_brief(brief, "three-panel-board.json")
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-panels", visual_review=None))
        master = self._approved_master("video-run-panels", {**brief, "video_prompt": "One continuous chai-stall scene."}, "three-panel-master.json")
        run = self.wiki / "creative-runs" / "video-run-panels"
        index = (run / "index.md").read_text()
        self.assertIn("<FIRST_FRAME>@Image1", index)
        self.assertIn("<IMAGE_REF_0>@Image2", index)
        self.assertIn("<IMAGE_REF_1>@Image3", index)
        self.assertIn("Customer gives a restrained smile", index)
        self.assertIn("Exact sung words: Chai se pehle ride.", index)
        prompt_text = json.loads(index.split("```json\n", 1)[1].split("\n```", 1)[0])["text"]
        self.assertLess(prompt_text.index("[# Sources"), prompt_text.index("One continuous chai-stall scene."))
        self.assertLess(prompt_text.index("Scene 1 [0–2s]: Use Image1 (<FIRST_FRAME>)"), prompt_text.index("Scene 2 [2–3.5s]: Use Image2 (<IMAGE_REF_0>)"))
        self.assertLess(prompt_text.index("tea cups clink"), prompt_text.index("Scene 2 [2–3.5s]"))
        self.assertLess(prompt_text.index("bike brakes softly"), prompt_text.index("Scene 3 [3.5–4.8s]"))
        self.assertLess(prompt_text.index("Scene 3 [3.5–4.8s]"), prompt_text.index("Music: Whisper the hook"))
        self.assertIn("Music or jingle timing: approximately 4.1–6.0s", prompt_text)
        self.assertIn("final card will be added in finishing from approximately 4.8s", prompt_text)
        self.assertIn("keep the generated audio continuous through it", prompt_text)
        self.assertIn("natural pacing guidance, not forced cuts", prompt_text)
        self.assertLess(prompt_text.index("final card will be added"), prompt_text.index("Music: Whisper the hook"))
        caller = Mock(return_value=(b"video", "video/mp4", "interaction-panels"))
        music_caller = Mock()
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            self._run(SimpleNamespace(brief=str(master), run_id="video-run-panels", visual_review=None), caller=caller, music_caller=music_caller)
        self.assertEqual(len(caller.call_args.args[3]), 3)
        music_caller.assert_not_called()
        manifest = json.loads((run / "manifest.json").read_text())
        displayed = json.loads(index.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(displayed, {"type": "text", "text": caller.call_args.args[2]})
        self.assertEqual(manifest["candidates"][-1]["request"]["input_text"], displayed)
        self.assertEqual(manifest["candidates"][-1]["request"]["image_roles"], ["FIRST_FRAME", "IMAGE_REF_0", "IMAGE_REF_1"])

    def test_audio_revision_reuses_unchanged_storyboard_images(self):
        initial = self._scene_brief(storyboard_fidelity="high_fidelity", music={"direction": "soft instrumental"})
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        first = self._write_brief(initial, "initial-board.json")
        self._run(SimpleNamespace(brief=str(first), run_id="video-run-audio", visual_review=None), image_caller=image_caller)
        self.assertEqual(image_caller.call_count, 2)
        revised = self._write_brief({**initial, "music": {"direction": "whisper then sung hook", "lyrics": "Chai se pehle ride"}}, "revised-board.json")
        self._run(SimpleNamespace(brief=str(revised), run_id="video-run-audio", visual_review=None), image_caller=image_caller)
        self.assertEqual(image_caller.call_count, 2)

    def test_visual_revision_uses_saved_interaction_id(self):
        brief = self._scene_brief(video_prompt="A continuous chai-stall scene.")
        storyboard = self._write_brief(brief, "edit-board.json")
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-edit", visual_review=None))
        first = self._approved_master("video-run-edit", brief, "edit-first.json")
        caller = Mock(side_effect=[(b"first", "video/mp4", "interaction-first"), (b"second", "video/mp4", "interaction-second")])
        def fake_finish(_source, output, **_kwargs):
            output.write_bytes(b"finished")
            return {"integrity": "passed"}
        with patch.object(video, "finish_video", side_effect=fake_finish):
            self._run(SimpleNamespace(brief=str(first), run_id="video-run-edit", visual_review=None), caller=caller)
            revision = self._approved_master("video-run-edit", {**brief, "video_prompt": "Make the reaction a small smile. Keep the rest the same.", "edit_from": "master-9x16-v1.mp4"}, "edit-second.json")
            self._run(SimpleNamespace(brief=str(revision), run_id="video-run-edit", visual_review=None), caller=caller)
        self.assertEqual(caller.call_args.args[5], "interaction-first")
        manifest = json.loads((self.wiki / "creative-runs" / "video-run-edit" / "manifest.json").read_text())
        self.assertEqual(manifest["candidates"][-1]["name"], "master-9x16-v2.mp4")
        self.assertEqual(manifest["candidates"][-1]["interaction_id"], "interaction-second")
        self.assertEqual(manifest["candidates"][-1]["request"]["edited_from"], "master-9x16-v1.mp4")

    def test_master_retry_reuses_provider_checkpoints_after_finishing_failure(self):
        storyboard = self._write_brief(self._scene_brief(music={"provider": "lyria", "direction": "warm instrumental"}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-resume", visual_review=None))
        master = self._approved_master("video-run-resume", self._scene_brief(
            source_image=str(self.source),
            music={"provider": "lyria", "direction": "warm instrumental"},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "resume.json")
        video_caller = Mock(return_value=(b"video", "video/mp4", "interaction-resume"))
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        music_caller = Mock(return_value=(b"audio", "audio/mpeg"))
        with patch.object(video, "finish_video", side_effect=ValueError("ffmpeg failed")):
            with self.assertRaisesRegex(ValueError, "ffmpeg failed"):
                self._run(
                    SimpleNamespace(brief=str(master), run_id="video-run-resume", visual_review=None),
                    caller=video_caller, image_caller=image_caller, music_caller=music_caller,
                )
        run = self.wiki / "creative-runs" / "video-run-resume"
        checkpointed = json.loads((run / "manifest.json").read_text())
        self.assertEqual(checkpointed["status"], "master_checkpointed")
        self.assertTrue((run / checkpointed["master_checkpoint"]["raw_video"]).is_file())
        self.assertTrue((run / checkpointed["master_checkpoint"]["music"]).is_file())

        with patch.object(video, "validate_video", return_value={"integrity": "passed"}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            self._run(
                SimpleNamespace(brief=str(master), run_id="video-run-resume", visual_review=None),
                caller=video_caller, image_caller=image_caller, music_caller=music_caller,
            )
        resumed = json.loads((run / "manifest.json").read_text())
        self.assertEqual(resumed["status"], "video_review_pending")
        self.assertEqual(video_caller.call_count, 1)
        self.assertEqual(image_caller.call_count, 0)
        self.assertEqual(music_caller.call_count, 1)

    def test_checkpointed_finishing_does_not_require_provider_configuration(self):
        storyboard = self._write_brief(self._scene_brief(music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-offline-finish", visual_review=None))
        master = self._approved_master("video-run-offline-finish", self._scene_brief(
            source_image=str(self.source),
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "offline-finish.json")
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "finish_video", side_effect=ValueError("ffmpeg failed")):
            with self.assertRaisesRegex(ValueError, "ffmpeg failed"):
                self._run(SimpleNamespace(brief=str(master), run_id="video-run-offline-finish", visual_review=None), caller=lambda *_: (b"video", "video/mp4", "interaction-offline"), image_caller=lambda *_: (png_bytes(), "image/png"))
        with patch.dict(os.environ, {"BOB_SELECTED_CUSTOMER_ID": self.customer}, clear=True), \
             patch.object(video, "STATE_ROOT", self.root), \
             patch.object(video, "account_wiki_dir", lambda _: self.wiki), \
             patch.object(video, "validate_video", return_value={"integrity": "passed"}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            video.create_video(SimpleNamespace(brief=str(master), run_id="video-run-offline-finish", visual_review=None))

    def test_music_policy_block_preserves_video_and_requests_a_new_direction(self):
        storyboard = self._write_brief(self._scene_brief(music={"provider": "lyria", "direction": "upbeat instrumental"}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-music-policy", visual_review=None))
        master = self._approved_master("video-run-music-policy", self._scene_brief(
            source_image=str(self.source),
            music={"provider": "lyria", "direction": "upbeat instrumental"},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "music-policy.json")
        video_caller = Mock(return_value=(b"video", "video/mp4", "interaction-music"))
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        with self.assertRaises(SystemExit):
            self._run(
                SimpleNamespace(brief=str(master), run_id="video-run-music-policy", visual_review=None),
                caller=video_caller,
                image_caller=image_caller,
                music_caller=lambda *_: (_ for _ in ()).throw(video.ProviderPolicyBlocked("music", "Use a different music direction.")),
            )
        run = self.wiki / "creative-runs" / "video-run-music-policy"
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "music_direction_needed")
        self.assertTrue((run / manifest["master_checkpoint"]["raw_video"]).is_file())
        self.assertEqual(manifest["provider_policy"]["message"], "Use a different music direction.")
        self.assertIn("Direction revision needed", (run / "index.md").read_text())
        revised_board = self._write_brief(self._scene_brief(music={"provider": "lyria", "direction": "calm instrumental"}), "music-revised-board.json")
        self._run(SimpleNamespace(brief=str(revised_board), run_id="video-run-music-policy", visual_review=None))
        revised = self._approved_master("video-run-music-policy", {**json.loads(master.read_text()), "music": {"provider": "lyria", "direction": "calm instrumental"}}, "music-revised.json")
        with patch.object(video, "validate_video", return_value={"integrity": "passed"}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            self._run(
                SimpleNamespace(brief=str(revised), run_id="video-run-music-policy", visual_review=None),
                caller=video_caller, image_caller=image_caller,
                music_caller=lambda *_: (b"audio", "audio/mpeg"),
            )
        self.assertEqual(video_caller.call_count, 1)
        self.assertEqual(image_caller.call_count, 0)

    def test_video_policy_block_preserves_motion_plate_and_requests_a_new_direction(self):
        storyboard = self._write_brief(self._scene_brief(music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-video-policy", visual_review=None))
        master = self._approved_master("video-run-video-policy", self._scene_brief(
            source_image=str(self.source),
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "video-policy.json")
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        video_caller = Mock(side_effect=[
            video.ProviderPolicyBlocked("video", "Use a different video direction."),
            (b"video", "video/mp4", "interaction-video"),
        ])
        with self.assertRaises(SystemExit):
            self._run(
                SimpleNamespace(brief=str(master), run_id="video-run-video-policy", visual_review=None),
                caller=video_caller,
                image_caller=image_caller,
            )
        run = self.wiki / "creative-runs" / "video-run-video-policy"
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "video_direction_needed")
        self.assertTrue((run / "references" / "storyboard-panel-1.png").is_file())
        self.assertFalse((run / manifest["master_checkpoint"]["raw_video"]).exists())
        self.assertEqual(manifest["provider_policy"]["message"], "Use a different video direction.")
        revised = self._approved_master("video-run-video-policy", {**json.loads(master.read_text()), "video_prompt": "The Captain arrives in one continuous full-frame scene."}, "video-revised.json")
        with patch.object(video, "validate_video", return_value={"integrity": "passed"}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            self._run(
                SimpleNamespace(brief=str(revised), run_id="video-run-video-policy", visual_review=None),
                caller=video_caller, image_caller=image_caller,
            )
        self.assertEqual(image_caller.call_count, 0)
        self.assertEqual(video_caller.call_count, 2)

    def test_landscape_adaptation_requires_reviewed_master(self):
        run = self.wiki / "creative-runs" / "video-run-003"; (run / "outputs").mkdir(parents=True)
        (run / "outputs" / "master-9x16-v1.mp4").write_bytes(b"video")
        manifest = {
            "run_id": "video-run-003", "customer_id": self.customer, "status": "video_master_ready",
            "storyboard": {"duration_seconds": 6, "aspect_ratio": "9:16", "sections": [], "copy": {}, "sfx": [], "music": {}},
            "candidates": [{"name": "master-9x16-v1.mp4", "candidate_type": "video_master", "review_status": "passed"}],
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        brief = self._write_brief({"stage": "adaptation", "confirmed": True, "master_name": "master-9x16-v1.mp4"}, "adapt.json")
        with patch.object(video, "adapt_portrait_to_landscape", return_value={"integrity": "passed"}):
            self._run(SimpleNamespace(brief=str(brief), run_id="video-run-003", visual_review=None))
        output = self.wiki / "creative-runs" / "video-run-003" / "outputs" / "adapt-16x9-v1.mp4"
        self.assertFalse(output.exists())
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "video_review_pending")
        self.assertEqual(manifest["candidates"][-1]["production_method"], "ffmpeg_adaptation")

    def test_omni_request_uses_catalog_duration_not_a_provider_parameter(self):
        captured = {}

        class Response:
            def read(self):
                return json.dumps({"id": "interaction-request", "steps": [{"content": [{"mime_type": "video/mp4", "data": b64encode(b"video").decode()}]}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return Response()

        with patch.object(video, "urlopen", fake_urlopen):
            payload, mime, interaction_id = video._call_omni("secret", "gemini-omni-1.1-flash", "animate this", [self.source, self.source, self.source], "9:16")
        self.assertEqual((payload, mime, interaction_id), (b"video", "video/mp4", "interaction-request"))
        self.assertEqual(captured["body"]["response_format"], {"type": "video", "aspect_ratio": "9:16"})
        self.assertNotIn("duration_seconds", captured["body"]["response_format"])
        self.assertEqual([item["type"] for item in captured["body"]["input"]], ["image", "image", "image", "text"])
        self.assertEqual(captured["body"]["input"][-1], {"type": "text", "text": "animate this"})
        self.assertTrue(captured["body"]["store"])

    def test_video_duration_is_provider_native(self):
        brief = self._brief(duration_seconds=8)
        with self.assertRaises(SystemExit):
            video._video_duration(brief)

    def test_music_uses_the_registered_lyria_clip_model(self):
        self.assertEqual(video._model("music", {}), "lyria-3-clip-preview")

    def test_lyria_clip_request_uses_the_documented_default_mp3_response(self):
        captured = {}

        class Response:
            def read(self):
                return json.dumps({"steps": [{"content": [{"type": "audio", "data": b64encode(b"audio").decode()}]}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            return Response()

        with patch.object(video, "urlopen", fake_urlopen):
            payload, mime = video._call_lyria("secret", "lyria-3-clip-preview", "warm instrumental")
        self.assertEqual((payload, mime), (b"audio", "audio/mpeg"))
        self.assertEqual(captured["body"], {
            "model": "lyria-3-clip-preview",
            "input": [{"type": "text", "text": "warm instrumental"}],
        })

    def test_master_uses_approved_panels_for_native_dialogue_and_end_card(self):
        storyboard = self._write_brief(self._brief(end_card={"start_seconds": 4.5}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-clean-plate", visual_review=None))
        master = self._approved_master("video-run-clean-plate", self._brief(
            source_image=str(self.source),
            video_prompt="One continuous full-frame Captain arrival.",
            end_card={"start_seconds": 4.5},
        ), "clean-plate.json")
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        video_caller = Mock(return_value=(b"video", "video/mp4", "interaction-clean"))
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}) as finish:
            self._run(SimpleNamespace(brief=str(master), run_id="video-run-clean-plate", visual_review=None), caller=video_caller, image_caller=image_caller)
        self.assertEqual([path.name for path in video_caller.call_args.args[3]], ["storyboard-panel-1.png", "storyboard-panel-2.png"])
        self.assertIsNone(video_caller.call_args.args[5])
        self.assertEqual(finish.call_args.kwargs["overlay_start_seconds"], 4.5)
        self.assertNotIn('"tts_model"', (self.wiki / "creative-runs" / "video-run-clean-plate" / "details" / "master-9x16-v1.md").read_text())

    def test_finishing_never_uses_visual_duration_cutoff(self):
        raw_qa = {"integrity": "passed"}
        output_qa = {"integrity": "passed"}
        with patch.object(video_media, "validate_video", side_effect=[raw_qa, output_qa]), \
             patch.object(video_media, "_binary", side_effect=lambda name: name), \
             patch.object(video_media, "_run") as run:
            result = video_media.finish_video(
                Path("raw.mp4"), Path("output.mp4"), duration_seconds=6, aspect_ratio="9:16",
                music=Path("music.mp3"), overlay=Path("overlay.png"),
            )
        argv = run.call_args.args[0]
        self.assertEqual(result, output_qa)
        self.assertNotIn("-t", argv)
        self.assertNotIn("-shortest", argv)
        self.assertIn("overlay=0:0:enable='gte(t,0)':shortest=1", " ".join(argv))
        self.assertIn("sidechaincompress", " ".join(argv))
        self.assertIn("apad=whole_dur=6,atrim=duration=6", " ".join(argv))
        self.assertIn("-preset", argv)
        self.assertEqual(argv[argv.index("-preset") + 1], "veryfast")

    def test_finishing_ducks_music_below_native_omni_audio(self):
        with patch.object(video_media, "validate_video", side_effect=[{"integrity": "passed"}, {"integrity": "passed"}]), \
             patch.object(video_media, "_binary", side_effect=lambda name: name), \
             patch.object(video_media, "_run") as run:
            video_media.finish_video(
                Path("raw.mp4"), Path("output.mp4"), duration_seconds=6, aspect_ratio="9:16",
                music=Path("music.mp3"),
            )
        graph = " ".join(run.call_args.args[0])
        self.assertIn("sidechaincompress", graph)
        self.assertIn("amix=inputs=2:duration=first", graph)

    def test_final_card_keeps_native_audio_when_no_extra_music_is_requested(self):
        with patch.object(video_media, "validate_video", side_effect=[{"integrity": "passed"}, {"integrity": "passed"}]), \
             patch.object(video_media, "_binary", side_effect=lambda name: name), \
             patch.object(video_media, "_run") as run:
            video_media.finish_video(Path("raw.mp4"), Path("output.mp4"), duration_seconds=6,
                                     aspect_ratio="9:16", overlay=Path("card.png"), overlay_start_seconds=4.8)
        argv = run.call_args.args[0]
        self.assertIn("0:a?", argv)
        self.assertIn("overlay=0:0:enable='gte(t,4.8)':shortest=1", " ".join(argv))
        self.assertNotIn("-t", argv)
