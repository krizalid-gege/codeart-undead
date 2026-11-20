#!/usr/bin/env node
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const serverEntry = path.resolve(here, "..", "bin", "codearts-mcp.js");
const mockBin = path.resolve(here, "mock-codearts.js");

const child = spawn(process.execPath, [serverEntry], {
  env: { ...process.env, CODEARTS_BIN: mockBin, MOCK_WAIT_STDIN: "1" },
  stdio: ["pipe", "pipe", "pipe"]
});

let buffer = "";
const pending = new Map();
let nextId = 1;

child.stdout.on("data", (chunk) => {
  buffer += chunk.toString();
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index).trim();
    buffer = buffer.slice(index + 1);
    if (!line) continue;
    const message = JSON.parse(line);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  }
});

child.stderr.on("data", (chunk) => {
  process.stderr.write(`[server] ${chunk.toString()}`);
});

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
}

const timeout = (ms) => new Promise((_, reject) => setTimeout(() => reject(new Error("test timeout")), ms));

async function main() {
  const init = await request("initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "smoke", version: "0" }
  });
  assert.equal(init.result.serverInfo.name, "codearts-bridge");
  assert.equal(init.result.serverInfo.version, "1.2.0");

  const list = await request("tools/list", {});
  const names = list.result.tools.map((t) => t.name);
  assert.deepEqual(names.sort(), ["codearts_health", "codearts_run", "codearts_session_list"]);

  const startedAt = Date.now();
  const call = await request("tools/call", {
    name: "codearts_run",
    arguments: { prompt: "读 README 并总结", approval: "auto", format: "json" }
  });
  const elapsed = Date.now() - startedAt;
  assert.equal(call.result.isError, false);
  assert.ok(elapsed < 15000, `run should not block on stdin, took ${elapsed}ms`);

  const payload = JSON.parse(call.result.content[0].text);
  assert.equal(payload.ok, true);
  assert.equal(payload.sessionId, "ses_mock_1");
  assert.equal(payload.text, "收到");
  assert.equal(payload.eventCount, 3);
  assert.ok(Array.isArray(payload.events));
  assert.equal(payload.events[0].type, "session");
  assert.equal(payload.format, "jsonl");
  assert.ok(payload.command.includes("--auto_approval"));

  const fail = await request("tools/call", {
    name: "codearts_run",
    arguments: { prompt: "--emit-failure", approval: "auto" }
  });
  assert.equal(fail.result.isError, true);
  assert.match(JSON.parse(fail.result.content[0].text).stderr, /mock failure/);

  const health = await request("tools/call", { name: "codearts_health", arguments: {} });
  assert.equal(health.result.isError, false);
  const healthPayload = JSON.parse(health.result.content[0].text);
  assert.equal(healthPayload.version, "codearts 9.9.9-mock");
  assert.equal(healthPayload.stdinMode, "ignore");

  const sessions = await request("tools/call", {
    name: "codearts_session_list",
    arguments: { format: "json", max_count: 5 }
  });
  assert.equal(sessions.result.isError, false);
  const sessionsPayload = JSON.parse(sessions.result.content[0].text);
  assert.equal(sessionsPayload.output[0].sessionId, "ses_mock_1");

  console.log(`smoke: all checks passed (run took ${elapsed}ms)`);
  child.kill();
  process.exit(0);
}

Promise.race([main(), timeout(30000)]).catch((err) => {
  console.error(err);
  child.kill();
  process.exit(1);
});