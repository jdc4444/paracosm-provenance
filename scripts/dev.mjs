import { spawn } from "node:child_process";
import process from "node:process";

const children = [];
const built = process.argv.includes("--built");
let shuttingDown = false;

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 250).unref();
}

function start(command, args, label) {
  const child = spawn(command, args, {
    cwd: process.cwd(),
    stdio: "inherit",
    env: { ...process.env, FORCE_COLOR: "1" },
  });
  child.on("exit", (code, signal) => {
    if (!shuttingDown && code && code !== 0) {
      console.error(`[${label}] exited with code ${code}${signal ? ` (${signal})` : ""}`);
      shutdown(code);
    }
  });
  children.push(child);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
process.on("exit", () => {
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
});

start("node", ["scripts/local-api.mjs"], "archive");
start(
  "npx",
  built
    ? ["vinext", "start", "--port", "3497"]
    : ["vinext", "dev", "--port", "3497"],
  "atlas",
);
