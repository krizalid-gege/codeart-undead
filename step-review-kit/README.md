# step-review-kit

STEP（3D）结构审阅模块，作为 `codearts-bridge` 的**可选上游 MCP Server**，也可单独作为 CLI 使用。

## 能力

| 类别 | 内容 |
|---|---|
| 装配核对 | 实例数、唯一外形数、层级、坐标原点（bbox 中心）、同名件复用（referred shape） |
| 几何量 | 外形尺寸、包围盒、体积、孔位（半径/轴线）、壁厚（曲面法射线采样） |
| 干涉/间隙 | 包围盒预筛 + BRep 精确布尔干涉、BRepExtrema 最小距离 |
| 配合检查 | `--fit`、`--align-holes`、`--limit-height`、`--avoid` |

## 依赖

- Python 3.10+
- `pip install cadquery mcp`
- `libGL.so.1`（cadquery/OCP 运行库）

### libGL 处理（三选一）

1. **系统已有**：多数桌面/服务器直接可用，跳过。
2. **有 root**：`dnf install mesa-libGL` / `apt install libgl1`。
3. **无 root / 无 libGL**：运行
   ```bash
   ./bootstrap_libgl.sh
   export STEP_LD_LIBRARY_PATH=<输出的路径>
   ```
   脚本会安装 `libglvnd` 并生成一个只满足加载的 `libGL` stub（几何计算不需要真实 GL 渲染）。

> stub 仅用于几何计算，不支持 3D 渲染/截图。

## 文件

| 文件 | 作用 |
|---|---|
| `mcp_server.py` | MCP Server（stdio） |
| `step_review.py` | 解析 + 几何/检查引擎 + 报告 |
| `run_step_mcp.sh` | MCP 启动封装（设置 `STEP_LD_LIBRARY_PATH`） |
| `run_step_review.sh` | CLI 封装 |
| `bootstrap_libgl.sh` | 可选：无 root 时安装 libGL stub |

## CLI

```bash
./run_step_review.sh model.step --list
./run_step_review.sh model.step --report report.md --json out.json

./run_step_review.sh model.step --fit PCB housing --fit-clearance 2
./run_step_review.sh model.step --align-holes PCB housing --tol 0.5
./run_step_review.sh model.step --limit-height CAP --zmax 25
./run_step_review.sh model.step --avoid BUSBAR housing --avoid-clearance 3

./run_step_review.sh model.step --interference
./run_step_review.sh model.step --min-gap
./run_step_review.sh model.step --wall-thickness --wall-part PCB
```

## MCP 工具

### `list_parts(step_path)`

返回装配树与零件几何（尺寸、体积、孔数、原点、复用）。

### `review_step(step_path, ...)`

| 参数 | 说明 |
|---|---|
| `fit_child` / `fit_parent` / `fit_clearance` | 包围盒配合检查 |
| `align_a` / `align_b` / `align_tol` | 孔轴线对齐 |
| `limit_part` / `limit_zmax` | 限高 |
| `avoid_a` / `avoid_b` / `avoid_clearance` | 避让最小间隙 |
| `interference` / `interference_vol` | 两两干涉 |
| `min_gap` | 最小间隙 Top-N |
| `wall_thickness` / `wall_part` / `wall_samples` | 壁厚（曲面法采样） |
| `include_report` | 同时返回 Markdown 报告 |

返回 JSON：`file` / `assembly` / `parts` / `checks`（可选 `report_markdown`）。

## 接入 codearts-bridge

与 PCB 模块同时聚合时，用 `MCP_UPSTREAMS`（不要同时用简化的 `PCB_REVIEW_MCP`）：

```
MCP_UPSTREAMS=[
 {"name":"pcb","command":"/abs/python3","args":["/abs/codeart-undead/pcb-review-kit/mcp_server.py"],
  "env":{"PCB_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":60000},
 {"name":"step","command":"/abs/codeart-undead/step-review-kit/run_step_mcp.sh","args":[],
  "env":{"STEP_LD_LIBRARY_PATH":"/abs/gltools/stublib:/abs/gltools/glenv/lib","STEP_REVIEW_ROOT":"/abs/project"},
  "callTimeoutMs":120000}
]
```

聚合后工具集：`codearts_*` + `review_pcb/parse_board/list_rules/get_rule` + `list_parts/review_step`。

## 边界

- 配合检查为**包围盒/孔轴线级**；精确内腔配合需指定内腔零件或面。
- 壁厚为**面中心射线采样**（min/median/max），不等同全零件最小壁厚。
- 同名件复用依赖 STEP 的 referred shape；部分导出器会把实例烘焙成独立形状。
- 不做强度/热/公差链仿真，不替代 CAD/CAE。