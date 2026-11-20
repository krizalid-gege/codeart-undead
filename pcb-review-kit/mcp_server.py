#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py — PCB 审核薄 MCP Server

依赖:  pip install mcp
复用:  pcb_review.py / rules.json
环境:  PCB_REVIEW_ROOT  允许读取的根目录(默认脚本上级目录)

运行:
  python3 mcp_server.py                 # stdio (Gemini 以子进程拉起)
  python3 mcp_server.py --http 8765     # streamable-http, 仅监听 127.0.0.1

工具:
  review_pcb(pcb_path, sch_path="", meta_path="", include_report=False)
  parse_board(pcb_path, sch_path="")
  list_rules()
  get_rule(rule_id)
"""
import argparse
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import pcb_review as E  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP as _Server
except Exception:
    from mcp.server.mcpserver import MCPServer as _Server

ROOT = os.path.realpath(os.environ.get("PCB_REVIEW_ROOT", os.path.dirname(BASE)))
RULES, RULES_DOC = E.load_rules()
mcp = _Server("pcb-review")


def _safe(path):
    if not path:
        return ""
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    real = os.path.realpath(p)
    if not (real == ROOT or real.startswith(ROOT + os.sep)):
        raise ValueError("path outside PCB_REVIEW_ROOT: %s" % real)
    if not os.path.exists(real):
        raise FileNotFoundError("not found: %s" % real)
    return real


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _review(pcb_path, sch_path="", meta_path="", include_report=False):
    meta, meta_missing = {}, True
    if meta_path:
        mp = _safe(meta_path)
        with open(mp, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["_path"] = mp
        meta_missing = False
    recs = E.parse_altium(_safe(pcb_path))
    schrecs = E.parse_altium(_safe(sch_path)) if sch_path else []
    ctx = E.collect(recs, schrecs)
    findings = E.build_findings(ctx, meta, RULES, meta_missing)
    findings.sort(key=lambda f: E.SEV_ORDER.index(f["severity"]) if f["severity"] in E.SEV_ORDER else 99)
    summary = {}
    for f in findings:
        summary[f["severity"]] = summary.get(f["severity"], 0) + 1
    out = {
        "board": meta.get("board_name", ""),
        "size_mm": [round(ctx["w_mil"] * E.MIL2MM, 2), round(ctx["h_mil"] * E.MIL2MM, 2)],
        "summary": summary,
        "findings": findings,
        "exit_code": E.compute_exit(summary, "high"),
    }
    if include_report:
        out["report_markdown"] = E.render_md(ctx, meta, findings, RULES_DOC)
    return out


@mcp.tool()
def review_pcb(pcb_path: str, sch_path: str = "", meta_path: str = "", include_report: bool = False) -> str:
    """审核 Altium ASCII 工程，返回 findings JSON（含 summary/exit_code）。路径相对 PCB_REVIEW_ROOT 或绝对路径。"""
    try:
        return _dumps(_review(pcb_path, sch_path, meta_path, include_report))
    except Exception as e:
        return _dumps({"error": "%s: %s" % (type(e).__name__, e)})


@mcp.tool()
def parse_board(pcb_path: str, sch_path: str = "") -> str:
    """提取板子结构摘要：尺寸、层叠、各层走线宽度、元件/过孔/焊盘数、网络标签 Top30。"""
    try:
        ctx = E.collect(E.parse_altium(_safe(pcb_path)),
                        E.parse_altium(_safe(sch_path)) if sch_path else [])
        wc = {}
        for t in ctx["tracks"]:
            wc.setdefault(t["layer"], {})
            k = round(t["width"], 2)
            wc[t["layer"]][k] = wc[t["layer"]].get(k, 0) + 1
        return _dumps({
            "size_mm": [round(ctx["w_mil"] * E.MIL2MM, 2), round(ctx["h_mil"] * E.MIL2MM, 2)],
            "stack": ctx["stack"],
            "track_width_by_layer": wc,
            "components": len(ctx["components"]),
            "vias": len(ctx["vias"]),
            "pads": len(ctx["pads"]),
            "polygons": ctx["polygons"],
            "netlabels_top": Counter(ctx["netlabels"]).most_common(30),
        })
    except Exception as e:
        return _dumps({"error": "%s: %s" % (type(e).__name__, e)})


@mcp.tool()
def list_rules() -> str:
    """返回全部审核规则（id/severity/title/standard/guide）。"""
    return _dumps([dict(id=k, **{kk: vv for kk, vv in r.items() if kk != "id"}) for k, r in RULES.items()])


@mcp.tool()
def get_rule(rule_id: str) -> str:
    """返回单条规则详情。"""
    r = RULES.get(rule_id)
    return _dumps(r) if r else _dumps({"error": "unknown rule_id: %s" % rule_id})


def main():
    ap = argparse.ArgumentParser(description="PCB review MCP server")
    ap.add_argument("--http", type=int, default=0, help="streamable-http 端口；0 表示 stdio")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if args.http:
        try:
            mcp.run(transport="streamable-http", host=args.host, port=args.http)
        except TypeError:
            try:
                mcp.settings.host = args.host
                mcp.settings.port = args.http
            except Exception:
                pass
            try:
                mcp.run(transport="streamable-http")
            except TypeError:
                mcp.run(transport="sse")
    else:
        try:
            mcp.run(transport="stdio")
        except TypeError:
            mcp.run()


if __name__ == "__main__":
    main()