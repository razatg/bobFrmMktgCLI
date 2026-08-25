#!/bin/sh
set -eu

SOURCE_ROOT=${1:?usage: migrate-client-state.sh SOURCE_ROOT DEST_STATE_ROOT}
DEST_ROOT=${2:?usage: migrate-client-state.sh SOURCE_ROOT DEST_STATE_ROOT}

SOURCE_ROOT=$(cd "$SOURCE_ROOT" && pwd)
mkdir -p "$DEST_ROOT"
DEST_ROOT=$(cd "$DEST_ROOT" && pwd)

if [ "$SOURCE_ROOT" = "$DEST_ROOT" ]; then
  echo "source and destination must be different" >&2
  exit 1
fi

# Bob's persistent state only. Code, skills, queries, and the launcher remain
# in the image and are deliberately not copied into the client volume.
for path in .bob data garf/outputs logs wiki validation; do
  if [ -d "$SOURCE_ROOT/$path" ]; then
    mkdir -p "$DEST_ROOT/$path"
    cp -a "$SOURCE_ROOT/$path/." "$DEST_ROOT/$path/"
  fi
done

echo "migrated Bob client state"
echo "  source:      $SOURCE_ROOT"
echo "  destination: $DEST_ROOT"
