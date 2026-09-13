#!/usr/bin/env python3
"""Compatibility facade for Bob Frm Mktg's stable CLI."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.bob.platform import core as _platform_core
from lib.bob.platform.core import *
from lib.bob.platform import presentation as _platform_presentation
from lib.bob.platform.presentation import *
from lib.bob.platform import data as _platform_data
from lib.bob.platform.data import *
from lib.bob.platform import google_ads as _platform_google_ads
from lib.bob.platform.google_ads import *
from lib.bob.performance import fetch as _performance_fetch
from lib.bob.performance.fetch import *
from lib.bob.performance import aggregate as _performance_aggregate
from lib.bob.performance.aggregate import *
from lib.bob.performance import compare as _performance_compare
from lib.bob.performance.compare import *
from lib.bob.performance import validation as _performance_validation
from lib.bob.performance.validation import *
from lib.bob.performance import creatives as _performance_creatives
from lib.bob.performance.creatives import *
from lib.bob.performance import manifest as _performance_manifest
from lib.bob.performance.manifest import *
from lib.bob import bid_budget as _bid_budget
from lib.bob.bid_budget import *
from lib.bob.static_banners import analyze as _static_banner_analyze
from lib.bob.static_banners.analyze import *
from lib.bob.static_banners import variants as _static_banner_variants
from lib.bob.static_banners.variants import *
from lib.bob.creative_copy import suggest as _creative_copy_suggest
from lib.bob.creative_copy.suggest import *
from lib.bob.creative_copy import apply as _creative_copy_apply
from lib.bob.creative_copy.apply import *
from lib.bob import accounts as _accounts
from lib.bob.accounts import *
from lib.bob import self_improve as _self_improve
from lib.bob.self_improve import *
from lib.bob import sync as _sync
from lib.bob.sync import *
from lib.bob import snapshot as _snapshot
from lib.bob.snapshot import *

_extracted_modules = [
    _platform_core, _platform_presentation, _platform_data, _platform_google_ads,
    _performance_fetch, _performance_aggregate, _performance_compare,
    _performance_validation, _performance_creatives, _performance_manifest,
    _bid_budget, _static_banner_analyze, _static_banner_variants,
    _creative_copy_suggest, _creative_copy_apply, _accounts, _self_improve,
    _sync, _snapshot,
]


class _ExtractingFacade(types.ModuleType):
    """Forward legacy overrides to extracted owners during API compatibility."""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module in _extracted_modules:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _ExtractingFacade

from lib.bob.cli import _COMMAND_MAP, build_parser, main

__all__ = ["main", "build_parser", "_write_bob_launcher"]

if __name__ == "__main__":
    raise SystemExit(main())
