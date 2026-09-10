# Native session diagnostics

This utility extracts a small, sanitized diagnostic from one native Codex session JSONL. Run it
inside the hosted container because VM snapshots deliberately exclude Codex runtime state.

From the VM repository directory:

```bash
docker-compose exec -T web python /app/docs/snapshot/session-details.py \
  SESSION_ID \
  --job-id JOB_ID
```

For example:

```bash
docker-compose exec -T web python /app/docs/snapshot/session-details.py \
  01a08c7d-d305-79c0-9613-1934047b0522 \
  --job-id 0081ecec329044b685f72434dd44874c
```

The report contains the hosted job status and prompt when available, error-like tool outputs from
the matching native JSONL, and the last assistant response. Common credential assignments and
bearer tokens are redacted. The full transcript and unrelated raw tool events are not printed.

To save a report that can be copied from the VM:

```bash
docker-compose exec -T web python /app/docs/snapshot/session-details.py \
  SESSION_ID --job-id JOB_ID > session-details.txt
```

Review the text before sharing it. Diagnostic output can still contain advertiser data or copy that
was part of the job.
