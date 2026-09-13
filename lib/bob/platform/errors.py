"""Stable CLI error handling shared by Bob's command modules."""

from __future__ import annotations

import sys
from typing import NoReturn


def die(message: str, code: int = 1, *, error_code: str | None = None) -> NoReturn:
    if error_code:
        print(f"BOB_ERROR_CODE={error_code}", file=sys.stderr)
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)
