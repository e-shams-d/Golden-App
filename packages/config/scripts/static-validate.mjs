import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = fileURLToPath(new URL(".", import.meta.url));
const root = resolve(scriptDirectory, "../../..");
const failures = [];

function requireFile(relativePath) {
  const absolutePath = join(root, relativePath);
  if (!existsSync(absolutePath)) failures.push(`missing ${relativePath}`);
  return absolutePath;
}

function requireText(relativePath, checks) {
  const path = requireFile(relativePath);
  if (!existsSync(path)) return;
  const content = readFileSync(path, "utf8");
  for (const [label, pattern] of checks) {
    if (!pattern.test(content)) failures.push(`${relativePath}: ${label}`);
  }
}

function findPackageJson(directory, output = []) {
  for (const entry of readdirSync(directory)) {
    if ([".git", ".next", "node_modules"].includes(entry)) continue;
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) findPackageJson(path, output);
    else if (entry === "package.json") output.push(path);
  }
  return output;
}

const packageJsonPaths = [
  join(root, "package.json"),
  ...findPackageJson(join(root, "apps")),
  ...findPackageJson(join(root, "packages")),
];

for (const path of packageJsonPaths) {
  try {
    JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    failures.push(`${path}: invalid JSON (${String(error)})`);
  }
}

const rootPackage = JSON.parse(readFileSync(requireFile("package.json"), "utf8"));
if (rootPackage.engines?.node !== ">=24.0.0 <25") {
  failures.push("package.json: Node 24 LTS engine is not enforced");
}

for (const app of ["trader-pwa", "admin-web"]) {
  requireText(`apps/${app}/app/layout.tsx`, [
    ["missing Persian lang", /lang="fa"/],
    ["missing RTL direction", /dir="rtl"/],
  ]);
  requireText(`apps/${app}/next.config.ts`, [
    ["shared security headers are not used", /buildNextHeaderRules/],
    ["standalone build is not enabled", /output:\s*"standalone"/],
    ["monorepo output tracing root is not configured", /outputFileTracingRoot/],
  ]);
  requireText(`apps/${app}/app/states/[kind]/page.tsx`, [
    ["loading state missing", /loading/],
    ["error state missing", /error/],
    ["empty state missing", /empty/],
    ["forbidden state missing", /forbidden/],
    ["conflict state missing", /conflict/],
  ]);
  requireFile(`apps/${app}/tests/a11y/shell.spec.ts`);
  requireText(`apps/${app}/app/health/route.ts`, [
    ["health response is missing", /status:\s*"ok"/],
    ["health response is cacheable", /no-store/],
  ]);
  requireFile(`apps/${app}/public/robots.txt`);
}

requireText("apps/trader-pwa/public/sw.js", [
  ["API exclusion missing", /\/api\//],
  ["file exclusion missing", /\/files\//],
  ["network no-store missing", /cache:\s*"no-store"/],
  ["offline command guard missing", /request\.method !== "GET"/],
]);

requireFile("packages/api-client/src/index.ts");
requireFile("packages/auth-client/src/index.ts");
requireFile("packages/ui/src/index.ts");
requireFile("packages/localization/src/index.ts");

if (failures.length > 0) {
  throw new Error(`Static M1 validation failed:\n- ${failures.join("\n- ")}`);
}

process.stdout.write("Static M1 workspace validation passed.\n");
