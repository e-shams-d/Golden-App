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

/**
 * Refuse to run if something is already serving on the port.
 *
 * Without this the harness adopts a stranger's server, and the failure that produces is
 * almost impossible to read. A previous `test:a11y` run killed part-way through — by a
 * timeout, by Ctrl-C — leaves its standalone server orphaned and still listening. The next
 * run then spawns its own server, which cannot bind and exits; `waitForServer` meanwhile
 * gets a 200 from the orphan on its first poll and returns before noticing the child died.
 * Every test then runs against a process nobody is managing.
 *
 * It cost roughly an hour to diagnose once, and the symptom pointed everywhere except
 * here: pages rendered and their headings were visible, because an orphaned server still
 * serves HTML — but `axe.analyze()` timed out on every page, on every branch, including
 * commits that had passed CI minutes earlier. It looked like a code defect, then like CPU
 * contention, and was neither.
 *
 * Checked before spawning rather than after, because after is where the race is.
 */
async function refuseIfPortIsTaken() {
  try {
    const response = await globalThis.fetch(`http://127.0.0.1:${port}/`, {
      signal: globalThis.AbortSignal.timeout(2_000),
    });
    throw new Error(
      `Something is already serving on port ${port} (it answered ${response.status}). ` +
        "This harness will not run against it: an orphaned server from an interrupted " +
        "run serves pages but its renderer is wedged, so accessibility checks time out " +
        "on every page and the failure looks like a defect in the application. " +
        `Stop it first — \`pkill -f "standalone/apps/${appName}"\` — and re-run.`,
    );
  } catch (error) {
    // A connection failure is the expected case: the port is free.
    if (error instanceof Error && error.message.startsWith("Something is already serving")) {
      throw error;
    }
  }
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

await refuseIfPortIsTaken();

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
