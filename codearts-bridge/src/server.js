import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const SERVER_NAME = "codearts-bridge";
const SERVER_VERSION = "1.0.0";
const DEFAULT_PROTOCOL = "2025-06-18";

const BIN = process.env.CODEARTS_BIN || "codearts";
const MAX_CONCURRENT = Number(process.env.CODEARTS_MAX_CONCURRENT || 2);
const DEFAULT_TIMEOUT = Number(process.env.CODEARTS_TIMEOUT_SECONDS || 900);
const ATTACH_URL = process.env.CODEARTS_ATTACH_URL || "";
const ATTACH_PASSWORD = process.env.CODEARTS_SERVER_PASSWORD || "";
const DEFAULT_CWD = process.env.CODEARTS_WORKDIR || process.cwd();

const APPROVAL_FLAGS = {
  auto: "--auto_approval",
  manual: "--manual_approval",
  full: "--full_access",
  none: null
};

let active = 0;
const waiting = [];

function withSlot(fn) {
  return new Promise((resolve, reject) => {
    const run = () => {
      active += 1;
      Promise.resolve()
        .then(fn)
        .then(resolve, reject)
        .finally(() => {
          active -= 1;
          const next = waiting.shift();
          if (next) next();
        });
    };
    if (active < MAX_CONCURRENT) run();
    else waiting.push(run);
  });
}

function execCodearts(args, options = {}) {
  const cwd = options.cwd || DEFAULT_CWD;
  const timeoutSeconds = Number(options.timeoutSeconds || DEFAULT_TIMEOUT);
  return withSlot(
    () =>
      new Promise((resolve) => {
        const startedAt = Date.now();
        let stdout = "";
        let stderr = "";
        let timedOut = false;
        let settled = false;

        const child = spawn(BIN, args, {
          cwd,
          env: process.env,
          shell: process.platform === "win32",
          windowsHide: true
        });

        const finish = (result) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve({
            ...result,
            stdout: stdout.trim(),
            stderr: stderr.trim(),
            ms: Date.now() - startedAt,
            command: [BIN, ...args].join(" ")
          });
        };

        const timer = setTimeout(() => {
          timedOut = true;
          child.kill("SIGKILL");
        }, Math.max(1, timeoutSeconds) * 1000);

        child.stdout.on("data", (d) => {
          stdout += d.toString();
        });
        child.stderr.on("data", (d) => {
          stderr += d.toString();
        });
        child.on("error", (err) => {
          finish({ ok: false, exitCode: null, timedOut: false, error: String(err.message || err) });
        });
        child.on("close", (code) => {
          finish({
            ok: code === 0 && !timedOut,
            exitCode: code,
            timedOut,
            error: timedOut ? `timeout after ${timeoutSeconds}s` : undefined
          });
        });
      })
  );
}

function parseMaybeJson(text) {
  if (!text) return { parsed: false, value: null };
  try {
    return { parsed: true, value: JSON.parse(text) };
  } catch {
    return { parsed: false, value: null };
  }
}

function render(result) {
  const body = result.stdout || "";
  const json = parseMaybeJson(body);
  const payload = json.parsed ? json.value : body;
  const envelope = {
    ok: result.ok,
    exitCode: result.exitCode,
    timedOut: result.timedOut,
    elapsedMs: result.ms,
    command: result.command,
    output: payload
  };
  if (result.error) envelope.error = result.error;
  if (!result.ok && result.stderr) envelope.stderr = result.stderr.slice(-4000);
  return JSON.stringify(envelope, null, 2);
}

function buildRunArgs(input) {
  const args = ["run"];
  if (ATTACH_URL) {
    args.push("--attach", ATTACH_URL);
    if (ATTACH_PASSWORD) args.push("--password", ATTACH_PASSWORD);
  }
  args.push(String(input.prompt));
  if (input.session_id) args.push("--sessionID", String(input.session_id));
  else if (input.continue_last) args.push("-c");
  if (input.agent) args.push("--agent", String(input.agent));
  if (input.model) args.push("--model", String(input.model));
  args.push("--format", input.format === "default" ? "default" : "json");
  const flag = APPROVAL_FLAGS[input.approval || "auto"];
  if (flag) args.push(flag);
  if (input.thinking) args.push("--thinking");
  if (input.title) args.push("--title", String(input.title));
  return args;
}

async function toolRun(input) {
  if (!input || typeof input.prompt !== "string" || !input.prompt.trim()) {
    return { isError: true, text: JSON.stringify({ ok: false, error: "prompt is required" }) };
  }
  const args = buildRunArgs(input);
  const result = await execCodearts(args, {
    cwd: input.cwd,
    timeoutSeconds: input.timeout_seconds
  });
  return { isError: !result.ok, text: render(result) };
}

async function toolSessionList(input = {}) {
  const args = ["session", "list", "--format", input.format === "json" ? "json" : "table"];
  if (input.max_count) args.push("-n", String(input.max_count));
  const result = await execCodearts(args, { cwd: input.cwd, timeoutSeconds: Math.min(120, DEFAULT_TIMEOUT) });
  return { isError: !result.ok, text: render(result) };
}

async function toolHealth(input = {}) {
  const result = await execCodearts(["--version"], { cwd: input.cwd, timeoutSeconds: 30 });
  const info = {
    ok: result.ok,
    bin: BIN,
    attachMode: Boolean(ATTACH_URL),
    defaultCwd: DEFAULT_CWD,
    maxConcurrent: MAX_CONCURRENT,
    defaultTimeoutSeconds: DEFAULT_TIMEOUT,
    version: result.stdout || null
  };
  if (!result.ok) {
    info.error = result.error || "codearts CLI not found or not executable";
    info.stderr = result.stderr.slice(-2000);
  }
  return { isError: !result.ok, text: JSON.stringify(info, null, 2) };
}

const TOOLS = [
  {
    name: "codearts_run",
    description:
      "Run a CodeArts Agent (码道) task non-interactively via `codearts run`. Returns structured JSON with ok/exitCode/output. Use session_id or continue_last to keep long-lived context.",
    inputSchema: {
      type: "object",
      properties: {
        prompt: { type: "string", description: "Instruction sent to CodeArts Agent" },
        session_id: { type: "string", description: "Resume this session id (from codearts_session_list)" },
        continue_last: { type: "boolean", description: "Continue the most recent session (-c)" },
        agent: { type: "string", description: "Agent name (e.g. plan, build, or a custom agent)" },
        model: { type: "string", description: "Model override" },
        format: { type: "string", enum: ["json", "default"], description: "Output format, default json" },
        approval: {
          type: "string",
          enum: ["auto", "manual", "full", "none"],
          description: "Approval mode. auto is recommended for unattended runs; full disables sandboxing"
        },
        thinking: { type: "boolean", description: "Include thinking blocks" },
        title: { type: "string", description: "Session title" },
        cwd: { type: "string", description: "Working directory for the task" },
        timeout_seconds: { type: "number", description: "Hard timeout, default 900" }
      },
      required: ["prompt"]
    }
  },
  {
    name: "codearts_session_list",
    description: "List CodeArts Agent sessions so an agent can resume a specific session_id.",
    inputSchema: {
      type: "object",
      properties: {
        max_count: { type: "number", description: "Limit to the most recent N sessions" },
        format: { type: "string", enum: ["json", "table"], description: "Output format, default table" },
        cwd: { type: "string", description: "Working directory" }
      }
    }
  },
  {
    name: "codearts_health",
    description: "Check that the codearts CLI is installed and report bridge configuration.",
    inputSchema: { type: "object", properties: {} }
  }
];

function send(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function reply(id, result) {
  send({ jsonrpc: "2.0", id, result });
}

function replyError(id, code, message) {
  send({ jsonrpc: "2.0", id, error: { code, message } });
}

async function handleCall(params) {
  const name = params && params.name;
  const args = (params && params.arguments) || {};
  switch (name) {
    case "codearts_run":
      return toolRun(args);
    case "codearts_session_list":
      return toolSessionList(args);
    case "codearts_health":
      return toolHealth(args);
    default:
      return { isError: true, text: JSON.stringify({ ok: false, error: `unknown tool: ${name}` }) };
  }
}

async function handleMessage(message) {
  const { id, method, params } = message;
  if (method === "initialize") {
    const protocolVersion =
      params && typeof params.protocolVersion === "string" ? params.protocolVersion : DEFAULT_PROTOCOL;
    return reply(id, {
      protocolVersion,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION }
    });
  }
  if (method === "ping") return reply(id, {});
  if (method === "tools/list") return reply(id, { tools: TOOLS });
  if (method === "tools/call") {
    try {
      const result = await handleCall(params);
      return reply(id, {
        content: [{ type: "text", text: result.text }],
        isError: Boolean(result.isError)
      });
    } catch (err) {
      return reply(id, {
        content: [{ type: "text", text: JSON.stringify({ ok: false, error: String(err && err.message ? err.message : err) }) }],
        isError: true
      });
    }
  }
  if (id === undefined || id === null) return undefined;
  return replyError(id, -32601, `method not found: ${method}`);
}

export async function start() {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      process.stderr.write(`codearts-bridge: invalid JSON line ignored\n`);
      return;
    }
    handleMessage(message).catch((err) => {
      process.stderr.write(`codearts-bridge: handler error ${err && err.stack ? err.stack : err}\n`);
      if (message && message.id !== undefined && message.id !== null) {
        replyError(message.id, -32603, String(err && err.message ? err.message : err));
      }
    });
  });
}