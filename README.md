# codeart-undead

持久化云沙箱的**保底保活**工程：外部定时任务 + 每日心跳 + 到期前重建，避免沙箱在 7 天空闲回收后彻底失联。

## 为什么需要它

华为云 DevKit 持久化沙箱（persistent pool）的生命周期：

| 状态 | 触发 | 数据 | 可进入 |
|---|---|---|---|
| 运行 | 有活动 | 保留 | 是 |
| 关机 | 空闲 60 分钟 | 保留 | 是（重连自动唤醒） |
| 回收 | 空闲满 7 天 | **随实例释放，数据丢失** | 否（再连是新空沙箱） |

沙箱关机后内部 cron 无法自救，因此保活程序**必须运行在沙箱之外**（本项目使用码道Space 定时任务）。

## 结构

```
guard/
  guard.json        # 状态：sessionId / port / publicUrl / 时间线
  guard.py          # 状态机：status 输出 HEARTBEAT 或 REBUILD；mark 记录结果
  deploy.sh         # 幂等部署：停旧进程 → 起静态服务 → 健康检查
  healthcheck.sh    # 探测 127.0.0.1:<port>
  static-server.js  # 无 python3 时的 node 兜底
site/
  index.html        # 演示页（可替换为真实站点/构建产物）
```

## 本地用法

```bash
python3 guard/guard.py status
APP_PORT=8080 ./guard/deploy.sh
./guard/healthcheck.sh
```

`guard.py status` 退出码：`0` = 只需心跳，`10` = 需要重建。

记录一次心跳或重建：

```bash
python3 guard/guard.py mark --action heartbeat --session-id <sid> --workspace-id <wid> --port 8080 --public-url <url>
python3 guard/guard.py mark --action rebuild   --session-id <sid> --workspace-id <wid> --port 8080 --public-url <url>
```

## 定时任务策略

- 频率：每天 09:00（`0 9 * * *`，Asia/Shanghai）。
- `REBUILD` 阈值：`rebuildAfterDays = 5`，回收阈值 `reclaimAfterDays = 7`，留 2 天余量。
- 心跳：connect 沙箱 → `healthcheck.sh` 失败则 `deploy.sh` → 校验隧道 URL。
- 重建：新建 persistent 沙箱 → clone 本仓 → `deploy.sh` → `expose_tunnel` → 写状态并输出新 URL。
- 失败处理：重试 1 次；仍失败则保留旧状态并在结果中明确报错，不静默失败。

## 边界

- 隧道 URL 与沙箱实例/端口绑定，重建后可能变化；`guard.json` 与任务输出是唯一事实来源。
- keepalive 只续隧道，不阻止沙箱空闲回收；真正续命靠心跳产生的活动。
- 重要产物请及时提交到本仓或同步 OBS，沙箱不是长期存储。

## 子项目

- [codearts-bridge](codearts-bridge/README.md)：把码道 CLI（`codearts run`）封装成零依赖 MCP Server，供你自己的 agent 长期调用。含 MCP 客户端配置、`serve + attach` 常驻方案、审批/超时/重试与 systemd 托管示例。