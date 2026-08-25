#!/bin/sh
set -eu

APP_ROOT=/app
STATE_ROOT=${BOB_STATE_ROOT:-/data/client}

mkdir -p \
  "$STATE_ROOT/.bob" \
  "$STATE_ROOT/data" \
  "$STATE_ROOT/garf/outputs" \
  "$STATE_ROOT/logs" \
  "$STATE_ROOT/wiki" \
  "$STATE_ROOT/validation"

# Keep the repository's historical relative paths visible to the agent and
# skills, while the actual directories live in the persistent client volume.
for path in .bob data garf/outputs logs wiki validation; do
  target="$STATE_ROOT/$path"
  link="$APP_ROOT/$path"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "refusing to replace non-symlink state path: $link" >&2
    exit 1
  fi
  ln -sfn "$target" "$link"
done

exec "$@"
