import { cp, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const allowedApps = new Set(["admin-web", "trader-pwa"]);
const appName = process.argv[2];
const port = process.argv[3];

if (!allowedApps.has(appName) || !/^\d{2,5}$/u.test(port ?? "")) {
  throw new Error(
    "Usage: node start-next-standalone.mjs <admin-web|trader-pwa> <port>",
  );
}

const repositoryRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const sourceAppRoot = resolve(repositoryRoot, "apps", appName);
const standaloneAppRoot = resolve(
  sourceAppRoot,
  ".next",
  "standalone",
  "apps",
  appName,
);
const serverPath = resolve(standaloneAppRoot, "server.js");

await stat(serverPath).catch(() => {
  throw new Error(
    `Standalone build is missing for ${appName}; run the production build before accessibility tests.`,
  );
});
await cp(
  resolve(sourceAppRoot, ".next", "static"),
  resolve(standaloneAppRoot, ".next", "static"),
  { recursive: true, force: true },
);
await cp(resolve(sourceAppRoot, "public"), resolve(standaloneAppRoot, "public"), {
  recursive: true,
  force: true,
});

process.env.HOSTNAME = "127.0.0.1";
process.env.NODE_ENV = "production";
process.env.PORT = port;

await import(pathToFileURL(serverPath).href);
