#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pcb_review.py  —  PCB 静态规则审核器

用途
  解析 Altium ASCII 工程(.PcbDoc/.SchDoc, Protel ASCII)，结合 design_meta.json，
  按 rules.json 输出可复现的 findings(JSON) 与 Markdown 报告。

边界
  仅做静态规则 / 几何 / 清单级审核；不做 SI/PI/EMC/热仿真，不替代安规认证与工厂 DFM。
  缺少 design_meta 时，依赖设计意图的规则会标为 review(待确认)，而不是误判。

用法
  python3 pcb_review.py --pcb board.pcbdoc [--sch board.schdoc] [--meta design_meta.json]
                        [-o report.md] [--json findings.json] [--fail-on high]

退出码
  0 通过；1 存在 medium；2 存在 high/critical
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
MIL2MM = 0.0254
SEV_ORDER = ["critical", "high", "medium", "low", "info", "review"]


def load_rules():
    p = os.path.join(BASE, "rules.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {r["id"]: r for r in data.get("rules", [])}, data
    return {}, {"severity_order": SEV_ORDER}


def num(x, default=0.0):
    if x is None:
        return default
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", str(x))
    return float(m.group(1)) if m else default


def parse_altium(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    recs = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        d = {}
        for seg in s[1:].split("|"):
            if "=" in seg:
                k, v = seg.split("=", 1)
                d[k] = v
        recs.append(d)
    return recs


def is_copper_layer_name(name):
    n = (name or "").lower()
    return n in ("top layer", "bottom layer") or bool(re.match(r"in\d+\.cu$", n))


def is_signal_ascii_layer(layer):
    return layer in ("TOP", "BOTTOM", "MID1", "MID2", "MID3", "MID4", "MID5", "MID6")


def board_size_mil(recs):
    for r in recs:
        if r.get("RECORD") == "Board" and "VX0" in r:
            xs, ys = [], []
            for k, v in r.items():
                if re.match(r"VX\d+$", k):
                    xs.append(num(v))
                elif re.match(r"VY\d+$", k):
                    ys.append(num(v))
            if xs and ys:
                return max(xs) - min(xs), max(ys) - min(ys)
    for r in recs:
        if "SHEETWIDTH" in r and "SHEETHEIGHT" in r:
            return num(r["SHEETWIDTH"]), num(r["SHEETHEIGHT"])
    return 0.0, 0.0


def stack_info(recs):
    for r in recs:
        if r.get("RECORD") == "Board" and "V9_STACK_LAYER0_NAME" in r:
            names = {}
            for k, v in r.items():
                m = re.match(r"V9_STACK_LAYER(\d+)_NAME$", k)
                if m:
                    names[int(m.group(1))] = v
            out = []
            for i in sorted(names):
                cop = r.get("V9_STACK_LAYER%d_COPTHICK" % i)
                diel = r.get("V9_STACK_LAYER%d_DIELHEIGHT" % i)
                out.append({
                    "idx": i,
                    "name": names[i],
                    "cop_mil": num(cop) if cop is not None else None,
                    "diel_mil": num(diel) if diel is not None else None,
                })
            return out
    return []


def collect(recs, sch_recs):
    ctx = {
        "components": [], "tracks": [], "vias": [], "pads": [], "texts": [],
        "rules": [], "polygons": [], "regions": [], "planes": 0, "netlabels": [],
        "stack": stack_info(recs),
    }
    ctx["w_mil"], ctx["h_mil"] = board_size_mil(recs)
    for r in recs:
        t = r.get("RECORD")
        if t == "Component":
            ctx["components"].append({
                "id": r.get("ID"), "designator": r.get("SOURCEDESIGNATOR", ""),
                "pattern": r.get("PATTERN", ""), "layer": r.get("LAYER", ""),
                "x": num(r.get("X")), "y": num(r.get("Y")),
            })
        elif t == "Track":
            lay = r.get("LAYER", "")
            if is_signal_ascii_layer(lay):
                ctx["tracks"].append({
                    "layer": lay, "width": num(r.get("WIDTH")),
                    "x1": num(r.get("X1")), "y1": num(r.get("Y1")),
                    "x2": num(r.get("X2")), "y2": num(r.get("Y2")),
                })
        elif t == "Via":
            ctx["vias"].append({"diameter": num(r.get("DIAMETER")), "hole": num(r.get("HOLESIZE"))})
        elif t == "Pad":
            ctx["pads"].append({"component": r.get("COMPONENT"), "layer": r.get("LAYER", ""),
                                "shape": r.get("SHAPE", ""), "hole": num(r.get("HOLESIZE")),
                                "xsize": num(r.get("XSIZE")), "ysize": num(r.get("YSIZE"))})
        elif t == "Text":
            ctx["texts"].append({"text": r.get("TEXT", ""), "layer": r.get("LAYER", "")})
        elif t == "DXPRule":
            ctx["rules"].append(r)
        elif t == "Polygon":
            ctx["polygons"].append({"layer": r.get("LAYER", "")})
        elif t == "Region":
            ctx["regions"].append({"layer": r.get("LAYER", "")})
        elif t == "Plane":
            ctx["planes"] += 1
    if sch_recs:
        for r in sch_recs:
            if r.get("RECORD") == "25" and r.get("TEXT"):
                ctx["netlabels"].append(r["TEXT"])
    return ctx


def ipc2221_width_mil(current_a, delta_t_c=10.0, oz=1.0, external=True):
    k = 0.048 if external else 0.024
    area = (current_a / (k * (delta_t_c ** 0.44))) ** (1.0 / 0.725)
    thickness = max(oz, 0.5) * 1.378
    return area / thickness


def cap_uF(s):
    s = (s or "").upper()
    m = re.search(r"(\d+(?:\.\d+)?)\s*U", s)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*N", s)
    if m:
        return float(m.group(1)) / 1000.0
    return 0.0


def cap_v(s):
    s = (s or "").upper()
    m = re.search(r"(\d+(?:\.\d+)?)\s*V\b", s)
    return float(m.group(1)) if m else 0.0


def right_angles(tracks):
    ends = {}
    for t in tracks:
        p1 = (round(t["x1"], 1), round(t["y1"], 1))
        p2 = (round(t["x2"], 1), round(t["y2"], 1))
        ends.setdefault(p1, []).append(p2)
        ends.setdefault(p2, []).append(p1)
    right = acute = 0
    for p, plist in ends.items():
        n = len(plist)
        for i in range(n):
            for j in range(i + 1, n):
                v1 = (plist[i][0] - p[0], plist[i][1] - p[1])
                v2 = (plist[j][0] - p[0], plist[j][1] - p[1])
                n1 = math.hypot(*v1); n2 = math.hypot(*v2)
                if n1 < 20 or n2 < 20:
                    continue
                c = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
                ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
                if 5 < ang < 85:
                    acute += 1
                elif 85 <= ang <= 95:
                    right += 1
    return right, acute


def build_findings(ctx, meta, RULES, meta_missing):
    F = []

    def add(rid, severity=None, evidence="", fix="", detail=""):
        r = RULES.get(rid, {})
        F.append({
            "rule_id": rid,
            "title": r.get("title", rid),
            "category": r.get("category", ""),
            "severity": severity or r.get("severity", "info"),
            "standard": r.get("standard", ""),
            "evidence": evidence,
            "detail": detail,
            "fix": fix or r.get("guide", ""),
        })

    ac = bool(meta.get("ac_input"))
    components = ctx["components"]
    patterns = [c["pattern"].upper() for c in components]
    texts_u = " ".join(t["text"].upper() for t in ctx["texts"])

    copper = [s for s in ctx["stack"] if is_copper_layer_name(s["name"])]
    inner = [s for s in copper if re.match(r"in\d+\.cu", s["name"].lower())]
    undef = [s["name"] for s in copper if s["cop_mil"] is None or s["cop_mil"] == 0]
    diel_undef = [s["name"] for s in ctx["stack"] if "dielectric" in s["name"].lower()
                  and (s["diel_mil"] is None or s["diel_mil"] == 0)]
    if undef:
        add("STACK-01", "high", "铜厚为0/未定义: %s；介质厚度为0的层: %s" % (", ".join(undef), ", ".join(diel_undef) or "无"),
            detail="层叠参数不完整会导致板厚、阻抗、结构不可控")

    inner_layers = set()
    for s in inner:
        inner_layers.add(s["name"])
    poly_layers = set(p["layer"] for p in ctx["polygons"])
    inner_poly = [l for l in poly_layers if l in ("MID1", "MID2", "MID3", "MID4")]
    if ctx["planes"] == 0 and not inner_poly:
        add("STACK-02", "high", "无 Plane 记录；内层无铺铜；Polygon 仅在 %s" % (", ".join(sorted(poly_layers)) or "无"),
            detail="4层板内层仅走信号，无完整 GND/电源平面")

    oz = float(meta.get("copper_oz_outer") or 1.0)
    if oz < 2 and (meta.get("output_current_A") or meta.get("per_slot_current_A")):
        add("STACK-03", "medium", "外层铜厚 %.1f oz" % oz)

    creep = [r for r in ctx["rules"] if r.get("RULEKIND") == "Creepage"]
    if ac:
        if not creep:
            add("SAFE-01", "high", "未发现 Creepage 规则")
        else:
            for r in creep:
                d = num(r.get("CHECKDISTANCE"))
                ign = r.get("IGNOREINTERNALLAYERS", "").upper() == "TRUE"
                if d <= 0 or ign:
                    add("SAFE-01", "high", "Creepage 规则 '%s': CHECKDISTANCE=%s, IGNOREINTERNALLAYERS=%s" % (
                        r.get("NAME", ""), r.get("CHECKDISTANCE"), r.get("IGNOREINTERNALLAYERS")))
                    break

    clears = [r for r in ctx["rules"] if r.get("RULEKIND") == "Clearance"]
    if ac:
        max_gap = 0.0
        has_ac_scope = False
        for r in clears:
            max_gap = max(max_gap, num(r.get("GAP")))
            scope = (r.get("SCOPE1EXPRESSION", "") + r.get("SCOPE2EXPRESSION", "")).upper()
            if any(k in scope for k in ("AC", "HIGHVOLT", "HV", "MAINS", "PRI")):
                has_ac_scope = True
        if not has_ac_scope and max_gap < 118:
            add("SAFE-02", "high", "Clearance 最大 GAP=%.1f mil(%.2f mm)，且无 AC/高压专用 Scope" % (max_gap, max_gap * MIL2MM))

    ac_term = [c for c, p in zip(components, patterns) if any(k in p for k in ("TB", "SCREW", "TERMINAL", "3WAY"))]
    if ac and ac_term:
        textvals = {t["text"].upper().strip() for t in ctx["texts"]}
        lab = (any(v in ("PE", "EARTH", "LIVE", "NEUTRAL", "AC_L", "AC_N") for v in textvals)
               or ("L" in textvals and "N" in textvals)
               or bool(re.search(r"火线|零线|接地", texts_u)))
        if not lab:
            add("SAFE-03", "high", "检出 %d 个 AC 端子，但丝印中无 L/N/PE 或相序标识" % len(ac_term))

    cap_total, cap_vmax = 0.0, 0.0
    for c in components:
        v = cap_uF(c["pattern"])
        if v > 0:
            cap_total += v
            cap_vmax = max(cap_vmax, cap_v(c["pattern"]))
    if cap_total > 0:
        bus_v = float(meta.get("dc_bus_voltage_V") or cap_vmax or 0.0)
        energy = 0.5 * (cap_total * 1e-6) * bus_v * bus_v
        bleed_auto = any(k in p for p in patterns for k in ("BLEED", "DISCHARGE", "DUMP"))
        bleed = bleed_auto or bool(meta.get("bleed_resistor"))
        if energy > 20 and not bleed:
            add("SAFE-04", "high", "母线电容合计 %.0f uF，按 %.0f V 储能约 %.1f J，未检出泄放电路" % (
                cap_total, bus_v, energy))

    prot_auto = any(k in p for p in patterns for k in ("FUSE", "MOV", "TVS", "VARISTOR", "CHOKE", "X2", "Y2"))
    if ac and not (prot_auto or meta.get("input_protection")):
        add("SAFE-05", "medium", "未检出保险丝/压敏/TVS/共模等输入保护器件")

    if ac:
        g = meta.get("single_point_ground")
        if g is None:
            add("SAFE-06", "review", "未提供单点接地/PE 连接信息")
        elif g is False:
            add("SAFE-06", "high", "meta.single_point_ground=false，接地架构存疑")

    outer_widths = [t["width"] for t in ctx["tracks"] if t["layer"] in ("TOP", "BOTTOM") and t["width"] > 0]
    max_outer = max(outer_widths) if outer_widths else 0.0
    max_all = max([t["width"] for t in ctx["tracks"]] or [0.0])
    cur = meta.get("per_slot_current_A") or meta.get("output_current_A")
    if cur and max_outer > 0:
        req = ipc2221_width_mil(float(cur), float(meta.get("max_delta_t_C") or 10), oz, external=True)
        if meta.get("current_via_busbar") is True:
            add("PWR-01", "review", "外层最宽 %.2f mil(%.2f mm)；按 IPC-2221/%.0fA/ΔT=%.0fC/%.0foz 需约 %.0f mil(%.1f mm)。已声明主载流走铜排" % (
                max_outer, max_outer * MIL2MM, float(cur), float(meta.get("max_delta_t_C") or 10), oz, req, req * MIL2MM),
                detail="需核算铜排截面积、焊盘与接触电阻")
            add("PWR-02", "review", "已声明铜排载流，需按实际电流核算铜排/焊盘温升")
        elif max_outer < req:
            add("PWR-01", "high", "外层最宽 %.2f mil(%.2f mm) < 按 IPC-2221/%.0fA/ΔT=%.0fC/%.0foz 估算所需 %.0f mil(%.1f mm)" % (
                max_outer, max_outer * MIL2MM, float(cur), float(meta.get("max_delta_t_C") or 10), oz, req, req * MIL2MM))
    else:
        add("PWR-01", "review", "未提供输出电流，无法量化载流；当前最宽走线 %.2f mil(%.2f mm)" % (
            max_all, max_all * MIL2MM))

    n_mod = len([c for c in components if re.search(r"CON-PCI|PCIH", (c["pattern"] or "").upper())])
    n_100n = sum(1 for p in patterns if abs(cap_uF(p) - 0.1) < 0.001)
    if n_mod >= 2 and n_100n < n_mod:
        add("PWR-03", "medium", "检出约 %d 个模块接口，但 0.1uF 级高频去耦仅 %d 个" % (n_mod, n_100n))

    if ctx["vias"]:
        add("PWR-04", "review", "过孔 %d 个，孔径 %.2f/%.2f mm；电源换层处需按电流核算并联数量" % (
            len(ctx["vias"]), (ctx["vias"][0]["diameter"] * MIL2MM), (ctx["vias"][0]["hole"] * MIL2MM)))

    if meta.get("high_speed_interfaces") and (ctx["planes"] == 0 and not inner_poly):
        add("SIG-01", "medium", "存在高速/差分接口 %s，但无内层参考平面" % (meta.get("high_speed_interfaces")))

    nets = set(n.upper() for n in ctx["netlabels"])
    if nets & {"SCL", "SDA", "SMB_ALERT"} and meta.get("communication_isolation") is None:
        add("SIG-02", "review", "检出 I2C/SMBus 信号，未确认上拉/终端/隔离")

    L = max(ctx["w_mil"], ctx["h_mil"]) * MIL2MM
    if L > 500:
        add("DFM-01", "medium", "板长 %.1f mm > 500mm" % L)
        add("DFM-04", "info", "长板需评估中间支撑、拼板方向与翘曲")

    if meta.get("smt_assembly"):
        has_mark = bool(re.search(r"MARK|FIDUCIAL|FID", texts_u)) or any("FID" in p for p in patterns)
        if not has_mark:
            add("DFM-02", "medium", "SMT 贴装但未检出 Mark 点")

    pci = [p for p in patterns if "PCI" in p]
    if len(pci) >= 3 and meta.get("keying") in (None, "unknown"):
        add("DFM-03", "info", "检出 %d 个同型号插槽连接器，未见防呆/keying 说明" % len(pci))

    ra, ac_ang = right_angles(ctx["tracks"])
    if ra + ac_ang > 0:
        add("DFM-05", "info", "粗计直角/近直角拐点约 %d 处、锐角约 %d 处（仅几何估算，仅供参考）" % (ra, ac_ang))

    if ac:
        if meta.get("ac_same_source") is None:
            add("FUNC-01", "review", "未确认多路 AC 是否同源/同相")
        elif meta.get("ac_same_source") is False:
            add("FUNC-01", "high", "多路 AC 非同源/同相，输出并联存在环流/缺相风险")

    if (nets & {"+SENSE", "-SENSE", "+LS", "-LS", "I_PROG", "V_PROG"}) and meta.get("load_share_topology") in (None, "unknown"):
        add("FUNC-02", "review", "检出 SENSE/load-share 信号，未确认单点/等长/对称拓扑")

    if n_mod >= 2 and meta.get("output_or_ing") in (None, "unknown"):
        add("FUNC-03", "review", "%d 路并联输出，未确认防反灌/ORing" % n_mod)

    hs = meta.get("hot_swap")
    if hs is True and not meta.get("hot_swap_protection"):
        add("FUNC-04", "high", "声明支持热插拔但无长短针分级/预充/软启动说明")
    elif hs is None:
        add("FUNC-04", "review", "未确认是否支持热插拔")

    drc = meta.get("drc_report")
    if drc:
        p = drc if os.path.isabs(drc) else os.path.join(os.path.dirname(meta.get("_path", "")), drc)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            errs = len(re.findall(r"(?im)^\s*(error|fatal)", txt))
            warns = len(re.findall(r"(?im)^\s*warning", txt))
            if errs > 0:
                add("DRC-01", "critical", "DRC 报告: %d error / %d warning" % (errs, warns))

    if meta_missing:
        add("META-00", "review", "未提供 design_meta.json，载流/安规/功能类规则仅作几何参考")
    return F


def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(ctx, meta, findings, rules_doc):
    lines = []
    lines.append("# PCB 审核报告")
    lines.append("")
    lines.append("- 板名: **%s**" % (meta.get("board_name") or "未提供"))
    lines.append("- 生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 尺寸: **%.1f x %.1f mm**" % (ctx["w_mil"] * MIL2MM, ctx["h_mil"] * MIL2MM))
    lines.append("- 元件: %d；走线: %d；过孔: %d；焊盘: %d；铺铜: %d；网络标签: %d" % (
        len(ctx["components"]), len(ctx["tracks"]), len(ctx["vias"]), len(ctx["pads"]),
        len(ctx["polygons"]), len(ctx["netlabels"])))
    lines.append("")
    cnt = {s: 0 for s in SEV_ORDER}
    for f in findings:
        cnt[f["severity"]] = cnt.get(f["severity"], 0) + 1
    if cnt.get("critical") or cnt.get("high"):
        concl = "**结论: 存在原则性问题，不建议直接投板。**"
    elif cnt.get("medium"):
        concl = "**结论: 无致命问题，但存在需整改的中等风险。**"
    else:
        concl = "**结论: 未发现原则性问题（仍有待确认项）。**"
    lines.append(concl)
    lines.append("")
    lines.append("| critical | high | medium | low | info | review |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| %d | %d | %d | %d | %d | %d |" % (
        cnt.get("critical", 0), cnt.get("high", 0), cnt.get("medium", 0),
        cnt.get("low", 0), cnt.get("info", 0), cnt.get("review", 0)))
    lines.append("")

    labels = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "info": "提示", "review": "待确认"}
    for sev in SEV_ORDER:
        group = [f for f in findings if f["severity"] == sev]
        if not group:
            continue
        lines.append("## %s (%d)" % (labels[sev], len(group)))
        lines.append("")
        lines.append("| 级别 | 规则 | 问题 | 证据 | 整改建议 |")
        lines.append("|---|---|---|---|---|")
        for f in group:
            lines.append("| %s | %s | %s | %s | %s |" % (
                labels[sev], f["rule_id"], md_escape(f["title"]),
                md_escape(f["evidence"]), md_escape(f["fix"])))
        lines.append("")

    lines.append("## 附录: 解析数据")
    lines.append("")
    lines.append("### 层叠")
    if ctx["stack"]:
        lines.append("| 层 | 名称 | 铜厚(mil) | 介质(mil) |")
        lines.append("|---|---|---|---|")
        for s in ctx["stack"]:
            lines.append("| %d | %s | %s | %s |" % (
                s["idx"], s["name"],
                "-" if s["cop_mil"] is None else s["cop_mil"],
                "-" if s["diel_mil"] is None else s["diel_mil"]))
    else:
        lines.append("未解析到层叠信息")
    lines.append("")
    lines.append("### 走线宽度分布")
    wc = {}
    for t in ctx["tracks"]:
        wc[t["layer"]] = wc.get(t["layer"], {})
        wc[t["layer"]][t["width"]] = wc[t["layer"]].get(t["width"], 0) + 1
    for lay in sorted(wc):
        items = sorted(wc[lay].items(), key=lambda kv: -kv[1])
        lines.append("- %s: %s" % (lay, ", ".join("%.2fmil x%d" % (w, n) for w, n in items)))
    lines.append("")
    if ctx["netlabels"]:
        from collections import Counter
        lines.append("### 网络标签 Top20")
        for k, n in Counter(ctx["netlabels"]).most_common(20):
            lines.append("- %s: %d" % (k, n))
    lines.append("")
    lines.append("> 本报告为静态规则审核，不构成安规认证。DRC/ERC 请在 Altium 中实际运行。")
    return "\n".join(lines)


def compute_exit(summary, fail_on):
    order = ["critical", "high", "medium"]
    if fail_on == "none":
        return 0
    idx = order.index(fail_on)
    for i, s in enumerate(order):
        if summary.get(s):
            return 2 if i <= idx else 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="PCB 静态规则审核器 (Altium ASCII)")
    ap.add_argument("--pcb", required=True, help="Altium ASCII .pcbdoc/.PcbDoc")
    ap.add_argument("--sch", help="Altium ASCII .schdoc/.SchDoc")
    ap.add_argument("--meta", help="design_meta.json")
    ap.add_argument("-o", "--out", help="Markdown 报告输出")
    ap.add_argument("--json", dest="json_out", help="findings JSON 输出")
    ap.add_argument("--fail-on", default="high", choices=["critical", "high", "medium", "none"])
    args = ap.parse_args()

    RULES, rules_doc = load_rules()
    if not os.path.exists(args.pcb):
        print("找不到文件: %s" % args.pcb, file=sys.stderr)
        return 3
    recs = parse_altium(args.pcb)
    sch = parse_altium(args.sch) if args.sch and os.path.exists(args.sch) else []
    meta, meta_missing = {}, True
    if args.meta and os.path.exists(args.meta):
        with open(args.meta, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["_path"] = args.meta
        meta_missing = False

    ctx = collect(recs, sch)
    findings = build_findings(ctx, meta, RULES, meta_missing)
    findings.sort(key=lambda f: SEV_ORDER.index(f["severity"]) if f["severity"] in SEV_ORDER else 99)

    md = render_md(ctx, meta, findings, rules_doc)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("报告已写入: %s" % args.out)
    else:
        print(md)

    summary = {}
    for f in findings:
        summary[f["severity"]] = summary.get(f["severity"], 0) + 1
    result = {
        "board": meta.get("board_name", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "size_mm": [round(ctx["w_mil"] * MIL2MM, 2), round(ctx["h_mil"] * MIL2MM, 2)],
        "summary": summary,
        "findings": findings,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("findings JSON: %s" % args.json_out)

    return compute_exit(summary, args.fail_on)


if __name__ == "__main__":
    sys.exit(main())