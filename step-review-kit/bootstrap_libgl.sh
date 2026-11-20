#!/bin/sh
# 可选：无 root 且缺 libGL 时，安装 libglvnd 并生成 libGL stub。
# 依赖: curl tar gcc objdump python3
# 用法: ./bootstrap_libgl.sh
# 完成后按输出设置 STEP_LD_LIBRARY_PATH。
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
GLROOT=${GLROOT:-$DIR/.gltools}
MARCH=$(uname -m)
case "$MARCH" in
  aarch64) MM=linux-aarch64 ;;
  x86_64|amd64) MM=linux-64 ;;
  *) echo "unsupported arch: $MARCH"; exit 1 ;;
esac

if python3 -c "import cadquery" >/dev/null 2>&1; then
  echo "cadquery 已可用，无需 bootstrap。"
  exit 0
fi

mkdir -p "$GLROOT"
MAMBA="$GLROOT/bin/micromamba"
if [ ! -x "$MAMBA" ]; then
  echo "下载 micromamba ($MM) ..."
  curl -L --fail -o "$GLROOT/micromamba.tar.bz2" "https://micro.mamba.pm/api/micromamba/$MM/latest"
  tar -xjf "$GLROOT/micromamba.tar.bz2" -C "$GLROOT"
fi

export MAMBA_ROOT_PREFIX="$GLROOT/mamba" MAMBA_ALWAYS_YES=true
"$MAMBA" create -y -p "$GLROOT/glenv" -c conda-forge libglvnd

TKO=$(find / -name 'libTKOpenGl-*.so*' 2>/dev/null | head -1)
if [ -z "$TKO" ]; then
  echo "找不到 libTKOpenGl，请先 pip install cadquery"
  exit 1
fi

mkdir -p "$GLROOT/stublib"
SYMS="$GLROOT/gl_syms.txt"
objdump -T "$TKO" | grep '\*UND\*' | awk '{print $NF}' | grep -E '^(gl|glX)' | sed 's/@.*//' | sort -u > "$SYMS"
{
  echo '#include <stdint.h>'
  sed 's/.*/void &(void) {}/' "$SYMS"
} > "$GLROOT/gl_stub.c"
gcc -shared -fPIC -o "$GLROOT/stublib/libGL.so.1" "$GLROOT/gl_stub.c"

echo "完成。请设置："
echo "  export STEP_LD_LIBRARY_PATH=$GLROOT/stublib:$GLROOT/glenv/lib"