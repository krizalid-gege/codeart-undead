# Changelog

本项目的所有重要变更记录在此。格式参考 Keep a Changelog，版本遵循 SemVer。

## [1.2.2] - 2026-11-20

### Added

- `pcb-review-kit/`：PCB 静态规则审核模块（MCP Server + CLI + 规则库 + 输入模板），作为可选上游。
- `pcb-review-kit/README.md`：模块说明与接入方式。

### Changed

- 根 `README.md`、`docs/ANTIGRAVITY.md`、`docs/OPERATIONS.md` 中的 PCB 上游路径改为仓库内 `pcb-review-kit/mcp_server.py`。
- 版本升至 `1.2.2`。

### Fixed

- 修复文档引用了仓库中不存在的 `pcb-review-kit` 目录的问题。

## [1.2.1] - 2026-11-20

### Added

- `docs/ANTIGRAVITY.md`：antigravity 环境接入与本项目工具调用手册。
- `docs/OPERATIONS.md`：安装、授权、配置、运行、排障、安全操作手册。
- `CHANGELOG.md`：版本与变更记录。

### Changed

- 根 `README.md` 增加文档索引与当前版本说明。
- `codearts-bridge/README.md` 增加 antigravity / 操作手册入口。

### Fixed

- 测试脚本在成功路径显式 `process.exit(0)`，避免 `Promise.race` 的超时定时器让测试进程多挂 30 秒。

## [1.2.0] - 2026-11-20

### Added

- `src/gateway.js`：零依赖 MCP 客户端与聚合层，可作为客户端连接任意上游 MCP Server。
- `test/aggregate.js`、`test/mock-upstream.js`：聚合与转发的协议层测试。
- 支持 `MCP_UPSTREAMS`（JSON 数组，可多个上游）与简化变量 `PCB_REVIEW_MCP` / `PCB_REVIEW_PYTHON` / `PCB_REVIEW_ROOT`。

### Changed

- `tools/list` 合并本地工具与上游工具，重名时自动加 `<name>_` 前缀。
- `tools/call` 支持本地优先、上游转发。
- `codearts_health` 返回 `upstreams`（`ready` / `error` / `toolCount`）。
- 版本升至 `1.2.0`。

## [1.1.0] - 2026-11-20

### Fixed

- 逐行解析 `codearts run --format json` 的 JSONL 输出，而不是对整段 stdout 做 `JSON.parse`。
- 子进程 stdin 设为 `ignore`，避免 CLI 等待 EOF 导致调用长时间挂起。

### Changed

- 输出结构化 `ok` / `exitCode` / `sessionId` / `text` / `events`；事件过大时截断为尾部。
- 失败时附带 `error` 与 `stderr` 尾部。

## [1.0.0] - 2026-11-20

### Added

- 初始 `codearts-bridge`：把 `codearts` CLI 封装为 stdio MCP Server。
- 工具：`codearts_run`、`codearts_session_list`、`codearts_health`。
- 零依赖（Node >= 18）、并发上限、超时、审批模式、attach 模式。