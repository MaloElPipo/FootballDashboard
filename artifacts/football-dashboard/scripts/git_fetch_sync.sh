#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace
[ -f .git/refs/remotes/github/main.lock ] && rm -f .git/refs/remotes/github/main.lock
[ -f .git/index.lock ] && rm -f .git/index.lock

echo "=== AVANT fetch ==="
git --no-optional-locks status --short --branch | head -3
git --no-optional-locks rev-list --left-right --count HEAD...github/main || true

echo "=== fetch github main ==="
git fetch github main

echo "=== APRES fetch ==="
git --no-optional-locks status --short --branch | head -3
git --no-optional-locks rev-list --left-right --count HEAD...github/main
echo "[OK] Done"
