import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const DEFAULT_PROTOCOL = "2025-06-18";
const DEFAULT_INIT_TIMEOUT = 15000;
const DEFAULT_CALL_TIMEOUT = 120000;
const RETRY_COOLDOWN_MS = 5000;

function log(message) {
  process.stderr.write(`codearts-bridge: ${message}\n`);
}

export function loadUpstreamConfigs() {
  const raw = process.env.MCP_UPSTREAMS;
  let list = [];
  if (raw && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) list = parsed;
      else if (parsed && typeof parsed === "object") list = [parsed];
    } catch (err) {
      log(`invalid MCP_UPSTREAMS JSON ignored: ${err.message}`);
    }
  }
  if (!list.length && process.env.PCB_REVIEW_MCP) {
    list = [
      {
        name: "pcb",
        command: process.env.PCB_REVIEW_PYTHON || "python3",
        args: [process.env.PCB_REVIEW_MCP],
        env: { PCB_REVIEW_ROOT: process.env.PCB_REVIEW_ROOT || process.cwd() }
      }
    ];
  }
  return list
    .filter((cfg) => cfg && typeof cfg === "object" && typeof cfg.command === "string" && cfg.command)
    .map((cfg, index) => ({
      name: String(cfg.name || `upstream${index + 1}`),
      command: cfg.command,
      args: Array.isArray(cfg.args) ? cfg.args.map(String) : [],
      env: cfg.env && typeof cfg.env === "object" ? cfg.env : {},
      cwd: typeof cfg.cwd === "string" && cfg.cwd ? cfg.cwd : undefined,
      prefix: typeof cfg.prefix === "string" ? cfg.prefix : "",
      initTimeoutMs: Number(cfg.initTimeoutMs || DEFAULT_INIT_TIMEOUT),
      callTimeoutMs: Number(cfg.callTimeoutMs || DEFAULT_CALL_TIMEOUT)
    }));
}

class UpstreamClient {
  constructor(config) {
    this.config = config;
    this.name = config.name;
    this.child = null;
    this.pending = new Map();
    this.nextId = 1;
    this.tools = [];
    this.ready = false;
    this.error = null;
    this.starting = null;
    this.lastFailAt = 0;
  }

  async ensureStarted() {
    if (this.ready) return true;
    if (this.error && Date.now() - this.lastFailAt < RETRY_COOLDOWN_MS) return false;
    if (this.starting) return this.starting;
    this.starting = this.start().finally(() => {
      this.starting = null;
    });
    return this.starting;
  }

  async start() {
    this.error = null;
    try {
      const child = spawn(this.config.command, this.config.args, {
        cwd: this.config.cwd,
        env: { ...process.env, ...this.config.env },
        stdio: ["pipe", "pipe", "pipe"],
        shell: process.platform === "win32",
        windowsHide: true
      });
      this.child = child;
      const rl = createInterface({ input: child.stdout, crlfDelay: Infinity });
      rl.on("line", (line) => this.onLine(line));
      child.stderr.on("data", (chunk) => {
        process.stderr.write(`[upstream:${this.name}] ${chunk.toString()}`);
      });
      child.on("error", (err) => this.fail(`spawn error: ${err.message}`));
      child.on("close", (code) => {
        if (this.ready) log(`upstream ${this.name} exited (code=${code})`);
        this.fail(`upstream exited (code=${code})`);
      });

      await this.request(
        "initialize",
        {
          protocolVersion: DEFAULT_PROTOCOL,
          capabilities: {},
          clientInfo: { name: "codearts-bridge", version: "1.2.2" }
        },
        this.config.initTimeoutMs
      );
      this.notify("notifications/initialized", {});
      const listed = await this.request("tools/list", {}, this.config.initTimeoutMs);
      this.tools = listed && Array.isArray(listed.tools) ? listed.tools : [];
      this.ready = true;
      log(`upstream ${this.name} ready (${this.tools.length} tools)`);
      return true;
    } catch (err) {
      this.fail(err && err.message ? err.message : String(err));
      return false;
    }
  }

  fail(message) {
    this.ready = false;
    this.error = message;
    this.lastFailAt = Date.now();
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(new Error(`upstream ${this.name} unavailable: ${message}`));
      this.pending.delete(id);
    }
  }

  send(message) {
    if (!this.child || !this.child.stdin || this.child.stdin.destroyed) {
      throw new Error(`upstream ${this.name} not running`);
    }
    this.child.stdin.write(JSON.stringify(message) + "\n");
  }

  notify(method, params) {
    this.send({ jsonrpc: "2.0", method, params });
  }

  request(method, params, timeoutMs) {
    const id = this.nextId++;
    const limit = Number(timeoutMs || this.config.callTimeoutMs || DEFAULT_CALL_TIMEOUT);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`upstream ${this.name} timeout: ${method}`));
      }, Math.max(1, limit));
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.send({ jsonrpc: "2.0", id, method, params });
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  onLine(line) {
    const trimmed = String(line || "").trim();
    if (!trimmed) return;
    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      return;
    }
    if (message.id === undefined || message.id === null) return;
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.error) entry.reject(new Error(message.error.message || JSON.stringify(message.error)));
    else entry.resolve(message.result);
  }

  async call(originalName, args) {
    const started = await this.ensureStarted();
    if (!started) throw new Error(`upstream ${this.name} unavailable: ${this.error || "start failed"}`);
    return this.request("tools/call", { name: originalName, arguments: args || {} }, this.config.callTimeoutMs);
  }

  status() {
    return {
      name: this.name,
      command: [this.config.command, ...this.config.args].join(" "),
      ready: this.ready,
      error: this.error,
      toolCount: this.tools.length
    };
  }

  close() {
    try {
      if (this.child && this.child.stdin) this.child.stdin.end();
    } catch {
      /* ignore */
    }
    try {
      if (this.child) this.child.kill();
    } catch {
      /* ignore */
    }
  }
}

export class Gateway {
  constructor(configs) {
    this.clients = configs.map((config) => new UpstreamClient(config));
    this.routes = new Map();
  }

  async init() {
    if (!this.clients.length) return;
    await Promise.all(this.clients.map((client) => client.ensureStarted()));
  }

  async listTools(localTools) {
    if (!this.clients.length) return { tools: localTools };
    await this.init();
    const used = new Set(localTools.map((tool) => tool.name));
    const routes = new Map();
    const tools = [...localTools];
    for (const client of this.clients) {
      if (!client.ready) continue;
      for (const tool of client.tools) {
        let publicName = tool.name;
        if (used.has(publicName)) {
          const base = client.config.prefix || `${client.name}_`;
          publicName = `${base}${tool.name}`;
          while (used.has(publicName)) publicName = `${client.name}_${publicName}`;
        }
        used.add(publicName);
        routes.set(publicName, { client, originalName: tool.name });
        tools.push({ ...tool, name: publicName });
      }
    }
    this.routes = routes;
    return { tools };
  }

  async call(name, args) {
    const route = this.routes.get(name);
    if (!route) throw new Error(`unknown upstream tool: ${name}`);
    return route.client.call(route.originalName, args);
  }

  has(name) {
    return this.routes.has(name);
  }

  status() {
    return this.clients.map((client) => client.status());
  }

  close() {
    for (const client of this.clients) client.close();
  }
}