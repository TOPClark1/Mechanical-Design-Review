#!/usr/bin/env bash
set -euo pipefail

# Scan tracked files for unresolved git conflict markers.
markers='^(<<<<<<< |=======|>>>>>>> )'

matches=$(git ls-files | xargs -r rg -n "$markers" || true)
if [[ -n "$matches" ]]; then
  echo "[ERROR] Unresolved conflict markers found:"
  echo "$matches"
  exit 1
fi

echo "[OK] No unresolved conflict markers found in tracked files."
