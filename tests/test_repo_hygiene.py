import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_container_build_generates_bob_launcher(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text()
        self.assertIn("_write_bob_launcher", dockerfile)
        self.assertIn('if [ ! -x "$APP_ROOT/bob" ]', entrypoint)

    def test_local_runtime_paths_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        for rule in ("data/", "tmp/", "*.sqlite3"):
            self.assertIn(rule, ignored)

    def test_local_credentials_and_runtime_data_are_not_tracked(self):
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True
        ).splitlines()
        forbidden_prefixes = ("data/", "tmp/")
        forbidden_names = (".env", "secrets", "metadata.sqlite3")
        bad = [
            path for path in tracked
            if path.startswith(forbidden_prefixes)
            or (path != ".env.example"
                and any(name in Path(path).name.lower() for name in forbidden_names))
        ]
        self.assertEqual(bad, [], f"local runtime or credential files are tracked: {bad}")

    def test_client_specific_fixture_names_are_absent_from_tracked_text(self):
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True
        ).splitlines()
        needles = (
            "rapido",
            "354-692-3408",
            "3546923408",
            "302-172-2615",
            "3021722615",
            "996-177-7147",
            "9961777147",
            "35-252-7237",
            "352527237",
        )
        matches = []
        for relative in tracked:
            if relative == "tests/test_repo_hygiene.py":
                continue
            path = ROOT / relative
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if any(needle in line.lower() for needle in needles):
                    matches.append(f"{relative}:{line_number}")
        self.assertEqual(matches, [], f"client-specific content is tracked: {matches}")


if __name__ == "__main__":
    unittest.main()
