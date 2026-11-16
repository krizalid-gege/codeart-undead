#!/usr/bin/env node
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const serverEntry = path.resolve(here, "..", "bin", "codearts-mcp.js");
const mockBin = path.resolve(here, "mock-codearts.js");

const child = spawn(process.execPath, [serverEntry], {
  env: { ...process.env, CODEARTS_BIN: mockBin },
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

  const list = await request("tools/list", {});
  const names = list.result.tools.map((t) => t.name);
  assert.deepEqual(names.sort(), ["codearts_health", "codearts_run", "codearts_session_list"]);

  const call = await request("tools/call", {
    name: "codearts_run",
    arguments: { prompt: "读 README 并总结", approval: "auto", format: "json" }
  });
  assert.equal(call.result.isError, false);
  const payload = JSON.parse(call.result.content[0].text);
  assert.equal(payload.ok, true);
  assert.equal(payload.output.prompt, "读 README 并总结");
  assert.ok(payload.command.includes("--auto_approval"));

  const fail = await request("tools/call", {
    name: "codearts_run",
    arguments: { prompt: "--emit-failure", approval: "auto" }
  });
  assert.equal(fail.result.isError, true);

  const health = await request("tools/call", { name: "codearts_health", arguments: {} });
  assert.equal(health.result.isError, false);
  assert.equal(JSON.parse(health.result.content[0].text).version, "codearts 9.9.9-mock");

  const sessions = await request("tools/call", {
    name: "codearts_session_list",
    arguments: { format: "json", max_count: 5 }
  });
  assert.equal(sessions.result.isError, false);

  console.log("smoke: all checks passed");
  child.kill();
}

Promise.race([main(), timeout(30000)]).catch((err) => {
  console.error(err);
  child.kill();
  process.exit(1);
});