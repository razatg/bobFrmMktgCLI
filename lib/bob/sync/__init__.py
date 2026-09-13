"""Shared-folder reconciliation commands."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
def _load_sync_config() -> dict:
    if not SYNC_CONFIG_PATH.exists():
        return {}
    with SYNC_CONFIG_PATH.open() as f:
        return json.load(f)


def _save_sync_config(cfg: dict) -> None:
    BOB_DIR.mkdir(parents=True, exist_ok=True)
    with SYNC_CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def _resolve_shared_dir(create: bool = False) -> Path:
    """Return the configured shared-folder Path, or die with a setup hint."""
    raw = _load_sync_config().get("shared_dir", "")
    if not raw:
        die("sync not set up — run: ./bob sync --set-dir PATH   (PATH = your shared folder, e.g. a Dropbox folder)")
    shared = Path(raw).expanduser()
    if not shared.exists():
        if create and shared.parent.exists():
            shared.mkdir(parents=True, exist_ok=True)
        else:
            die(f"shared folder not found: {shared} — is it available / your cloud drive mounted?")
    return shared


def _read_jsonl_lines(path: Path) -> list[str]:
    """Return non-blank, valid-JSON lines of a JSONL file (tolerant), preserving raw text."""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(line)
    return out


def _jsonl_ts(line: str) -> str:
    try:
        return json.loads(line).get("timestamp", "")
    except Exception:
        return ""


def _union_jsonl(local_path: Path, shared_path: Path, to_local: bool, to_shared: bool,
                 dry_run: bool) -> dict:
    """Union an append-only JSONL across local + shared (+ any cloud 'conflicted copy' siblings).

    Exact-line dedup, sorted by timestamp. Append-only ⇒ no conflicts, no event ever lost.
    """
    local = _read_jsonl_lines(local_path)
    shared = _read_jsonl_lines(shared_path)
    local_set, shared_set = set(local), set(shared)
    conflicted: list[str] = []
    conflict_files: list[Path] = []
    if shared_path.parent.exists():
        for p in shared_path.parent.glob("*conflicted copy*.jsonl"):
            conflict_files.append(p)
            conflicted.extend(_read_jsonl_lines(p))

    seen: set[str] = set()
    merged: list[str] = []
    for line in [*local, *shared, *conflicted]:
        if line not in seen:
            seen.add(line)
            merged.append(line)
    merged.sort(key=_jsonl_ts)

    stats = {
        "total": len(merged),
        "added_local": sum(1 for l in merged if l not in local_set),
        "added_shared": sum(1 for l in merged if l not in shared_set),
        "conflicted_folded": len(conflict_files),
    }
    if not dry_run:
        text = "".join(l + "\n" for l in merged)
        # Write only when content actually changes — re-running with nothing new rewrites nothing.
        if to_local and (not local_path.exists() or local_path.read_text() != text):
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text)
        if to_shared:
            if not shared_path.exists() or shared_path.read_text() != text:
                shared_path.parent.mkdir(parents=True, exist_ok=True)
                shared_path.write_text(text)
            for p in conflict_files:
                try:
                    p.unlink()
                except OSError:
                    pass
    return stats


_INDEX_TITLE_DEFAULT = "# Bob — Wiki Index"


def _parse_index_sections(text: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """Split Index.md into (title_block, {'## Header': [lines]}, header_order). Unknown sections kept."""
    title: list[str] = []
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line.strip()
            if current not in sections:
                sections[current] = []
                order.append(current)
        elif current is None:
            title.append(line)
        else:
            sections[current].append(line)
    return "\n".join(title).strip(), sections, order


def _union_index(local_text: str, shared_text: str) -> str:
    """Union two Index.md files per section: bullet/content lines deduped, order preserved."""
    l_title, l_sec, l_order = _parse_index_sections(local_text)
    s_title, s_sec, s_order = _parse_index_sections(shared_text)
    order: list[str] = []
    for h in [*l_order, *s_order]:
        if h not in order:
            order.append(h)
    parts: list[str] = [l_title or s_title or _INDEX_TITLE_DEFAULT]
    for h in order:
        seen: set[str] = set()
        bullets: list[str] = []
        for x in [*l_sec.get(h, []), *s_sec.get(h, [])]:
            key = x.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            bullets.append(x.rstrip())
        parts.append((h + "\n\n" + "\n".join(bullets)).rstrip())
    return "\n\n".join(parts).rstrip() + "\n"


def _split_entry_blocks(lines: list[str]) -> list[str]:
    """Split a section's lines into '### ' entry blocks (text before the first '### ' is dropped)."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line.startswith("### "):
            if cur:
                blocks.append("\n".join(cur).strip())
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def _union_backlog(local_text: str, shared_text: str) -> str:
    """Union backlog.md per section by '### ' entry block (dedup exact blocks, order preserved).

    Like the Index union but entries are multi-line blocks rather than single bullets — so two
    people adding bug/feature entries both accumulate, nothing is lost, nothing conflicts.
    """
    l_title, l_sec, l_order = _parse_index_sections(local_text)
    s_title, s_sec, s_order = _parse_index_sections(shared_text)
    order: list[str] = []
    for h in [*l_order, *s_order]:
        if h not in order:
            order.append(h)
    parts: list[str] = [l_title or s_title]
    for h in order:
        seen: set[str] = set()
        blocks: list[str] = []
        for b in [*_split_entry_blocks(l_sec.get(h, [])), *_split_entry_blocks(s_sec.get(h, []))]:
            key = b.strip()
            if key and key not in seen:
                seen.add(key)
                blocks.append(b)
        parts.append((h + "\n\n" + "\n\n".join(blocks)).rstrip())
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


def _union_md_file(local_path: Path, shared_path: Path, union_fn, to_local: bool,
                   to_shared: bool, dry_run: bool) -> dict:
    """Reconcile a single markdown file via union_fn; write only the sides whose content changes."""
    l_text = local_path.read_text(errors="replace") if local_path.exists() else ""
    s_text = shared_path.read_text(errors="replace") if shared_path.exists() else ""
    if not l_text and not s_text:
        return {"present": False, "to_local": False, "to_shared": False}
    merged = union_fn(l_text, s_text)
    stats = {"present": True, "to_local": merged != l_text, "to_shared": merged != s_text}
    if not dry_run:
        if to_local and stats["to_local"]:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(merged)
        if to_shared and stats["to_shared"]:
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            shared_path.write_text(merged)
    return stats


def _iter_wiki_files(base: Path) -> dict[str, Path]:
    """Map relative-path → absolute Path under base (skips junk + local .bak safety copies)."""
    out: dict[str, Path] = {}
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_dir() or p.name == ".DS_Store" or ".bak-" in p.name:
            continue
        out[str(p.relative_to(base))] = p
    return out


def _files_equal(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _backup(path: Path) -> None:
    """Save a sibling .bak copy so a newer-wins overwrite never loses content."""
    if path.exists():
        bak = path.with_name(path.name + f".bak-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}")
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass


def _sync_wiki(local_base: Path, shared_base: Path, to_local: bool, to_shared: bool,
               dry_run: bool) -> dict:
    """Reconcile wiki files: copy where missing, union Index.md, newer-wins (with .bak) elsewhere."""
    local_files = _iter_wiki_files(local_base)
    shared_files = _iter_wiki_files(shared_base)
    stats = {"to_shared": 0, "to_local": 0, "index_unioned": 0, "baks": 0}
    for rel in sorted(set(local_files) | set(shared_files)):
        lp, sp = local_files.get(rel), shared_files.get(rel)
        ltarget, starget = local_base / rel, shared_base / rel
        if lp and not sp:
            if to_shared:
                if not dry_run:
                    starget.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(lp, starget)
                stats["to_shared"] += 1
        elif sp and not lp:
            if to_local:
                if not dry_run:
                    ltarget.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sp, ltarget)
                stats["to_local"] += 1
        elif lp and sp and not _files_equal(lp, sp):
            if Path(rel).name == "Index.md":
                merged = _union_index(lp.read_text(errors="replace"), sp.read_text(errors="replace"))
                if not dry_run:
                    if to_local:
                        ltarget.write_text(merged)
                    if to_shared:
                        starget.write_text(merged)
                stats["index_unioned"] += 1
            elif sp.stat().st_mtime >= lp.stat().st_mtime:
                if to_local:
                    if not dry_run:
                        _backup(ltarget)
                        shutil.copy2(sp, ltarget)
                    stats["to_local"] += 1
                    stats["baks"] += 1
            else:
                if to_shared:
                    if not dry_run:
                        _backup(starget)
                        shutil.copy2(lp, starget)
                    stats["to_shared"] += 1
                    stats["baks"] += 1
    return stats


def sync(args: argparse.Namespace) -> None:
    """Share wiki/ + logs/session-signals.jsonl with teammates via a plain shared folder.

    No git: the append-only signal log and Index.md bullet lists are unioned, other wiki files are
    copied newer-wins (older kept as .bak). Both paths stay gitignored, so the public repo is never
    touched. Default reconciles both ways; --pull / --push limit the direction.
    """
    if args.set_dir:
        shared_set = Path(args.set_dir).expanduser()
        _save_sync_config({"shared_dir": str(shared_set)})
        print(f"shared folder set: {shared_set}")
        if not shared_set.exists() and not shared_set.parent.exists():
            print(f"warning: {shared_set.parent} not found — is your cloud drive mounted?")

    if args.pull and args.push:
        die("use at most one of --pull / --push")
    shared = _resolve_shared_dir(create=not args.dry_run)
    to_local = not args.push
    to_shared = not args.pull

    direction = "both ways" if (to_local and to_shared) else ("pull only" if to_local else "push only")
    print(f"{'DRY RUN — ' if args.dry_run else ''}sync ({direction}) with {shared}\n")

    sig = _union_jsonl(SIGNAL_LOG_PATH, shared / "session-signals.jsonl", to_local, to_shared, args.dry_run)
    wiki = _sync_wiki(STATE_ROOT / "wiki", shared / "wiki", to_local, to_shared, args.dry_run)
    bk = _union_md_file(STATE_ROOT / "logs" / "backlog.md", shared / "backlog.md",
                        _union_backlog, to_local, to_shared, args.dry_run)

    print(f"signals : {sig['total']} total  (+{sig['added_local']} local, +{sig['added_shared']} shared"
          + (f", {sig['conflicted_folded']} conflicted-copy folded in" if sig["conflicted_folded"] else "") + ")")
    print(f"wiki    : {wiki['to_local']} → local, {wiki['to_shared']} → shared, "
          f"{wiki['index_unioned']} Index.md unioned, {wiki['baks']} .bak saved")
    bk_state = ("not present yet" if not bk["present"]
                else "unioned " + ("→ local & shared" if bk["to_local"] and bk["to_shared"]
                                   else "→ local" if bk["to_local"]
                                   else "→ shared" if bk["to_shared"] else "(already in sync)"))
    print(f"backlog : {bk_state}")
    print("\nNothing written (dry run)." if args.dry_run else "\nsync complete.")

__all__ = [name for name in globals() if not name.startswith("__")]
