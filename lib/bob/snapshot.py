"""Local snapshot import command."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from lib.bob.platform.core import *
def snapshot_pull(args: argparse.Namespace) -> None:
    """Pull an on-demand, read-only development snapshot from a hosted VM."""
    host = (args.ssh_host or os.getenv("BOB_SNAPSHOT_SSH_HOST", "")).strip()
    instance = (args.gcloud_instance or os.getenv("BOB_SNAPSHOT_GCLOUD_INSTANCE", "")).strip()
    if not host and not instance:
        raise SystemExit("snapshot-pull requires --ssh-host or --gcloud-instance")
    remote_dir = args.remote_dir or os.getenv("BOB_SNAPSHOT_REMOTE_DIR", "~/bobFrmMktgCLI")
    local_dir = Path(args.local_dir or os.getenv("BOB_SNAPSHOT_LOCAL_DIR", str(SNAPSHOT_DEFAULT_DIR))).expanduser().resolve()
    local_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="vm-snapshot-", dir=str(local_dir.parent)))
    archive = staging / "snapshot.tar.gz"
    remote_db = "/data/metadata/.bob-metadata-snapshot.sqlite3"
    if instance:
        zone = args.gcloud_zone or os.getenv("BOB_SNAPSHOT_GCLOUD_ZONE", "")
        project = args.gcloud_project or os.getenv("BOB_SNAPSHOT_GCLOUD_PROJECT", "")
        if not zone or not project:
            raise SystemExit("Google Cloud snapshots require --gcloud-zone and --gcloud-project")
        ssh_prefix = ["gcloud", "compute", "ssh", instance, "--zone", zone, "--project", project, "--"]
    else:
        ssh_prefix = ["ssh", "-o", "BatchMode=yes", host]
    remote_dir_command = f"$HOME/{shlex.quote(remote_dir[2:])}" if remote_dir.startswith("~/") else shlex.quote(remote_dir)
    remote_base = f"cd {remote_dir_command}"
    backup_code = (
        "import sqlite3; "
        "src=sqlite3.connect('/data/metadata/metadata.sqlite3'); "
        f"dst=sqlite3.connect({remote_db!r}); "
        "src.backup(dst); dst.close(); src.close()"
    )
    remote_archive = "/tmp/bob-snapshot-container.tar.gz"
    archive_code = (
        "import tarfile,os; "
        f"out=tarfile.open({remote_archive!r},mode='w:gz'); "
        f"out.add({remote_db!r},arcname='metadata/metadata.sqlite3'); "
        "[out.add('/data/client/'+name,arcname='client/'+name) for name in "
        "('garf','data','wiki','logs','validation','.bob/accounts','.bob/accounts.json') "
        "if os.path.exists('/data/client/'+name)]; out.close()"
    )
    try:
        subprocess.run(ssh_prefix + [f"{remote_base} && docker compose exec -T web python -c {shlex.quote(backup_code)}"], check=True)
        if instance:
            remote_host_archive = "/tmp/bob-snapshot.tar.gz"
            subprocess.run(ssh_prefix + [f"{remote_base} && docker compose exec -T web python -c {shlex.quote(archive_code)} && docker compose cp web:{remote_archive} {remote_host_archive}"], check=True)
            subprocess.run(["gcloud", "compute", "scp", f"{instance}:{remote_host_archive}", str(archive), "--zone", zone, "--project", project], check=True)
        else:
            with archive.open("wb") as handle:
                subprocess.run(ssh_prefix + [f"{remote_base} && docker compose exec -T web python -c {shlex.quote(archive_code)} && docker compose cp web:{remote_archive} /tmp/bob-snapshot.tar.gz && cat /tmp/bob-snapshot.tar.gz"], stdout=handle, check=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        extract_root = staging / "payload"
        extract_root.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                target = (extract_root / member.name).resolve()
                if not str(target).startswith(str(extract_root.resolve()) + os.sep):
                    raise RuntimeError("snapshot contains an unsafe path")
            bundle.extractall(extract_root)
        manifest = {
            "source": host,
            "pulled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "archive_sha256": digest,
            "contents": ["metadata/metadata.sqlite3", "client/"],
            "read_only_source": True,
        }
        (extract_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        previous = local_dir.with_name(local_dir.name + ".previous")
        if previous.exists():
            shutil.rmtree(previous)
        if local_dir.exists():
            local_dir.rename(previous)
        extract_root.rename(local_dir)
        working_dir = local_dir.with_name(local_dir.name + ".working")
        working_staging = local_dir.with_name(local_dir.name + ".working-staging")
        if working_staging.exists():
            shutil.rmtree(working_staging)
        shutil.copytree(local_dir, working_staging)
        if working_dir.exists():
            shutil.rmtree(working_dir)
        working_staging.rename(working_dir)
        print(f"snapshot pulled: {local_dir}")
        print(f"local Docker working copy: {working_dir}")
        print(f"source: {host} · sha256: {digest[:16]}…")
    finally:
        cleanup = f"{remote_base} && docker compose exec -T web rm -f {remote_db} {remote_archive}"
        if instance:
            cleanup += " && rm -f /tmp/bob-snapshot.tar.gz"
        subprocess.run(ssh_prefix + [cleanup], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(staging, ignore_errors=True)

__all__ = [name for name in globals() if not name.startswith("__")]
