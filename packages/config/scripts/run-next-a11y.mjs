import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const allowedApps = new Set(["admin-web", "trader-pwa"]);
const appName = process.argv[2];
const port = process.argv[3];
const configFile = process.argv[4];

if (
  !allowedApps.has(appName) ||
  !/^\d{2,5}$/u.test(port ?? "") ||
  !configFile
) {
  throw new Error(
    "Usage: node run-next-a11y.mjs <admin-web|trader-pwa> <port> <config>",
  );
}

const repositoryRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const appRoot = resolve(repositoryRoot, "apps", appName);
const standaloneLauncher = resolve(
  repositoryRoot,
  "packages",
  "config",
  "scripts",
  "start-next-standalone.mjs",
);
const playwrightCli = resolve(
  appRoot,
  "node_modules",
  "@playwright",
  "test",
  "cli.js",
);

function delay(milliseconds) {
  return new Promise((resolveDelay) => {
    globalThis.setTimeout(resolveDelay, milliseconds);
  });
}

async function waitForServer(server) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`The ${appName} standalone server exited before becoming ready.`);
    }
    try {
      const response = await globalThis.fetch(`http://127.0.0.1:${port}/`, {
        signal: globalThis.AbortSignal.timeout(2_000),
      });
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await delay(500);
  }
  throw new Error(`Timed out waiting for ${appName} on port ${port}.`);
}

async function terminate(child) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolveExit) => child.once("exit", resolveExit)),
    delay(5_000),
  ]);
  if (child.exitCode === null) {
    child.kill("SIGKILL");
  }
}

const server = spawn(
  process.execPath,
  [standaloneLauncher, appName, port],
  {
    cwd: appRoot,
    env: process.env,
    stdio: "inherit",
  },
);

let exitCode = 1;
try {
  await waitForServer(server);
  const runner = spawn(
    process.execPath,
    [playwrightCli, "test", `--config=${configFile}`],
    {
      cwd: appRoot,
      env: { ...process.env, PLAYWRIGHT_EXTERNAL_SERVER: "1" },
      stdio: "inherit",
    },
  );
  exitCode = await new Promise((resolveExit, rejectExit) => {
    runner.once("error", rejectExit);
    runner.once("exit", (code, signal) => {
      if (signal) {
        rejectExit(new Error(`Playwright exited after signal ${signal}.`));
        return;
      }
      resolveExit(code ?? 1);
    });
  });
} finally {
  await terminate(server);
}

process.exitCode = exitCode;
