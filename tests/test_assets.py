import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.assets import (
    AssetValidationError,
    detect_media,
    resolve_asset_path,
    safe_original_name,
    store_upload,
)


async def chunks(*values: bytes):
    for value in values:
        yield value


class AssetStorageTests(unittest.TestCase):
    def test_detects_only_supported_media_signatures(self):
        self.assertEqual(detect_media(b"\x89PNG\r\n\x1a\nrest"), ("image/png", ".png"))
        self.assertEqual(detect_media(b"\xff\xd8\xffrest"), ("image/jpeg", ".jpg"))
        self.assertEqual(detect_media(b"RIFF0000WEBPrest"), ("image/webp", ".webp"))
        self.assertEqual(detect_media(b"0000ftypisom"), ("video/mp4", ".mp4"))
        self.assertIsNone(detect_media(b"plain text"))

    def test_upload_uses_safe_name_and_content_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stored = asyncio.run(store_upload(
                chunks(b"\x89PNG\r\n", b"\x1a\ncontent"), root, "client-1", "asset-1", "../bad\x00name.png"
            ))
            self.assertEqual(stored.original_name, "badname.png")
            self.assertEqual(stored.media_type, "image/png")
            self.assertEqual((root / stored.storage_relpath).read_bytes(), b"\x89PNG\r\n\x1a\ncontent")

    def test_invalid_upload_is_removed_and_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(AssetValidationError):
                asyncio.run(store_upload(chunks(b"not media"), root, "client-1", "asset-1", "x.txt"))
            self.assertFalse((root / "client-assets" / "client-1" / "asset-1").exists())
            self.assertIsNone(resolve_asset_path(root, "../outside.png"))

    def test_declared_oversize_is_rejected_before_creating_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(AssetValidationError) as raised:
                asyncio.run(store_upload(
                    chunks(b"unused"), root, "client-1", "asset-1", "x.png", 101 * 1024 * 1024
                ))
            self.assertEqual(raised.exception.status_code, 413)
            self.assertFalse((root / "client-assets").exists())

    def test_streamed_oversize_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary, patch("server.assets.MAX_UPLOAD_BYTES", 8):
            root = Path(temporary)
            with self.assertRaises(AssetValidationError) as raised:
                asyncio.run(store_upload(
                    chunks(b"\x89PNG\r\n\x1a\n", b"extra"), root, "client-1", "asset-1", "x.png"
                ))
            self.assertEqual(raised.exception.status_code, 413)
            self.assertFalse((root / "client-assets" / "client-1" / "asset-1").exists())


if __name__ == "__main__":
    unittest.main()
