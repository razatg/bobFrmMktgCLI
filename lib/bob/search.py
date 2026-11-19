"""Account-filtered text retrieval. No embeddings or search service required."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml

from lib.bob.decisions.records import database


def skills_search(root: Path, query: str = "") -> list[dict]:
    terms = query.casefold().split()
    skills = []
    for path in sorted((root / ".agents" / "skills").glob("*/SKILL.md")):
        parts = path.read_text().split("---", 2)
        metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
        description = str(metadata.get("description", ""))
        name = str(metadata.get("name", path.parent.name))
        score = sum(term in (name + " " + description).casefold() for term in terms)
        if score or not terms:
            skills.append({"name": name, "description": description,
                           "path": str(path.relative_to(root)), "score": score})
    return sorted(skills, key=lambda item: (-item["score"], item["name"]))


def search(root: Path, account: str, query: str, *, kind: str = "", since: str = "",
           limit: int = 10) -> list[dict]:
    from lib.bob.decisions.evidence import account_dir
    account_dir(root, account)  # Validate the account before using it in paths.
    terms = re.findall(r"\w+", query, re.UNICODE)
    if not terms:
        return []
    directory = root / "search"
    directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(directory / f"{account}.fts.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(path UNINDEXED, kind UNINDEXED, date UNINDEXED, body)")
        # Refresh on read too: captures manual KT edits and sync, not only CLI writes.
        connection.execute("DELETE FROM documents")
        wiki = (root / "wiki" / account).resolve()
        for path in sorted(wiki.rglob("*.md")):
            if not path.resolve().is_relative_to(wiki) or path.stat().st_size > 1_000_000:
                continue
            category = "kt" if path.name.casefold() == "kt.md" else "action" if "action-items" in path.parts else "analysis"
            import datetime as dt
            stamp = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).date().isoformat()
            connection.execute("INSERT INTO documents VALUES (?,?,?,?)",
                               (str(path.relative_to(root)), category, stamp, path.read_text()))
        with database(root, account) as journal:
            for row in journal.execute("SELECT id,created_at,record FROM decisions"):
                connection.execute("INSERT INTO documents VALUES (?,?,?,?)",
                                   (f"decision:{row['id']}", "decision", row['created_at'], row['record']))
        match = " OR ".join('"' + term + '"' for term in terms)
        rows = connection.execute('''SELECT path,kind,date,snippet(documents,3,'','', ' … ',40) snippet
          FROM documents WHERE documents MATCH ? AND (?='' OR kind=?) AND date>=?
          ORDER BY rank LIMIT ?''', (match, kind, kind, since, max(1, min(limit, 50)))).fetchall()
    return [dict(row) for row in rows]
