# 操作手册

本文是 `codearts-bridge` 的日常操作手册：安装、授权、配置、运行、聚合、排障、安全与升级。面向把它接入 agent（antigravity / DSH / 其他 MCP 客户端）的工程师。

---

## 1. 它是什么 / 不是什么

**是什么**

- 一个零依赖（Node >= 18）的 **stdio MCP 网关**。
- 对外提供码道工具：`codearts_run`、`codearts_session_list`、`codearts_health`。
- 可聚合任意上游 MCP Server（如 PCB 审核），对外仍是一个入口。

**不是什么**

- 不是码道的 REST API（码道没有公开对话 REST API）。
- 不是 HTTP/SSE 服务（只提供 stdio）。
- 不绕过码道 CLI 的授权、权限、审批。

---

## 2. 安装

```bash
git clone https://github.com/krizalid-gege/codeart-undead.git
cd codeart-undead/codearts-bridge
node --version          # 需要 >= 18
node bin/codearts-mcp.js   # 能启动并等待 stdin 即可
npm test                # smoke + aggregate 全部通过
```

安装码道 CLI 后验证：

```bash
codearts --version
```

---

## 3. 授权

两种方式：

- **网页登录**：有浏览器的开发机，首次运行 `codearts` 会拉起登录页。
- **AK/SK**：服务器、容器、CI 使用。用独立 IAM 子用户 + 最小权限，不要复用主账号。

授权后用 `codearts_health`（或 `codearts --version`）确认可用。

---

## 4. 三层权限（无人值守必配）

凭据通过 ≠ 能跑任务。三层都要配：

| 层 | 作用 | 位置 | 无人值守要求 |
|---|---|---|---|
| 1. 文件夹信任 | 是否信任工作目录 | `~/.codeartsdoer/cli-data/settings.json` | `enabled: false`（信任） |
| 2. 执行权限 | bash / 目录外读写 / 点文件 | `~/.codeartsdoer/cli-data/storage/permission/global.json` | 不能留 `ask` |
| 3. 会话审批 | `--auto_approval` 等 | bridge 的 `approval` 参数 | 用 `auto` |

第 1 层示例：

```json
{ "enabled": false }
```

第 2 层示例（按需最小化，例如只放行常用命令）：

```json
[
  { "permission": "bash", "pattern": "*", "action": "allow" },
  { "permission": "external_directory_read", "pattern": "*", "action": "allow" },
  { "permission": "external_directory_write", "pattern": "*", "action": "ask" },
  { "permission": "dotfile", "pattern": "*", "action": "ask" }
]
```

> 改完必须**重启 bridge**（即重启 MCP 客户端），CLI 只在启动时读取配置。

---

## 5. 配置

### 5.1 只接码道

```json
{
  "mcpServers": {
    "codearts": {
      "command": "/abs/node",
      "args": ["/abs/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/abs/project",
        "CODEARTS_BIN": "/abs/codearts"
      }
    }
  }
}
```

### 5.2 聚合上游（示例：PCB 审核）

```json
{
  "mcpServers": {
    "codearts": {
      "command": "/abs/node",
      "args": ["/abs/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/abs/project",
        "CODEARTS_BIN": "/abs/codearts",
        "PCB_REVIEW_MCP": "/abs/codeart-undead/pcb-review-kit/mcp_server.py",
        "PCB_REVIEW_PYTHON": "/abs/python3",
        "PCB_REVIEW_ROOT": "/abs/project"
      }
    }
  }
}
```

通用多上游：

```
MCP_UPSTREAMS=[{"name":"pcb","command":"/abs/python3","args":["/abs/codeart-undead/pcb-review-kit/mcp_server.py"],"env":{"PCB_REVIEW_ROOT":"/abs/project"},"callTimeoutMs":60000}]
```

### 5.3 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CODEARTS_BIN` | `codearts` | CLI 路径 |
| `CODEARTS_WORKDIR` | 当前目录 | 默认工作目录 |
| `CODEARTS_ATTACH_URL` | 空 | 设置后走 `--attach` |
| `CODEARTS_SERVER_PASSWORD` | 空 | serve 密码 |
| `CODEARTS_MAX_CONCURRENT` | `2` | 并发上限 |
| `CODEARTS_TIMEOUT_SECONDS` | `900` | 默认超时 |
| `CODEARTS_MAX_EVENT_BYTES` | `200000` | 事件返回上限 |
| `MCP_UPSTREAMS` | 空 | 上游 MCP Server 配置（JSON 数组） |
| `PCB_REVIEW_MCP` | 空 | 简化：单个 PCB 审核上游脚本 |
| `PCB_REVIEW_PYTHON` | `python3` | 简化：上游 Python |
| `PCB_REVIEW_ROOT` | 当前目录 | 简化：上游允许读取的根目录 |

---

## 6. 运行

### 6.1 最小验证

- 调 `codearts_health`：看 `version`、`upstreams[].ready`。
- 调 `codearts_run`：`{ "prompt": "ping", "approval": "auto", "format": "json" }`。
- 聚合时调上游工具：`list_rules`、`review_pcb` 等。

### 6.2 单次任务

```json
{ "name": "codearts_run", "arguments": { "prompt": "把 TODO 汇总成清单", "approval": "auto", "format": "json" } }
```

### 6.3 长会话

- 续上一个：`continue_last: true`
- 指定会话：`session_id: "ses_..."`（从 `codearts_run` 返回或 `codearts_session_list` 获取）
- 建议维护 `任务 → session_id` 映射，长期复用。

### 6.4 常驻模式（推荐长期）

```bash
export CODEARTS_SERVER_USERNAME="agent"
export CODEARTS_SERVER_PASSWORD="<强密码>"
codearts serve
```

bridge 设 `CODEARTS_ATTACH_URL` 与 `CODEARTS_SERVER_PASSWORD` 后走 attach，省冷启动。systemd 示例见 `deploy/codearts-serve.service`。

---

## 7. 监控与成本

```bash
codearts stats --days 1
```

用量异常时先降并发（`CODEARTS_MAX_CONCURRENT=1`），再考虑换小模型。

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `codearts CLI not found` | PATH 没有 codearts | 设 `CODEARTS_BIN` 绝对路径 |
| 调用一直不返回 | `manual`/`none` 卡审批 | 改 `approval: "auto"` |
| attach 连接失败 | serve 没起/密码错/端口变 | 查 systemd 与端口 |
| 并发大量超时 | 并发过高 | 降到 1 |
| 登录态丢失 | 浏览器 token 过期 | 改用 AK/SK |
| stdout 非 JSON | 日志误写 stdout | 日志只能写 stderr |
| 上游工具不出现 | 上游启动失败 | 看 `codearts_health.upstreams[].error` |
| `unknown tool` | 工具名冲突被加前缀 | 看 `tools/list` 的实际名称 |

诊断顺序：`codearts_health` → `codearts_run "ping"` → 正式任务。

---

## 9. 安全清单

- AK/SK、serve 密码、token 走环境变量/密钥管理，**不进 Git**。
- AK/SK 用 IAM 子用户、最小权限、定期轮换。
- 生产默认 `approval: "auto"`，禁止 `full`。
- `CODEARTS_WORKDIR` 只指向授权目录。
- `MCP_UPSTREAMS` 只配置可信 server（等价于允许启动子进程）。
- 不把 prompt 中敏感内容写入日志；审计记录 hash 与元数据即可。
- 网关 stdout 是协议通道，日志一律写 stderr。

---

## 10. 升级与回滚

```bash
cd codeart-undead
git pull
cd codearts-bridge
npm test
```

- 版本记录见 `CHANGELOG.md`。
- 回滚：`git checkout <tag-or-commit>` 后重启 MCP 客户端。
- 升级后先调 `codearts_health`，确认 `upstreams` 状态，再上正式任务。

---

## 11. 相关文档

- [antigravity 接入手册](ANTIGRAVITY.md)
- [版本变更记录](../CHANGELOG.md)
- [codearts-bridge 详细手册](../codearts-bridge/README.md)