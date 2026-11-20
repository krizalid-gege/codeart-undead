# codeart-undead

> 当前版本：1.2.1（版本记录见 [CHANGELOG.md](CHANGELOG.md)）

把华为云码道（CodeArts Agent）封装成**任意 agent 都能直接调用的 MCP 网关**。

你的 agent 通过标准 MCP 协议（stdio + JSON-RPC）调用码道；网关还可聚合任意上游 MCP Server（如 PCB 审核），对外只暴露一个入口。

## 目录

```
codearts-bridge/     MCP 网关（零依赖，Node >= 18）
  bin/codearts-mcp.js      入口
  src/server.js            协议实现与本地工具定义
  src/gateway.js           MCP 聚合层（上游 client + 工具合并/转发）
  test/                    smoke（本地）+ aggregate（聚合）测试
  deploy/                  codearts serve 的 systemd 托管示例
  README.md                使用手册（给 agent 和集成方看）
```

## 不需要什么

- 不需要预先创建华为云持久化沙箱
- 不需要公网隧道
- 不需要对外暴露 HTTP 服务

MCP 走 stdio，进程随你的 agent 启动，退出即结束。

## 需要什么

1. 安装 `codearts` CLI
2. 完成授权（网页登录，或服务器环境用 AK/SK）
3. 有可用的码道套餐/积分
4. 主机能访问华为云

聚合上游 MCP Server 时，额外需要该上游自身的运行时（例如 PCB 审核需要 `python3` + `mcp` 包），与码道 CLI 相互独立。

## 快速开始

```bash
cd codearts-bridge
codearts --version     # 确认 CLI 已安装
npm test               # 本地 + 聚合自检，smoke / aggregate 均通过
```

在 MCP 客户端里注册：

```json
{
  "mcpServers": {
    "codearts": {
      "command": "node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/project"
      }
    }
  }
}
```

默认三个工具：`codearts_run`、`codearts_session_list`、`codearts_health`。聚合上游后工具集会合并（见下）。

### 聚合上游 MCP Server（可选）

网关会作为 MCP **客户端**连上游，再把上游工具并入对外工具集，入口仍是一个。推荐用简化变量：

```json
{
  "mcpServers": {
    "codearts": {
      "command": "node",
      "args": ["/absolute/path/to/codearts-bridge/bin/codearts-mcp.js"],
      "env": {
        "CODEARTS_WORKDIR": "/absolute/path/to/project",
        "PCB_REVIEW_MCP": "/absolute/path/to/pcb-review-kit/mcp_server.py",
        "PCB_REVIEW_PYTHON": "python3",
        "PCB_REVIEW_ROOT": "/absolute/path/to/project"
      }
    }
  }
}
```

或者用通用的 `MCP_UPSTREAMS`（JSON 数组，可配多个）：

```
MCP_UPSTREAMS=[{"name":"pcb","command":"python3","args":["/abs/pcb-review-kit/mcp_server.py"],"env":{"PCB_REVIEW_ROOT":"/abs/project"}}]
```

- 上游工具名与本地冲突时，自动加 `<name>_` 前缀。
- `codearts_health` 会返回 `upstreams: [{name, ready, error, toolCount}]`，agent 应先用它自检。
- 上游启动失败不会拖垮本地 `codearts_*` 工具；对应上游工具暂时不出现在 `tools/list`。

## 边界

码道目前只开放 CLI 作为集成面，没有公开的对话 REST API，也不能作为 MCP Server 被直接挂载。本项目把 CLI 包成 MCP tool，是当前唯一稳定的官方路径。

聚合层不改变这个边界：它只是让同一个入口同时提供码道工具与上游 MCP 工具，不绕过 CLI。

## 文档

- [版本变更记录](CHANGELOG.md)
- [antigravity 接入手册](docs/ANTIGRAVITY.md)
- [操作手册](docs/OPERATIONS.md)
- [codearts-bridge 详细手册](codearts-bridge/README.md)