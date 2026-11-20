#!/usr/bin/env node
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const serverEntry = path.resolve(here, "..", "bin", "codearts-mcp.js");
const mockBin = path.resolve(here, "mock-codearts.js");
const mockUpstream = path.resolve(here, "mock-upstream.js");

const upstreams = JSON.stringify([
  { name: "mock", command: process.execPath, args: [mockUpstream] }
]);

const child = spawn(process.execPath, [serverEntry], {
  env: {
    ...process.env,
    CODEARTS_BIN: mockBin,
    MOCK_WAIT_STDIN: "1",
    MCP_UPSTREAMS: upstreams
  },
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
    clientInfo: { name: "aggregate", version: "0" }
  });
  assert.equal(init.result.serverInfo.name, "codearts-bridge");
  assert.equal(init.result.serverInfo.version, "1.2.0");

  const list = await request("tools/list", {});
  const names = list.result.tools.map((tool) => tool.name).sort();
  assert.deepEqual(names, ["add", "codearts_health", "codearts_run", "codearts_session_list", "echo"]);

  const echo = await request("tools/call", {
    name: "echo",
    arguments: { text: "hello-pcb" }
  });
  assert.equal(echo.result.isError, false);
  assert.equal(echo.result.content[0].text, "hello-pcb");

  const add = await request("tools/call", {
    name: "add",
    arguments: { a: 2, b: 3 }
  });
  assert.equal(add.result.isError, false);
  assert.equal(add.result.content[0].text, "5");

  const health = await request("tools/call", { name: "codearts_health", arguments: {} });
  assert.equal(health.result.isError, false);
  const healthPayload = JSON.parse(health.result.content[0].text);
  assert.equal(healthPayload.version, "codearts 9.9.9-mock");
  assert.ok(Array.isArray(healthPayload.upstreams));
  assert.equal(healthPayload.upstreams[0].name, "mock");
  assert.equal(healthPayload.upstreams[0].ready, true);
  assert.equal(healthPayload.upstreams[0].toolCount, 2);

  const run = await request("tools/call", {
    name: "codearts_run",
    arguments: { prompt: "ping", approval: "auto", format: "json" }
  });
  assert.equal(run.result.isError, false);
  const runPayload = JSON.parse(run.result.content[0].text);
  assert.equal(runPayload.sessionId, "ses_mock_1");

  console.log("aggregate: all checks passed");
  child.kill();
  process.exit(0);
}

Promise.race([main(), timeout(30000)]).catch((err) => {
  console.error(err);
  child.kill();
  process.exit(1);
});