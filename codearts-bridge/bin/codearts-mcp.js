#!/usr/bin/env node
import { start } from "../src/server.js";

start().catch((err) => {
  process.stderr.write(`codearts-bridge fatal: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});