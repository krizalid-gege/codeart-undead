# pcb-review-kit

PCB 静态规则审核模块，作为 `codearts-bridge` 的**可选上游 MCP Server**。它本身也能独立作为 CLI 使用。

## 依赖

- Python 3.10+
- `pip install mcp`（MCP Server 模式需要）

## 组成

| 文件 | 作用 |
|---|---|
| `mcp_server.py` | MCP Server（stdio），暴露 4 个工具 |
| `pcb_review.py` | 解析 + 规则引擎 + 报告生成 |
| `rules.json` | 25 条审核规则（阈值/标准/整改建议） |
| `design_meta.example.json` | 输入模板（电流/电压/AC/热插拔等设计意图） |

## MCP 工具

| 工具 | 说明 |
|---|---|
| `review_pcb` | 审核 Altium ASCII 工程，返回 findings JSON（summary/exit_code） |
| `parse_board` | 提取板尺寸、层叠、各层走线宽度、元件/过孔/焊盘、网络标签 |
| `list_rules` | 返回规则清单 |
| `get_rule` | 返回单条规则 |

## 输入格式

- PCB：Altium **ASCII** `.PcbDoc` / `.SchDoc`（二进制 `.PcbDoc` 不支持，请在 Altium 中另存为 ASCII）。
- 元信息：`design_meta.json`（照 `design_meta.example.json` 填）。

> 缺少 `design_meta` 时，依赖设计意图的规则会标为 `review`（待确认），而不是误判。

## 单独 CLI

```bash
python3 pcb_review.py \
  --pcb board.pcbdoc --sch board.schdoc \
  --meta design_meta.json \
  -o report.md --json findings.json
```

退出码：`0` 通过 / `1` 有 medium / `2` 有 high·critical。

## 作为上游接入 codearts-bridge

在 MCP 客户端的 `codearts` 环境变量里：

```json
{
  "PCB_REVIEW_MCP": "/abs/codeart-undead/pcb-review-kit/mcp_server.py",
  "PCB_REVIEW_PYTHON": "/abs/python3",
  "PCB_REVIEW_ROOT": "/abs/project"
}
```

或用 `MCP_UPSTREAMS`：

```
MCP_UPSTREAMS=[{"name":"pcb","command":"/abs/python3","args":["/abs/codeart-undead/pcb-review-kit/mcp_server.py"],"env":{"PCB_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":60000}]
```

聚合后，客户端会同时看到 `codearts_*` 与 `review_pcb / parse_board / list_rules / get_rule`。

## 边界

静态规则/几何/清单级审核；不做 SI/PI/EMC/热仿真，不替代安规认证与工厂 DFM。详见仓库根 `README.md` 与 `docs/`。