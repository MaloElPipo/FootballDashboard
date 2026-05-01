#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace
[ -f .git/index.lock ] && rm -f .git/index.lock

echo "=== AVANT reset ==="
git --no-optional-locks log --oneline -3
git --no-optional-locks status --short --branch | head -3

echo "=== reset --hard github/main ==="
git reset --hard github/main

echo "=== APRES reset ==="
git --no-optional-locks log --oneline -3
git --no-optional-locks status --short --branch | head -3
git --no-optional-locks rev-list --left-right --count HEAD...github/main
echo "[OK] Done"
