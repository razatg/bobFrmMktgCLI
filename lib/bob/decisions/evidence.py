"""Copy cited evidence, rather than depending on mutable processed filenames."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path


def account_dir(root: Path, account: str) -> Path:
    account = account.replace("-", "")
    if not re.fullmatch(r"\d+", account):
        raise ValueError("a numeric account identifier is required")
    return root / "decisions" / account


def preserve(root: Path, account: str, source: str, operation: dict) -> dict:
    path = (root / source).resolve()
    allowed = ((root / "data" / "processed" / account).resolve(),
               (root / "wiki" / account).resolve())
    if not any(path.is_relative_to(directory) for directory in allowed):
        raise ValueError("evidence must belong to the selected account")
    if path.stat().st_size > 25_000_000:
        raise ValueError("evidence exceeds snapshot size limit")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    target = account_dir(root, account) / "evidence" / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != data:
                raise ValueError("immutable evidence integrity failure")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    code = hashlib.sha256()
    for module in sorted(Path(__file__).resolve().parents[1].rglob('*.py')):
        code.update(str(module.relative_to(Path(__file__).resolve().parents[1])).encode())
        code.update(module.read_bytes())
    return {"sha256": digest, "source": source, "operation": operation,
            "bytes": len(data), "code_version": os.getenv("BOB_RELEASE_SHA") or code.hexdigest()}


def read(root: Path, account: str, digest: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("invalid evidence identity")
    data = (account_dir(root, account) / "evidence" / digest).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("immutable evidence integrity failure")
    return data
