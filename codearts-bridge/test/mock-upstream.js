#!/usr/bin/env node
import { createInterface } from "node:readline";

const TOOLS = [
  {
    name: "echo",
    description: "Echo the given text",
    inputSchema: {
      type: "object",
      properties: { text: { type: "string" } },
      required: ["text"]
    }
  },
  {
    name: "add",
    description: "Add two numbers",
    inputSchema: {
      type: "object",
      properties: { a: { type: "number" }, b: { type: "number" } },
      required: ["a", "b"]
    }
  }
];

function send(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;

  let message;
  try {
    message = JSON.parse(trimmed);
  } catch {
    return;
  }

  const { id, method, params } = message;

  if (method === "initialize") {
    return send({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2025-06-18",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "mock-upstream", version: "1.0.0" }
      }
    });
  }
  if (method === "notifications/initialized") return undefined;
  if (method === "tools/list") return send({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
  if (method === "tools/call") {
    const name = params && params.name;
    const args = (params && params.arguments) || {};
    if (name === "echo") {
      return send({
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: String(args.text ?? "") }], isError: false }
      });
    }
    if (name === "add") {
      return send({
        jsonrpc: "2.0",
        id,
        result: { content: [{ type: "text", text: String(Number(args.a) + Number(args.b)) }], isError: false }
      });
    }
    return send({
      jsonrpc: "2.0",
      id,
      result: {
        content: [{ type: "text", text: JSON.stringify({ ok: false, error: `unknown tool: ${name}` }) }],
        isError: true
      }
    });
  }
  if (id !== undefined && id !== null) {
    return send({ jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } });
  }
  return undefined;
});