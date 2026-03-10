#!/usr/bin/env bash
set -euxo pipefail

# Package prebuilt binaries from upstream static folder without rebuilding.
if [[ ! -d "static" ]]; then
  echo "ERROR: expected static/ folder in Auto-Mech/MESS source tree" >&2
  exit 1
fi

mkdir -p "$PREFIX/bin"

# Copy all executable files from static into conda bin.
find static -maxdepth 1 -type f -perm -u+x -exec cp -f {} "$PREFIX/bin/" \;

# If executables are not marked executable in git, copy all files and fix mode.
if [[ -z "$(find "$PREFIX/bin" -maxdepth 1 -type f -name 'mess' -print -quit)" ]]; then
  find static -maxdepth 1 -type f -exec cp -f {} "$PREFIX/bin/" \;
fi

chmod +x "$PREFIX/bin"/* || true
