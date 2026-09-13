"""Shared Google Ads credential paths and write authorization boundaries."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .core import *  # noqa: F403

def _profile_customer_id(profile: dict[str, Any]) -> str:
    return str(profile.get("google_ads_customer_id", "")).replace("-", "")


def _account_credentials_dir(customer_id: str) -> str:
    return str(ACCOUNTS_DIR / customer_id.replace("-", ""))


def _default_read_config_path(customer_id: str) -> str:
    return f"{_account_credentials_dir(customer_id)}/google-ads-garf.yaml"


def _default_write_config_path(customer_id: str) -> str:
    return f"{_account_credentials_dir(customer_id)}/google-ads-api.yaml"


def _resolve_profile_config_path(profile: dict[str, Any], *, write: bool = False) -> Path:
    customer_id = _profile_customer_id(profile)
    configured = (
        str(profile.get("google_ads_write_config_path", "") or "").strip()
        if write
        else _profile_read_config_value(profile)
    )
    defaults: list[str] = []
    if configured:
        defaults.append(configured)
    if customer_id:
        defaults.append(_default_write_config_path(customer_id) if write else _default_read_config_path(customer_id))

    seen: set[str] = set()
    for candidate in defaults:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = _resolve_state_path(candidate)
        if path.exists():
            return path
    fallback = configured
    if not fallback:
        fallback = defaults[0]
    return _resolve_state_path(fallback)

def _runtime_write_config_path() -> Path:
    """Hosted writes use the connected user's runtime OAuth config only."""
    configured = os.getenv("BOB_GOOGLE_ADS_RUNTIME_CONFIG", "").strip()
    if not configured:
        die("Google Ads is not connected for this user. Connect Google Ads in Bob before applying changes.", error_code="GOOGLE_AUTH_REQUIRED")
    path = Path(configured).expanduser()
    if not path.exists():
        die("Google Ads runtime authorization is unavailable. Reconnect Google Ads before applying changes.", error_code="GOOGLE_AUTH_REQUIRED")
    return path

def _require_write_permission() -> None:
    if os.getenv("BOB_ACCOUNT_PERMISSION", "read").strip().lower() != "read_write":
        die("This Bob user has READ access only. READ & WRITE permission is required to apply Google Ads changes.")


def _normalize_account_config_files(profile: dict[str, Any]) -> list[str]:
    customer_id = _profile_customer_id(profile)
    if not customer_id:
        return []

    migrated: list[str] = []
    read_default = _resolve_state_path(_default_read_config_path(customer_id))
    write_default = _resolve_state_path(_default_write_config_path(customer_id))

    read_path = _profile_read_config_value(profile)
    if read_path:
        current_read = _resolve_state_path(read_path)
        if current_read != read_default and current_read.exists() and not read_default.exists():
            read_default.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_read, read_default)
            migrated.append(f"copied read config into account folder: {read_default}")
        _set_profile_read_config_value(profile, str(read_default))
    elif read_default.exists():
        _set_profile_read_config_value(profile, str(read_default))
        migrated.append("set active account profile to account-folder read config")

    write_path = str(profile.get("google_ads_write_config_path", "") or "").strip()
    if write_path:
        current_write = _resolve_state_path(write_path)
        if current_write != write_default and current_write.exists() and not write_default.exists():
            write_default.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_write, write_default)
            migrated.append(f"copied write config into account folder: {write_default}")
        profile["google_ads_write_config_path"] = str(write_default)
    elif write_default.exists():
        profile["google_ads_write_config_path"] = str(write_default)
        migrated.append("set active account profile to account-folder write config")

    if migrated:
        _set_active_account(profile)
    return migrated

__all__ = [name for name in globals() if not name.startswith("__")]
