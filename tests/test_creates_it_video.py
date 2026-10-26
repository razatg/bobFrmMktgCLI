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
            "panels": [
                {"title": "Chai order", "visual": "Customer at the chai stall.", "camera": "Stable portrait frame.", "speaker": "Customer", "voice": "adult Indian male voice", "dialogue": "Bhaiya, ek chai dena.", "kind": "scene"},
                {"title": "Captain arrives", "visual": "Captain arrives beside customer.", "camera": "Keep both men readable.", "speaker": "Captain", "voice": "adult Indian male voice", "dialogue": "Sir, aapki Rapido.", "kind": "scene"},
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

    def _run(self, args, **kwargs):
        with patch.dict(os.environ, self.env, clear=False), \
             patch.object(video, "STATE_ROOT", self.root), \
             patch.object(video, "account_wiki_dir", lambda _: self.wiki):
            video.create_video(args, **kwargs)

    def test_storyboard_is_one_editable_run_artifact(self):
        brief = self._write_brief(self._brief())
        self._run(SimpleNamespace(brief=str(brief), run_id="video-run-001", visual_review=None))
        run = self.wiki / "creative-runs" / "video-run-001"
        index = (run / "index.md").read_text()
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertTrue(index.startswith("<!-- bob-video-storyboard -->"))
        self.assertIn("isolated controlled clip", index)
        self.assertEqual(manifest["status"], "storyboard_ready")
        self.assertIn("creative-runs/video-run-001/index.md", (self.wiki / "Index.md").read_text())

    def test_master_snapshots_only_confirmed_storyboard_then_requires_visual_review(self):
        storyboard = self._write_brief(self._brief())
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-002", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source),
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "master.json")
        def fake_video(*_): return b"video", "video/mp4"
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
        self.assertNotIn("secret", (run / "details" / "master-9x16-v1.md").read_text())
        review = self._write_brief({"reviews": [{
            "name": "master-9x16-v1.mp4",
            "checks": {name: "passed" for name in video.VIDEO_REVIEW_CHECKS},
            "issues": [],
        }]}, "review.json")
        self._run(SimpleNamespace(brief=None, run_id="video-run-002", visual_review=str(review)))
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "video_master_ready")

    def test_master_retry_reuses_provider_checkpoints_after_finishing_failure(self):
        storyboard = self._write_brief(self._brief(copy={}, music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-resume", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source), copy={},
            music={"direction": "warm instrumental"},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "resume.json")
        video_caller = Mock(return_value=(b"video", "video/mp4"))
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
        storyboard = self._write_brief(self._brief(copy={}, music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-offline-finish", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source), copy={},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "offline-finish.json")
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "finish_video", side_effect=ValueError("ffmpeg failed")):
            with self.assertRaisesRegex(ValueError, "ffmpeg failed"):
                self._run(SimpleNamespace(brief=str(master), run_id="video-run-offline-finish", visual_review=None), caller=lambda *_: (b"video", "video/mp4"), image_caller=lambda *_: (png_bytes(), "image/png"))
        with patch.dict(os.environ, {"BOB_SELECTED_CUSTOMER_ID": self.customer}, clear=True), \
             patch.object(video, "STATE_ROOT", self.root), \
             patch.object(video, "account_wiki_dir", lambda _: self.wiki), \
             patch.object(video, "validate_video", return_value={"integrity": "passed"}), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}):
            video.create_video(SimpleNamespace(brief=str(master), run_id="video-run-offline-finish", visual_review=None))

    def test_music_policy_block_preserves_video_and_requests_a_new_direction(self):
        storyboard = self._write_brief(self._brief(copy={}, music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-music-policy", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source), copy={},
            music={"direction": "upbeat instrumental"},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "music-policy.json")
        video_caller = Mock(return_value=(b"video", "video/mp4"))
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
        revised = self._write_brief({**json.loads(master.read_text()), "music": {"direction": "calm instrumental"}}, "music-revised.json")
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
        storyboard = self._write_brief(self._brief(copy={}, music={}))
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-video-policy", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source), copy={},
            video_prompt="The commuter notices a stationary Captain at a chai stall.",
        ), "video-policy.json")
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        video_caller = Mock(side_effect=[
            video.ProviderPolicyBlocked("video", "Use a different video direction."),
            (b"video", "video/mp4"),
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
        revised = self._write_brief({**json.loads(master.read_text()), "video_prompt": "The Captain arrives in one continuous full-frame scene."}, "video-revised.json")
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
                return json.dumps({"steps": [{"content": [{"mime_type": "video/mp4", "data": b64encode(b"video").decode()}]}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return Response()

        with patch.object(video, "urlopen", fake_urlopen):
            payload, mime = video._call_omni("secret", "gemini-omni-1.1-flash", "animate this", self.source, "9:16")
        self.assertEqual((payload, mime), (b"video", "video/mp4"))
        self.assertEqual(captured["body"]["response_format"], {"type": "video", "aspect_ratio": "9:16"})
        self.assertNotIn("duration_seconds", captured["body"]["response_format"])

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
        storyboard = self._write_brief(self._brief())
        self._run(SimpleNamespace(brief=str(storyboard), run_id="video-run-clean-plate", visual_review=None))
        master = self._write_brief(self._brief(
            stage="master", confirmed=True, source_image=str(self.source),
            video_prompt="One continuous full-frame Captain arrival.",
            end_card={"start_seconds": 4.5},
        ), "clean-plate.json")
        image_caller = Mock(return_value=(png_bytes(), "image/png"))
        video_caller = Mock(return_value=(b"video", "video/mp4"))
        with patch.object(video, "probe_video", return_value={"streams": [{"codec_type": "video", "width": 720, "height": 1280}]}), \
             patch.object(video, "render_overlay"), \
             patch.object(video, "finish_video", return_value={"integrity": "passed"}) as finish:
            self._run(SimpleNamespace(brief=str(master), run_id="video-run-clean-plate", visual_review=None), caller=video_caller, image_caller=image_caller)
        self.assertEqual(video_caller.call_args.args[3].name, "storyboard-panel-1.png")
        self.assertEqual(video_caller.call_args.args[5].name, "storyboard-panel-2.png")
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
