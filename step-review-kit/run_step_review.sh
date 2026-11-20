#!/bin/sh
# STEP CLI 审阅封装：可选设置 libGL stub 的 LD_LIBRARY_PATH
DIR=$(cd "$(dirname "$0")" && pwd)
if [ -n "$STEP_LD_LIBRARY_PATH" ]; then
  export LD_LIBRARY_PATH="$STEP_LD_LIBRARY_PATH:${LD_LIBRARY_PATH}"
fi
exec python3 "$DIR/step_review.py" "$@"