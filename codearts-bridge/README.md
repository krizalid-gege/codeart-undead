# codearts-bridge

把你自己的 agent 接到华为云码道（CodeArts Agent）上的**零依赖 MCP Server + 长期调用手册**。

本仓库解决一件事：让你的 agent 用统一的 MCP 协议调用码道，并且能稳定地跑几天、几周，而不是每次冷启动、每次超时、每次卡在审批。

---

## 1. 先理解边界（很重要）

| 事实 | 影响 |
|---|---|
| 码道**没有公开的对话 REST API** | 不要找 `/v1/chat` 之类的接口，找不到 |
| 码道**不能作为 MCP Server** 被直接挂载 | 所以需要本项目的 bridge：把 CLI 包成 MCP tool |
| 官方集成面只有 CLI：`codearts run` / `codearts serve` / `codearts attach` | bridge 的全部能力都建立在这三个命令上 |
| `codearts run` 是**进程级调用** | 冷启动较慢，长期高频调用必须用 `serve + attach` |
| **不需要预先准备沙箱** | `approval: auto/manual` 用的是 CLI 内置隔离，与你自己的机器或华为云持久化沙箱无关 |

### 常见误解

- ❌ “调用码道要先开一个华为云沙箱 / 挂域名隧道” → 不需要。MCP 走 stdio，进程随客户端启动。
- ❌ “没有公网 IP 就调不了” → 只要能访问华为云即可，不需要入站端口。
- ❌ “必须用 `full_access` 才能跑” → 恰恰相反，无人值守用 `auto`，`full_access` 只用于一次性隔离容器。
- ✅ 真正的前置条件只有三个：CLI 已安装、已授权、有套餐积分。

架构：

```
你的 Agent
   │  MCP (stdio, JSON-RPC)
   ▼
codearts-bridge (本仓库, Node, 零依赖)
   │  spawn
   ▼
codearts CLI ──(attach)──> codearts serve (常驻进程) ──> 码道云端模型
```

---

## 2. 安装

### 2.1 安装码道 CLI

```bash
# Windows (PowerShell)
irm https://cnnorth4-cloudide-marketplace.obs.cn-north-4.myhuaweicloud.com/codearts/cli_tui/install_script/install.ps1 | iex

# Linux / macOS 安装方式见官方文档
# https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0005.html
```

验证：

```bash
codearts --version
```

### 2.2 安装 bridge

```bash
cd codearts-bridge
node bin/codearts-mcp.js   # 能启动（等待 stdin）即安装成功
```

无需 `npm install`，没有第三方依赖，Node >= 18 即可。

### 2.3 授权（长期运行的关键）

两种方式：

- **网页登录**：适合有浏览器的开发机，`codearts` 首次运行会拉起登录页。
- **AK/SK 鉴权**：适合服务器、容器、CI。配置后长期有效，不依赖浏览器。

官方授权说明：https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0026.html

> 注意：AK/SK 建议用独立 IAM 子用户 + 最小权限，不要复用主账号。

---

## 3. 接到你的 agent（MCP 配置）

### 3.1 最小配置（一次性调用模式）

```json
{
  "mcpServers": {
    "codearts": {
      "command": "node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/your/project",
        "CODEARTS_MAX_CONCURRENT": "2",
        "CODEARTS_TIMEOUT_SECONDS": "900"
      }
    }
  }
}
```

### 3.2 长期模式（常驻服务 + attach）

先起服务（见 §4.2），再把 bridge 指过去：

```json
{
  "mcpServers": {
    "codearts": {
      "command": "node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/your/project",
        "CODEARTS_ATTACH_URL": "http://127.0.0.1:4096",
        "CODEARTS_SERVER_PASSWORD": "<serve 密码>"
      }
    }
  }
}
```

密码不要硬编码进仓库，用你的密钥管理或宿主环境变量注入。

---

## 4. 三种长期调用模式

### 模式 A：无状态调用（简单，但有冷启动）

每次 `codearts_run` 都新起一个 CLI 进程。适合低频、任务彼此独立。

```json
{ "prompt": "把 TODO 汇总成清单", "approval": "auto" }
```

### 模式 B：常驻服务 + attach（推荐长期）

`codearts serve` 常驻，bridge 每次通过 `--attach` 连接，省掉冷启动。

```bash
export CODEARTS_SERVER_USERNAME="agent"
export CODEARTS_SERVER_PASSWORD="<强密码>"
codearts serve
```

用 systemd 托管（示例见 `deploy/codearts-serve.service`）：

```bash
sudo cp deploy/codearts-serve.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now codearts-serve
```

健康检查：

```bash
codearts run --attach http://127.0.0.1:4096 --password "$CODEARTS_SERVER_PASSWORD" "ping" --format json --auto_approval
```

### 模式 C：会话续接（有上下文的长任务）

三种续接方式：

| 方式 | 参数 | 场景 |
|---|---|---|
| 续上一个 | `continue_last: true` | 简单的连续对话 |
| 指定会话 | `session_id: "ses_..."` | 多任务并行，各自独立上下文 |
| 派生分支 | CLI `--fork`（bridge 暂未暴露） | 想从同一上下文分叉 |

获取会话 ID：

```json
{ "name": "codearts_session_list", "arguments": { "format": "json", "max_count": 20 } }
```

建议你的 agent 维护一张 `任务 → session_id` 映射表，长期复用，不要每次新建会话。

---

## 5. 工具与参数

### `codearts_run`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `prompt` | string | 必填 | 指令 |
| `session_id` | string | - | 续接指定会话 |
| `continue_last` | bool | false | 续上一个会话 |
| `agent` | string | - | 智能体名称（build / plan / 自定义） |
| `model` | string | - | 模型覆盖 |
| `format` | enum | json | 输出格式 |
| `approval` | enum | auto | `auto` / `manual` / `full` / `none` |
| `thinking` | bool | false | 输出思考块 |
| `title` | string | - | 会话标题 |
| `cwd` | string | 环境变量 | 工作目录 |
| `timeout_seconds` | number | 900 | 硬超时，超时直接 SIGKILL |

返回结构（文本内 JSON）：

```json
{
  "ok": true,
  "exitCode": 0,
  "timedOut": false,
  "elapsedMs": 12345,
  "command": "codearts run ... --format json --auto_approval",
  "output": { "...": "codearts 的原始 JSON" }
}
```

失败时额外带 `error` 与 `stderr` 尾部 4KB。

### `codearts_session_list`

| 参数 | 说明 |
|---|---|
| `max_count` | 最近 N 个 |
| `format` | `json` 或 `table` |

### `codearts_health`

返回 CLI 是否可用、是否 attach 模式、并发与超时配置、版本号。**agent 启动时应先调它。**

---

## 6. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CODEARTS_BIN` | `codearts` | CLI 可执行文件路径 |
| `CODEARTS_WORKDIR` | 当前目录 | 默认工作目录 |
| `CODEARTS_ATTACH_URL` | 空 | 设置后所有调用走 `--attach` |
| `CODEARTS_SERVER_PASSWORD` | 空 | serve 密码 |
| `CODEARTS_MAX_CONCURRENT` | `2` | 并发上限，超出排队 |
| `CODEARTS_TIMEOUT_SECONDS` | `900` | 默认超时 |

并发上限建议保持 `1~2`：码道任务是重推理任务，并发过高只会互相拖慢并放大成本。

---

## 7. 无人值守的正确姿势

### 7.1 审批模式

| 值 | 行为 | 用在 |
|---|---|---|
| `auto` | 沙箱内执行，高风险拦截，重要操作 AI 自动审批 | **定时任务、长期无人值守（推荐）** |
| `manual` | 重要操作等人 | 有人在旁边看 |
| `full` | 不隔离、跳过检查、不询问 | 仅限一次性容器 / 完全可信的隔离机 |
| `none` | 不传审批参数 | 不建议，可能卡住 |

永远不要把 `full` 当默认值。

### 7.2 超时与重试

- 单次任务默认 900 秒；长构建类任务显式传 `timeout_seconds: 1800`。
- 重试策略：**只重试可重试错误**（网络抖动、attach 连接断开、`timedOut: false` 且 exitCode 非 0 的临时失败）。
- 超时（`timedOut: true`）不要原样重试，先查是不是任务本身太重，拆分后再跑。
- 建议退避：30s → 120s → 300s，最多 3 次。

### 7.3 进程守护

- `codearts serve` 用 systemd / launchd / supervisor 托管，`Restart=always`。
- bridge 本身由 MCP 客户端托管，不要额外常驻。
- 日志：serve 输出重定向到文件并做轮转；bridge 的日志只写 stderr（stdout 是协议通道，不能污染）。

### 7.4 每日巡检

```bash
codearts run --attach "$CODEARTS_ATTACH_URL" --password "$CODEARTS_SERVER_PASSWORD" \
  "输出当前工作目录与 git 状态" --format json --auto_approval
codearts stats --days 1
```

`codearts stats` 用来盯积分/成本；用量异常时先降并发，再考虑换小模型。

---

## 8. 安全清单

- `CODEARTS_SERVER_PASSWORD` 走环境变量或密钥管理，不进 Git。
- AK/SK 用 IAM 子用户，最小权限，定期轮换。
- 生产默认 `approval: "auto"`，禁止 `full`。
- bridge 的 `cwd` 只指向授权目录，不要给 `/` 或 `$HOME`。
- 不把 prompt 里的敏感内容打到日志；如需审计，记录 hash 与元数据即可。

---

## 9. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `codearts CLI not found` | PATH 没有 codearts | 设 `CODEARTS_BIN` 为绝对路径 |
| attach 连接失败 | serve 没起 / 密码错 / 端口变 | 查 `systemctl status codearts-serve`，确认端口 |
| 调用一直不返回 | 审批模式 `manual`/`none`，卡在确认 | 改 `auto` |
| `exitCode` 非 0 且 stderr 有权限错误 | 目录不可写 / 沙箱限制 | 换 `cwd`，检查权限 |
| 并发下大量超时 | 并发过高 | 降 `CODEARTS_MAX_CONCURRENT` 到 1 |
| 登录态丢失 | 浏览器 token 过期 | 改用 AK/SK 授权 |
| stdout 出现非 JSON | bridge 日志误写 stdout | 日志必须写 stderr |

---

## 10. 验证

```bash
npm test
```

测试会用 `test/mock-codearts.js` 模拟 CLI，完整走一遍 MCP 握手、`tools/list`、成功调用、失败调用、健康检查、会话列表，确保协议层正确。

接入真实 CLI 后，先让 agent 调一次 `codearts_health`，再调 `codearts_run` 发一句 `ping`，最后才上正式任务。

---

## 11. 官方文档

- [码道 CLI 命令（`codearts run` 全参数）](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0034.html)
- [什么是码道 CLI](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0001.html)
- [授权（网页 / AK-SK）](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0026.html)
- [安装](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0005.html)
- [码道 CLI 定时任务](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_00021.html)