#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${APP_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"

if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 5 "$URL" >/dev/null
elif command -v wget >/dev/null 2>&1; then
  wget -q -T 5 -O /dev/null "$URL"
else
  exec 3<>"/dev/tcp/127.0.0.1/${PORT}"
  exec 3>&-
fi

echo "healthy: $URL"