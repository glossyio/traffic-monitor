#!/bin/bash
# Pack tm-control's UI sources for the revproxy image build (tasks/revproxy_setup.yml), on the machine running tmsetup.
# Usage: pack-ui-sources.sh <tm-control directory> <archive.tar.gz>
#
# The archive's members are named ui/...: the files git lists under ui (tracked, or untracked and not ignored), so
# stray local files stay behind. Without git, or outside a git checkout (a release download), it packs the whole ui
# directory. node_modules and dist never go in.
set -euo pipefail

src=$1
archive=$2
excludes=(--exclude=ui/node_modules --exclude='ui/node_modules/*' --exclude=ui/dist --exclude='ui/dist/*')

if command -v git >/dev/null 2>&1 && git -C "$src" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # A file deleted from the working tree but not yet from git is still listed; leave it out.
  git -C "$src" ls-files -z --cached --others --exclude-standard -- ui |
    while IFS= read -r -d '' name; do
      if [ -e "$src/$name" ]; then printf '%s\0' "$name"; fi
    done |
    tar -czf "$archive" -C "$src" "${excludes[@]}" --null -T -
  echo "packed the UI files git lists"
else
  tar -czf "$archive" -C "$src" "${excludes[@]}" ui
  echo "packed the whole UI directory (no git checkout)"
fi
