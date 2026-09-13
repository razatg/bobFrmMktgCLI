"""Public CLI contract tests for the datapull decomposition."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import datapull as dp  # noqa: E402


EXPECTED_HANDLERS = {
    "fetch": "fetch",
    "bootstrap": "bootstrap",
    "log-pull": "log_pull_cmd",
    "log-signal": "log_signal_cmd",
    "session-debrief": "session_debrief",
    "self-improve": "self_improve",
    "aggregate": "aggregate",
    "validate-manual": "validate_manual",
    "check-config": "check_config",
    "compare-weeks": "compare_weeks",
    "compare-months": "compare_months",
    "slice-campaigns": "slice_campaigns",
    "data-manifest": "data_manifest",
    "slice-creatives": "slice_creatives",
    "suggest-creative-copy": "suggest_creative_copy",
    "suggest-static-banners": "suggest_static_banners",
    "suggest-static-variants": "suggest_static_variants",
    "static-variants-apply": "static_variants_apply",
    "creative-copy-apply": "creative_copy_apply",
    "bid-budget-recommend": "bid_budget_recommend",
    "bid-budget-apply": "bid_budget_apply",
    "bid-budget-retrospective": "bid_budget_retrospective",
    "resolve-dates": "cmd_resolve_dates",
    "setup-write-credentials": "setup_write_credentials",
    "onboard": "onboard",
    "switch-account": "switch_account",
    "list-accounts": "list_accounts",
    "repair-setup": "repair_setup",
    "sync": "sync",
    "snapshot-pull": "snapshot_pull",
}


def command_parsers():
    parser = dp.build_parser()
    subcommands = next(action for action in parser._actions if action.dest == "command")
    return parser, subcommands.choices


class CliContractTests(unittest.TestCase):
    def test_complete_command_set_and_handler_routing(self):
        _, commands = command_parsers()
        self.assertEqual(set(commands), set(EXPECTED_HANDLERS))
        for command, handler in EXPECTED_HANDLERS.items():
            self.assertEqual(commands[command].get_default("func").__name__, handler)

    def test_representative_defaults_and_choices_remain_stable(self):
        parser, _ = command_parsers()
        fetch = parser.parse_args(["fetch", "--query", "campaign_daily"])
        self.assertEqual((fetch.days, fetch.force, fetch.quiet), (None, False, False))

        compare = parser.parse_args(["compare-weeks"])
        self.assertEqual((compare.grain, compare.summary, compare.top), ("both", False, 10))

        partial = parser.parse_args(["resolve-dates", "--period", "partial-wow"])
        self.assertEqual(partial.n, 3)

        onboard = parser.parse_args(["onboard", "--dry-run"])
        self.assertTrue(onboard.dry_run)
        self.assertFalse(onboard.interactive)

        sync = parser.parse_args(["sync"])
        self.assertEqual((sync.pull, sync.push, sync.dry_run), (False, False, False))

    def test_datapull_remains_a_direct_executable(self):
        environment = dict(os.environ)
        environment["BOB_TODAY"] = "2026-06-18"
        result = subprocess.run(
            [sys.executable, str(ROOT / "lib" / "datapull.py"), "resolve-dates", "--period", "yesterday"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2026-06-17", result.stdout)

    def test_no_argument_output_remains_the_command_map(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "lib" / "datapull.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, dp._COMMAND_MAP)

    def test_generated_launcher_still_targets_the_facade(self):
        launcher = (ROOT / "bob").read_text()
        self.assertIn('python "$DIR/lib/datapull.py" "$@"', launcher)


if __name__ == "__main__":
    unittest.main()
