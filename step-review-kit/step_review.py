#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step_review.py — STEP 3D 结构审阅器

能力:
  1) 装配核对: 零件数/实例数/层级/坐标原点/同名件复用(referred shape)
  2) 几何量: 外形尺寸、包围盒、体积、孔位(圆柱轴线)、孔半径
  3) 干涉/间隙: 包围盒预筛 + BRep 精确布尔干涉、BRepExtrema 最小距离
  4) 配合检查: --fit / --align-holes / --limit-height / --avoid

运行(需要 LD_LIBRARY_PATH 指向 libGL stub):
  ./run_step_review.sh model.step --list
  ./run_step_review.sh model.step --report report.md --json out.json
  ./run_step_review.sh model.step --fit PCB housing --clearance 2
  ./run_step_review.sh model.step --align-holes PCB housing --tol 0.5
  ./run_step_review.sh model.step --limit-height CAP --zmax 25
  ./run_step_review.sh model.step --avoid BUSBAR housing --clearance 3
  ./run_step_review.sh model.step --interference
  ./run_step_review.sh model.step --min-gap
"""
import argparse
import json
import math
import os
import sys

try:
    import cadquery  # noqa: F401
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDataStd import TDataStd_Name
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Pnt, gp_Dir, gp_Lin
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS
except Exception as exc:  # pragma: no cover
    sys.stderr.write(
        "无法加载 cadquery/OCP: %s\n"
        "请用 ./run_step_review.sh 运行（它会设置 LD_LIBRARY_PATH 指向 libGL stub）。\n" % exc
    )
    raise


def r3(x):
    try:
        return round(float(x), 3)
    except Exception:
        return None


def label_name(label):
    attr = TDataStd_Name()
    try:
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            val = attr.Get()
            try:
                return val.ToExtString()
            except Exception:
                return str(val)
    except Exception:
        pass
    return ""


def label_entry(label):
    try:
        return label.EntryDump()
    except Exception:
        try:
            return str(label.Tag())
        except Exception:
            return ""


def shape_metrics(shape):
    out = {}
    try:
        box = Bnd_Box()
        box.SetGap(0.0)
        BRepBndLib.Add_s(shape, box)
        g = box.Get()
        bbox = [r3(v) for v in g]
        out["bbox"] = bbox
        out["size"] = [r3(bbox[3] - bbox[0]), r3(bbox[4] - bbox[1]), r3(bbox[5] - bbox[2])]
    except Exception:
        out["bbox"] = None
        out["size"] = None
    try:
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        out["volume"] = r3(props.Mass())
    except Exception:
        out["volume"] = None
    return out


def extract_holes(shape):
    holes = []
    seen = set()
    try:
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            face = TopoDS.Face_s(exp.Current())
            surf = BRepAdaptor_Surface(face)
            if surf.GetType() == GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                ax = cyl.Axis()
                p = ax.Location()
                d = ax.Direction()
                h = {
                    "r": r3(cyl.Radius()),
                    "p": [r3(p.X()), r3(p.Y()), r3(p.Z())],
                    "d": [r3(d.X()), r3(d.Y()), r3(d.Z())],
                }
                key = (h["r"], tuple(h["p"]), tuple(h["d"]))
                if key not in seen:
                    seen.add(key)
                    holes.append(h)
            exp.Next()
    except Exception:
        pass
    return holes


def union_bbox(nodes):
    bs = [n["bbox"] for n in nodes if n.get("bbox")]
    if not bs:
        return None
    return [min(b[0] for b in bs), min(b[1] for b in bs), min(b[2] for b in bs),
            max(b[3] for b in bs), max(b[4] for b in bs), max(b[5] for b in bs)]


def bbox_overlap(a, b, eps=1e-6):
    if not a or not b:
        return False
    return not (a[3] < b[0] - eps or b[3] < a[0] - eps or
                a[4] < b[1] - eps or b[4] < a[1] - eps or
                a[5] < b[2] - eps or b[5] < a[2] - eps)


def common_volume(a, b):
    try:
        algo = BRepAlgoAPI_Common(a, b)
        algo.Build()
        if not algo.IsDone():
            return None
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(algo.Shape(), props)
        return props.Mass()
    except Exception:
        return None


def min_distance(a, b):
    try:
        d = BRepExtrema_DistShapeShape(a, b)
        d.Perform()
        if d.IsDone():
            return d.Value()
    except Exception:
        pass
    return None


def line_line_distance(p1, d1, p2, d2):
    def norm(v):
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n > 1e-12 else v
    d1 = norm(d1)
    d2 = norm(d2)
    w = [p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]]
    cross = [d1[1] * d2[2] - d1[2] * d2[1],
             d1[2] * d2[0] - d1[0] * d2[2],
             d1[0] * d2[1] - d1[1] * d2[0]]
    cn = math.sqrt(sum(x * x for x in cross))
    if cn < 1e-9:
        # 平行: 点到直线距离
        cw = [d1[0] * w[0] + d1[1] * w[1] + d1[2] * w[2]]
        proj = [c * cw[0] for c in d1]
        diff = [w[0] - proj[0], w[1] - proj[1], w[2] - proj[2]]
        return math.sqrt(sum(x * x for x in diff))
    return abs(sum(w[i] * cross[i] for i in range(3)) / cn)


def build_nodes(tool):
    nodes = []

    def walk(label, depth, parent_path):
        name = label_name(label) or ""
        path = (parent_path + "/" + name) if parent_path else (name or "root")
        is_asm = False
        is_ref = False
        try:
            is_asm = bool(tool.IsAssembly_s(label))
            is_ref = bool(tool.IsReference_s(label))
        except Exception:
            pass
        referred = ""
        if is_ref:
            try:
                ref_label = TDF_Label()
                if tool.GetReferredShape_s(label, ref_label):
                    referred = label_entry(ref_label)
            except Exception:
                pass
        node = {
            "path": path, "name": name, "depth": depth, "assembly": is_asm,
            "reference": is_ref, "referred": referred,
        }
        shape = None
        if not is_asm:
            try:
                shape = tool.GetShape_s(label)
            except Exception:
                shape = None
        node["shape"] = shape
        if shape is not None:
            node.update(shape_metrics(shape))
        origin = None
        bbox = node.get("bbox")
        if bbox:
            origin = [r3((bbox[0] + bbox[3]) / 2.0),
                      r3((bbox[1] + bbox[4]) / 2.0),
                      r3((bbox[2] + bbox[5]) / 2.0)]
        if origin is None and shape is not None:
            try:
                t = shape.Location().Transformation().TranslationPart()
                origin = [r3(t.X()), r3(t.Y()), r3(t.Z())]
            except Exception:
                origin = None
        if origin is None:
            origin = [0, 0, 0]
        node["origin"] = origin
        nodes.append(node)
        if is_asm:
            comps = TDF_LabelSequence()
            try:
                tool.GetComponents_s(label, comps)
            except Exception:
                return
            for i in range(1, comps.Length() + 1):
                try:
                    walk(comps.Value(i), depth + 1, path)
                except Exception:
                    pass

    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        walk(free.Value(i), 0, "")
    return nodes


def load_step(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError("STEP 读取失败: %s (status=%s)" % (path, status))
    reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    return tool, build_nodes(tool)


def select_parts(nodes, query):
    q = (query or "").lower()
    return [n for n in nodes if (not n.get("assembly")) and n.get("shape") is not None
            and (q in (n.get("name") or "").lower() or q in n.get("path", "").lower())]


def public_node(n):
    d = {k: v for k, v in n.items() if k != "shape"}
    if n.get("shape") is not None:
        d["holes"] = extract_holes(n["shape"])
        d["hole_count"] = len(d["holes"])
    else:
        d["holes"] = []
        d["hole_count"] = 0
    return d


def check_fit(child, parent, clearance):
    cb = union_bbox(child)
    pb = union_bbox(parent)
    if not cb or not pb:
        return {"ok": False, "error": "bbox 不可用"}
    gaps = {
        "xmin": r3(cb[0] - pb[0]), "ymin": r3(cb[1] - pb[1]), "zmin": r3(cb[2] - pb[2]),
        "xmax": r3(pb[3] - cb[3]), "ymax": r3(pb[4] - cb[4]), "zmax": r3(pb[5] - cb[5]),
    }
    inside = all(v is not None and v >= -1e-6 for v in gaps.values())
    ok = inside and all(v >= clearance - 1e-6 for v in gaps.values())
    return {"ok": ok, "inside": inside, "clearance_required": clearance,
            "gaps": gaps, "child_bbox": cb, "parent_bbox": pb}


def check_align(a_nodes, b_nodes, tol):
    ha = []
    hb = []
    for n in a_nodes:
        for h in extract_holes(n["shape"]):
            h["owner"] = n["path"]
            ha.append(h)
    for n in b_nodes:
        for h in extract_holes(n["shape"]):
            h["owner"] = n["path"]
            hb.append(h)
    unmatched = []
    matched = 0
    for a in ha:
        best = None
        best_h = None
        for b in hb:
            dist = line_line_distance(a["p"], a["d"], b["p"], b["d"])
            if best is None or dist < best:
                best = dist
                best_h = b
        if best is not None and best <= tol:
            matched += 1
        else:
            unmatched.append({"hole": a, "nearest": best_h, "distance": r3(best) if best is not None else None})
    return {"a_holes": len(ha), "b_holes": len(hb), "matched": matched,
            "unmatched_count": len(unmatched), "unmatched": unmatched[:50], "tol": tol}


def check_limit(nodes, zmax):
    b = union_bbox(nodes)
    if not b:
        return {"ok": False, "error": "bbox 不可用"}
    return {"ok": b[5] <= zmax + 1e-6, "zmax": b[5], "limit": zmax}


def check_avoid(a_nodes, b_nodes, clearance):
    worst = None
    for a in a_nodes:
        for b in b_nodes:
            d = min_distance(a["shape"], b["shape"])
            if d is None:
                continue
            if worst is None or d < worst["gap"]:
                worst = {"gap": d, "a": a["path"], "b": b["path"]}
    if worst is None:
        return {"ok": False, "error": "无法计算距离"}
    worst["gap"] = r3(worst["gap"])
    worst["required"] = clearance
    worst["ok"] = worst["gap"] >= clearance - 1e-6
    return worst


def check_interference(nodes, vol_tol):
    parts = [n for n in nodes if not n.get("assembly") and n.get("shape") is not None]
    hits = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            if not bbox_overlap(a.get("bbox"), b.get("bbox")):
                continue
            vol = common_volume(a["shape"], b["shape"])
            if vol is not None and vol > vol_tol:
                hits.append({"a": a["path"], "b": b["path"], "volume": r3(vol)})
    hits.sort(key=lambda x: -x["volume"])
    return {"checked_parts": len(parts), "collisions": len(hits), "hits": hits[:100]}


def check_min_gap(nodes, top_n=20):
    parts = [n for n in nodes if not n.get("assembly") and n.get("shape") is not None]
    pairs = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            d = min_distance(a["shape"], b["shape"])
            if d is not None:
                pairs.append({"a": a["path"], "b": b["path"], "gap": r3(d)})
    pairs.sort(key=lambda x: x["gap"])
    return {"pairs_checked": len(pairs), "min_pairs": pairs[:top_n]}


def estimate_wall(shape, max_faces=200):
    faces = []
    try:
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            faces.append(TopoDS.Face_s(exp.Current()))
            exp.Next()
    except Exception:
        return None
    if not faces:
        return None
    try:
        inter = IntCurvesFace_ShapeIntersector()
        inter.Load(shape, 1e-6)
    except Exception:
        return None
    vals = []
    for face in faces[:max(1, max_faces)]:
        try:
            surf = BRepAdaptor_Surface(face)
            u = (surf.FirstUParameter() + surf.LastUParameter()) / 2.0
            v = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
            p = surf.Value(u, v)
            du = surf.DN(u, v, 1, 0)
            dv = surf.DN(u, v, 0, 1)
            n = du.Crossed(dv)
            mag = math.sqrt(n.X() ** 2 + n.Y() ** 2 + n.Z() ** 2)
            if mag < 1e-9:
                continue
            line = gp_Lin(gp_Pnt(p.X(), p.Y(), p.Z()),
                          gp_Dir(-n.X() / mag, -n.Y() / mag, -n.Z() / mag))
            inter.Perform(line, 1e-6, 1e6)
            if not inter.IsDone():
                continue
            best = None
            for i in range(1, inter.NbPnt() + 1):
                q = inter.Pnt(i)
                d = math.sqrt((q.X() - p.X()) ** 2 + (q.Y() - p.Y()) ** 2 + (q.Z() - p.Z()) ** 2)
                if d > 1e-4 and (best is None or d < best):
                    best = d
            if best is not None:
                vals.append(best)
        except Exception:
            continue
    if not vals:
        return None
    vals.sort()
    return {"samples": len(vals), "min": r3(vals[0]),
            "median": r3(vals[len(vals) // 2]), "max": r3(vals[-1])}


def render_md(data):
    lines = []
    lines.append("# STEP 结构审阅报告")
    lines.append("")
    lines.append("- 文件: `%s`" % data["file"])
    lines.append("- 单位: mm")
    lines.append("- 实例数: %d；唯一外形(referred)数: %d；最大层级: %d" % (
        data["assembly"]["instance_count"], data["assembly"]["unique_shape_count"], data["assembly"]["max_depth"]))
    lines.append("")
    if data["assembly"]["reused"]:
        lines.append("## 同名件复用")
        lines.append("")
        lines.append("| referred | 实例数 |")
        lines.append("|---|---|")
        for k, v in data["assembly"]["reused"].items():
            lines.append("| %s | %d |" % (k, v))
        lines.append("")
    lines.append("## 装配树")
    lines.append("")
    for n in data["assembly"]["tree"]:
        indent = "  " * n["depth"]
        tag = " [asm]" if n["assembly"] else (" [ref]" if n["reference"] else "")
        lines.append("- `%s%s`%s" % (indent, n["path"], tag))
    lines.append("")
    lines.append("## 零件几何")
    lines.append("")
    lines.append("| 路径 | 尺寸(mm) | 体积(mm3) | 孔数 | 原点 |")
    lines.append("|---|---|---|---|---|")
    for n in data["parts"]:
        if n["assembly"]:
            continue
        sz = n.get("size") or ["-", "-", "-"]
        lines.append("| `%s` | %s x %s x %s | %s | %d | %s |" % (
            n["path"], sz[0], sz[1], sz[2], n.get("volume"), n.get("hole_count", 0),
            ",".join(str(x) for x in n.get("origin", []))))
    lines.append("")
    checks = data.get("checks") or {}
    if checks:
        lines.append("## 检查项")
        lines.append("")
        for name, res in checks.items():
            lines.append("### %s" % name)
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(res, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
    lines.append("> 几何审阅基于 STEP/BRep；干涉与距离为实体级精确计算，配合检查为包围盒/孔轴线级。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="STEP 3D 结构审阅器")
    ap.add_argument("step", help="STEP 文件 (.step/.stp)")
    ap.add_argument("--list", action="store_true", help="列出装配树与零件")
    ap.add_argument("--report", help="输出 Markdown 报告")
    ap.add_argument("--json", dest="json_out", help="输出 JSON")
    ap.add_argument("--fit", nargs=2, metavar=("CHILD", "PARENT"), help="包围盒配合检查")
    ap.add_argument("--clearance", type=float, default=0.0, help="通用最小间隙默认值 mm")
    ap.add_argument("--fit-clearance", type=float, default=None, help="fit 专用最小间隙 mm")
    ap.add_argument("--avoid-clearance", type=float, default=None, help="avoid 专用最小间隙 mm")
    ap.add_argument("--align-holes", nargs=2, metavar=("A", "B"), help="孔轴线对齐检查")
    ap.add_argument("--tol", type=float, default=0.5, help="孔对齐容差 mm")
    ap.add_argument("--limit-height", metavar="PART", help="限高零件")
    ap.add_argument("--zmax", type=float, help="限高上限 mm")
    ap.add_argument("--avoid", nargs=2, metavar=("A", "B"), help="两零件避让检查")
    ap.add_argument("--interference", action="store_true", help="两两干涉检查")
    ap.add_argument("--interference-vol", type=float, default=1e-3, help="干涉体积阈值 mm3")
    ap.add_argument("--min-gap", action="store_true", help="最小间隙 Top-N")
    ap.add_argument("--wall-thickness", action="store_true", help="壁厚估算(曲面法采样)")
    ap.add_argument("--wall-part", help="仅估算指定零件的壁厚")
    ap.add_argument("--wall-samples", type=int, default=200, help="每零件最大采样面数")
    args = ap.parse_args()

    tool, nodes = load_step(args.step)
    public_all = [public_node(n) for n in nodes]

    referred_count = {}
    for n in nodes:
        if n.get("referred"):
            referred_count[n["referred"]] = referred_count.get(n["referred"], 0) + 1
    reused = {k: v for k, v in referred_count.items() if v > 1}
    max_depth = max((n["depth"] for n in nodes), default=0)

    data = {
        "file": os.path.abspath(args.step),
        "assembly": {
            "instance_count": sum(1 for n in nodes if not n["assembly"]),
            "unique_shape_count": len(referred_count),
            "max_depth": max_depth,
            "reused": reused,
            "tree": [{"path": n["path"], "depth": n["depth"], "assembly": n["assembly"],
                      "reference": n["reference"]} for n in nodes],
        },
        "parts": public_all,
        "checks": {},
    }

    if args.fit:
        a = select_parts(nodes, args.fit[0])
        b = select_parts(nodes, args.fit[1])
        fit_clear = args.fit_clearance if args.fit_clearance is not None else args.clearance
        data["checks"]["fit"] = {"child_matches": [n["path"] for n in a],
                                 "parent_matches": [n["path"] for n in b],
                                 "result": check_fit(a, b, fit_clear)}
    if args.align_holes:
        a = select_parts(nodes, args.align_holes[0])
        b = select_parts(nodes, args.align_holes[1])
        data["checks"]["align_holes"] = check_align(a, b, args.tol)
    if args.limit_height:
        a = select_parts(nodes, args.limit_height)
        data["checks"]["limit_height"] = check_limit(a, args.zmax if args.zmax is not None else 0.0)
    if args.avoid:
        a = select_parts(nodes, args.avoid[0])
        b = select_parts(nodes, args.avoid[1])
        avoid_clear = args.avoid_clearance if args.avoid_clearance is not None else args.clearance
        data["checks"]["avoid"] = check_avoid(a, b, avoid_clear)
    if args.interference:
        data["checks"]["interference"] = check_interference(nodes, args.interference_vol)
    if args.min_gap:
        data["checks"]["min_gap"] = check_min_gap(nodes)
    if args.wall_thickness:
        targets = select_parts(nodes, args.wall_part) if args.wall_part else \
            [n for n in nodes if not n.get("assembly") and n.get("shape") is not None]
        data["checks"]["wall_thickness"] = {
            n["path"]: estimate_wall(n["shape"], args.wall_samples) for n in targets
        }

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("JSON: %s" % args.json_out)
    md = render_md(data)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(md)
        print("报告: %s" % args.report)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())