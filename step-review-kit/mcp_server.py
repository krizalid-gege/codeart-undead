#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step-review-kit/mcp_server.py — STEP 3D 结构审阅 MCP Server

工具:
  list_parts(step_path)
  review_step(step_path, ...检查项... , include_report=False)

依赖:
  pip install cadquery mcp
  libGL（见 README；无 root 可用 bootstrap_libgl.sh，并设置 STEP_LD_LIBRARY_PATH）
运行:
  ./run_step_mcp.sh                 # stdio
环境:
  STEP_REVIEW_ROOT  允许读取的根目录（默认仓库根）
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import step_review as S  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP as _Server
except Exception:
    from mcp.server.mcpserver import MCPServer as _Server

ROOT = os.path.realpath(os.environ.get("STEP_REVIEW_ROOT", os.path.dirname(BASE)))
mcp = _Server("step-review")


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _safe(path):
    if not path:
        raise ValueError("step_path is required")
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    real = os.path.realpath(p)
    if not (real == ROOT or real.startswith(ROOT + os.sep)):
        raise ValueError("path outside STEP_REVIEW_ROOT: %s" % real)
    if not os.path.exists(real):
        raise FileNotFoundError("not found: %s" % real)
    return real


def _data(path, nodes, checks):
    referred_count = {}
    for n in nodes:
        if n.get("referred"):
            referred_count[n["referred"]] = referred_count.get(n["referred"], 0) + 1
    reused = {k: v for k, v in referred_count.items() if v > 1}
    return {
        "file": os.path.abspath(path),
        "assembly": {
            "instance_count": sum(1 for n in nodes if not n["assembly"]),
            "unique_shape_count": len(referred_count),
            "max_depth": max((n["depth"] for n in nodes), default=0),
            "reused": reused,
            "tree": [{"path": n["path"], "depth": n["depth"], "assembly": n["assembly"],
                      "reference": n["reference"]} for n in nodes],
        },
        "parts": [S.public_node(n) for n in nodes],
        "checks": checks,
    }


def _review(step_path, fit_child="", fit_parent="", fit_clearance=0.0,
            align_a="", align_b="", align_tol=0.5,
            limit_part="", limit_zmax=0.0,
            avoid_a="", avoid_b="", avoid_clearance=0.0,
            interference=False, interference_vol=1e-3,
            min_gap=False, wall_thickness=False, wall_part="", wall_samples=200):
    path = _safe(step_path)
    tool, nodes = S.load_step(path)
    checks = {}
    if fit_child and fit_parent:
        a = S.select_parts(nodes, fit_child)
        b = S.select_parts(nodes, fit_parent)
        checks["fit"] = {"child_matches": [n["path"] for n in a],
                         "parent_matches": [n["path"] for n in b],
                         "result": S.check_fit(a, b, fit_clearance)}
    if align_a and align_b:
        a = S.select_parts(nodes, align_a)
        b = S.select_parts(nodes, align_b)
        checks["align_holes"] = S.check_align(a, b, align_tol)
    if limit_part:
        a = S.select_parts(nodes, limit_part)
        checks["limit_height"] = S.check_limit(a, limit_zmax)
    if avoid_a and avoid_b:
        a = S.select_parts(nodes, avoid_a)
        b = S.select_parts(nodes, avoid_b)
        checks["avoid"] = S.check_avoid(a, b, avoid_clearance)
    if interference:
        checks["interference"] = S.check_interference(nodes, interference_vol)
    if min_gap:
        checks["min_gap"] = S.check_min_gap(nodes)
    if wall_thickness:
        targets = S.select_parts(nodes, wall_part) if wall_part else \
            [n for n in nodes if not n.get("assembly") and n.get("shape") is not None]
        checks["wall_thickness"] = {n["path"]: S.estimate_wall(n["shape"], wall_samples) for n in targets}
    return _data(path, nodes, checks)


@mcp.tool()
def list_parts(step_path: str) -> str:
    """列出 STEP 装配树与零件几何（尺寸、体积、孔数、原点、同名件复用）。"""
    try:
        return _dumps(_review(step_path))
    except Exception as e:
        return _dumps({"error": "%s: %s" % (type(e).__name__, e)})


@mcp.tool()
def review_step(step_path: str,
                fit_child: str = "", fit_parent: str = "", fit_clearance: float = 0.0,
                align_a: str = "", align_b: str = "", align_tol: float = 0.5,
                limit_part: str = "", limit_zmax: float = 0.0,
                avoid_a: str = "", avoid_b: str = "", avoid_clearance: float = 0.0,
                interference: bool = False, interference_vol: float = 1e-3,
                min_gap: bool = False,
                wall_thickness: bool = False, wall_part: str = "", wall_samples: int = 200,
                include_report: bool = False) -> str:
    """STEP 结构审阅：装配/几何 + 可选配合、孔对齐、限高、避让、干涉、最小间隙、壁厚。"""
    try:
        data = _review(step_path, fit_child, fit_parent, fit_clearance,
                       align_a, align_b, align_tol,
                       limit_part, limit_zmax,
                       avoid_a, avoid_b, avoid_clearance,
                       interference, interference_vol,
                       min_gap, wall_thickness, wall_part, wall_samples)
        if include_report:
            data["report_markdown"] = S.render_md(data)
        return _dumps(data)
    except Exception as e:
        return _dumps({"error": "%s: %s" % (type(e).__name__, e)})


def main():
    try:
        mcp.run(transport="stdio")
    except TypeError:
        mcp.run()


if __name__ == "__main__":
    main()