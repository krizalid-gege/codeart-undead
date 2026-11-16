#!/usr/bin/env node
const args = process.argv.slice(2);
const joined = args.join(" ");

function out(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
}

if (args[0] === "--version") {
  process.stdout.write("codearts 9.9.9-mock\n");
  process.exit(0);
}

if (args[0] === "session" && args[1] === "list") {
  if (args.includes("json")) {
    out([{ sessionId: "ses_mock_1", title: "demo" }]);
  } else {
    process.stdout.write("ses_mock_1\tdemo\n");
  }
  process.exit(0);
}

if (args[0] === "run") {
  const rest = args.slice(args.indexOf("run") + 1);
  const promptParts = [];
  for (const arg of rest) {
    if (arg.startsWith("-")) break;
    promptParts.push(arg);
  }
  const prompt = promptParts.join(" ");
  if (joined.includes("--emit-failure")) {
    process.stderr.write("mock failure\n");
    process.exit(2);
  }
  if (args.includes("--format") && args[args.indexOf("--format") + 1] === "json") {
    out({
      ok: true,
      mock: true,
      prompt,
      sessionId: "ses_mock_1",
      args
    });
  } else {
    process.stdout.write(`mock answer for: ${prompt}\n`);
  }
  process.exit(0);
}

process.stderr.write(`mock codearts: unsupported args ${joined}\n`);
process.exit(3);