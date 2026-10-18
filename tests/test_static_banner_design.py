"""Account design evidence validation and rendering tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib.bob.static_banners import analyze


def complete_strategy() -> dict:
    return {
        "status": "complete",
        "image_inspected_count": 1,
        "raw_asset_count": 2,
        "unique_image_count": 1,
        "creative_observations": [{
            "asset_id": "asset-1",
            "visual_description": "A violet product card on a cream field.",
            "composition": "Product left, short claim right, with generous outer margins.",
            "hierarchy": "Product, claim, logo, then action.",
            "typography": "Heavy geometric headline with a smaller regular supporting line.",
            "palette": "Cream background, violet primary, orange accent.",
            "product_treatment": "The product is isolated as the dominant proof object.",
            "logo_treatment": "Small logo in the upper-right clear area.",
            "copy_density": "One four-word headline and one two-word action.",
            "safe_area": "Outer ten percent remains free of text and branding.",
            "ratio_adaptation": "The square layout depends on balanced left-right zones.",
            "message_cta": "Benefit claim followed by a compact action label.",
            "evidence_note": "Direct observation from asset-1; recurrence is not established.",
        }],
        "duplicate_groups": [],
        "winning_patterns": ["Asset-1 uses a product-first reading path; single-image evidence."],
        "visual_language": ["Use cream fields with violet product-led focal areas."],
        "brand_colors": {
            "primary": {"value": "violet", "note": "Observed in asset-1 only."},
        },
        "typography_signals": {
            "headline": {"fontWeight": "bold", "note": "Observed, exact family unknown."},
        },
        "component_patterns": ["Isolated product card."],
        "brand_signals": ["Small upper-right logo with surrounding clear space."],
        "token_confidence_notes": ["Colour names are approximate visual observations."],
        "composition_rules": ["Keep the product and claim in separate visual zones."],
        "imagery_rules": ["Use an isolated product object rather than an unrelated scene."],
        "ratio_rules": {"square": "Preserve the two-zone balance seen in asset-1."},
        "message_hierarchy": ["Product proof before benefit claim, logo, and action."],
        "copy_density_rules": ["Retain one short claim and one compact action."],
        "safe_area_guidance": ["Keep the outer ten percent clear."],
        "cta_rules": ["Keep the action visually subordinate to the benefit claim."],
        "brand_and_product_rules": ["Product remains dominant; logo remains small."],
        "visual_style": ["Flat cream field with a saturated product accent."],
        "avoid": ["Do not introduce unrelated lifestyle photography."],
        "future_generation_contract_notes": ["Confirm exact brand colour tokens if supplied later."],
    }


class StaticBannerDesignTests(unittest.TestCase):
    def test_nested_or_partial_strategy_is_rejected(self):
        strategy = {
            "status": "complete",
            "image_inspected_count": 1,
            "observations": complete_strategy(),
        }

        errors = analyze._strategy_validation_errors(strategy, {"asset-1"})

        self.assertIn("creative_observations must be a non-empty list", errors)
        self.assertTrue(any("visual_language" in error for error in errors))

    def test_every_downloaded_asset_requires_one_detailed_observation(self):
        strategy = complete_strategy()

        errors = analyze._strategy_validation_errors(
            strategy, {"asset-1", "asset-2"}
        )

        self.assertTrue(any("missing observations for asset IDs: asset-2" in error for error in errors))
        self.assertTrue(any("image_inspected_count" in error for error in errors))

    def test_complete_strategy_renders_only_supplied_design_guidance(self):
        strategy = complete_strategy()
        self.assertEqual(
            analyze._strategy_validation_errors(strategy, {"asset-1"}), []
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "DESIGN.md"
            analyze._write_static_banner_design_md(
                output,
                strategy,
                Path(directory) / "DESIGN_STRATEGY.md",
                "1234567890",
            )
            text = output.read_text()

        self.assertIn("Use cream fields with violet product-led focal areas.", text)
        self.assertIn("Keep the outer ten percent clear.", text)
        self.assertIn("Confirm exact brand colour tokens if supplied later.", text)
        self.assertNotIn("Build one dominant reading path", text)
        self.assertNotIn("Use one CTA per banner", text)
        self.assertNotIn("Theme Grammar", text)


if __name__ == "__main__":
    unittest.main()
