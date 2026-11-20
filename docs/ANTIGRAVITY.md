# antigravity 接入手册

本文说明如何在 **antigravity** 环境中接入并调用本项目（`codearts-bridge` MCP 网关），包括码道工具与可选的 PCB 审核上游。

> 适用版本：`codearts-bridge >= 1.2.1`。antigravity 的 MCP 配置入口与字段名可能随版本变化，**以你所用版本的官方 MCP 文档为准**；本文给的是通用 `mcpServers` 结构。

---

## 1. 前置条件

| 项 | 说明 |
|---|---|
| Node | `>= 18`（bridge 零依赖） |
| 码道 CLI | `codearts` 已安装，且 antigravity 能访问到该可执行文件 |
| 授权 | 已完成网页登录或 AK/SK 授权，且有可用套餐/积分 |
| 网络 | 主机可访问华为云 |
| 传输 | antigravity 必须支持 **stdio** MCP（本项目只提供 stdio，不内置 HTTP/SSE） |
| 可选：PCB 上游 | `python3` 且已 `pip install mcp`，上游脚本为 `pcb-review-kit/mcp_server.py` |

> 如果 antigravity 只支持远程/HTTP MCP，需额外加一个 stdio→HTTP 的代理（如 `mcp-proxy`），本项目不内置该代理。

---

## 2. 最小接入（只接码道工具）

在 antigravity 的 MCP 配置中加入：

```json
{
  "mcpServers": {
    "codearts": {
      "command": "/absolute/path/to/node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/project",
        "CODEARTS_BIN": "/absolute/path/to/codearts"
      }
    }
  }
}
```

要点：

- **`command` / `args` / `CODEARTS_BIN` 全部用绝对路径**。GUI 启动的 antigravity 往往拿不到你 shell 里的 `PATH`。
- `CODEARTS_WORKDIR` 指向被授权的项目目录，不要给 `/` 或 `$HOME`。
- 不需要 `npm install`，不需要公网入站端口。

---

## 3. 聚合接入（码道 + PCB 审核，一个入口）

```json
{
  "mcpServers": {
    "codearts": {
      "command": "/absolute/path/to/node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/project",
        "CODEARTS_BIN": "/absolute/path/to/codearts",
        "PCB_REVIEW_MCP": "/absolute/path/to/pcb-review-kit/mcp_server.py",
        "PCB_REVIEW_PYTHON": "/absolute/path/to/python3",
        "PCB_REVIEW_ROOT": "/absolute/path/to/project"
      }
    }
  }
}
```

或用通用方式（可接多个上游）：

```
MCP_UPSTREAMS=[{"name":"pcb","command":"/abs/python3","args":["/abs/codeart-undead/pcb-review-kit/mcp_server.py"],"env":{"PCB_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":60000}]
```

聚合后对外工具集（共 7 个）：

- 码道：`codearts_run`、`codearts_session_list`、`codearts_health`
- PCB：`review_pcb`、`parse_board`、`list_rules`、`get_rule`

> 上游工具名与本地冲突时，网关自动加 `<name>_` 前缀。

### 3.2 同时聚合 PCB + STEP（可选）

用 `MCP_UPSTREAMS` 一次接入多个上游（此时不要再用 `PCB_REVIEW_MCP`，它只在没有 `MCP_UPSTREAMS` 时生效）：

```
MCP_UPSTREAMS=[
 {"name":"pcb","command":"/abs/python3","args":["/abs/codeart-undead/pcb-review-kit/mcp_server.py"],"env":{"PCB_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":60000},
 {"name":"step","command":"/abs/codeart-undead/step-review-kit/run_step_mcp.sh","args":[],"env":{"STEP_LD_LIBRARY_PATH":"/abs/gltools/stublib:/abs/gltools/glenv/lib","STEP_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":120000}
]
```

STEP 上游额外提供：`list_parts`、`review_step`。详见 `step-review-kit/README.md`。

---

## 4. 首次验证顺序（建议照做）

1. **进程能起来**：
   ```bash
   node /abs/codearts-bridge/bin/codearts-mcp.js
   ```
   能启动并等待 stdin 即正常（Ctrl+C 退出）。

2. **协议自检**（在仓库内）：
   ```bash
   cd codearts-bridge && npm test
   ```
   期望 `smoke: all checks passed` 与 `aggregate: all checks passed`。

3. **在 antigravity 里先调 `codearts_health`**：
   - 看 `version` 是否有值、`upstreams[].ready` 是否为 `true`。
   - 若上游失败，`upstreams[].error` 会给出原因。

4. **再调 `codearts_run`**：
   ```json
   { "prompt": "ping", "approval": "auto", "format": "json" }
   ```
   返回 `ok: true` 且带 `sessionId` 即打通。

5. **若接了 PCB 上游**：
   ```json
   { "name": "review_pcb", "arguments": { "pcb_path": "board.pcbdoc", "sch_path": "board.schdoc", "meta_path": "design_meta.json" } }
   ```
   返回 `summary` 与 `findings`。

---

## 5. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| antigravity 看不到 `codearts` server | 配置没生效 / 未信任本地 server | 重启 antigravity，按提示信任该 MCP server |
| `codearts CLI not found` | GUI 没有 PATH | 设 `CODEARTS_BIN` 为绝对路径 |
| `codearts_run` 一直不返回 | 审批模式为 `manual`/`none`，卡在确认 | 改 `approval: "auto"` |
| 返回权限/信任错误 | 文件夹信任或执行权限未放开 | 见 `docs/OPERATIONS.md` 第 4 节三层权限 |
| `upstreams[].ready=false` | 上游 Python 缺 `mcp`、路径错、`PCB_REVIEW_ROOT` 未覆盖工程 | 看 `error`，用绝对路径，确认 `python3 -c "import mcp"` |
| PCB 工具不出现 | 上游启动失败 | 先修上游，再在 antigravity 里重连 server |
| 传输报错 | antigravity 只支持远程 MCP | 加 stdio→HTTP 代理，或改用支持 stdio 的客户端 |

---

## 6. 安全

- 不要把 AK/SK、GitHub token、serve 密码写进 MCP 配置文件或仓库；用环境变量/密钥管理注入。
- `MCP_UPSTREAMS` 等价于"允许 bridge 启动这些子进程"，只配置可信 server。
- `CODEARTS_WORKDIR` 只指向授权目录；生产默认 `approval: "auto"`，禁止 `full`。
- 详细安全清单见 `docs/OPERATIONS.md` 第 9 节。