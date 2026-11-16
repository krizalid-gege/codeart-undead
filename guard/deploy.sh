#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PORT="${APP_PORT:-8080}"
PIDFILE="$HERE/.server.pid"
LOGFILE="$HERE/server.log"

if [ -f "$PIDFILE" ]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PIDFILE"
fi

if command -v python3 >/dev/null 2>&1; then
  cd "$ROOT/site"
  nohup python3 -m http.server "$PORT" --bind 0.0.0.0 >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
elif command -v node >/dev/null 2>&1; then
  cd "$ROOT/site"
  nohup node "$HERE/static-server.js" "$PORT" >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
else
  echo "no supported runtime (python3/node)" >&2
  exit 3
fi

sleep 1
"$HERE/healthcheck.sh"
echo "deployed on port $PORT pid $(cat "$PIDFILE")"