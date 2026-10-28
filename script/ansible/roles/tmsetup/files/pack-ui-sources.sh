#!/bin/bash
# Pack tm-control's UI sources for the revproxy image build (tasks/revproxy_setup.yml), on the machine running tmsetup.
# Usage: pack-ui-sources.sh <tm-control directory> <archive.tar.gz>
#
# The archive's members are named ui/...: the files git lists under ui (tracked, or untracked and not ignored), so
# stray local files stay behind, and the directories that hold them, so unarchive gives those the role's owner and
# mode too. Without git, or outside a git checkout (a release download), it packs the whole ui directory.
# node_modules and dist never go in. Written for bash 3.2, the version macOS ships.
set -euo pipefail

src=$1
archive=$2
excludes=(--exclude=ui/node_modules --exclude='ui/node_modules/*' --exclude=ui/dist --exclude='ui/dist/*')

if command -v git >/dev/null 2>&1 && git -C "$src" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  list=$(mktemp)
  trap 'rm -f "$list"' EXIT
  # Each file that exists (git still lists one deleted from the working tree) and every directory above it, sorted,
  # so a directory comes before what's in it
  git -C "$src" ls-files -z --cached --others --exclude-standard -- ui |
    while IFS= read -r -d '' name; do
      [ -e "$src/$name" ] || continue
      printf '%s\0' "$name"
      dir=$name
      while [ "${dir%/*}" != "$dir" ]; do
        dir=${dir%/*}
        printf '%s\0' "$dir"
      done
    done |
    sort -z -u > "$list"
  # Inside some other repo (a copy of the code unpacked in an unrelated checkout), git lists that repo's files
  if ! tr '\0' '\n' < "$list" | grep -qx 'ui/package.json'; then
    echo "pack-ui-sources: git doesn't list ui/package.json under $src, so this isn't a Traffic Monitor checkout" \
      "git can read. Run tmsetup from a git clone of Traffic Monitor, or from a copy outside any git checkout." >&2
    exit 1
  fi
  tar -czf "$archive" -C "$src" "${excludes[@]}" --no-recursion --null -T "$list"
  echo "packed the UI files git lists"
else
  tar -czf "$archive" -C "$src" "${excludes[@]}" ui
  echo "packed the whole UI directory (no git checkout)"
fi
