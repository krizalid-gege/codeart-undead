# codeart-undead

把华为云码道（CodeArts Agent）封装成**任意 agent 都能直接调用的 MCP Server**。

你的 agent 通过标准 MCP 协议（stdio + JSON-RPC）调用码道，无需了解码道 CLI 细节。

## 目录

```
codearts-bridge/     MCP Server（零依赖，Node >= 18）
  bin/codearts-mcp.js      入口
  src/server.js            协议实现与工具定义
  test/                    协议层冒烟测试（mock CLI）
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

## 快速开始

```bash
cd codearts-bridge
codearts --version     # 确认 CLI 已安装
npm test               # 协议层自检，期望 smoke: all checks passed
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

三个工具：`codearts_run`、`codearts_session_list`、`codearts_health`。

完整用法、长期调用方案、审批模式、错误处理见 [codearts-bridge/README.md](codearts-bridge/README.md)。

## 边界

码道目前只开放 CLI 作为集成面，没有公开的对话 REST API，也不能作为 MCP Server 被直接挂载。本项目把 CLI 包成 MCP tool，是当前唯一稳定的官方路径。