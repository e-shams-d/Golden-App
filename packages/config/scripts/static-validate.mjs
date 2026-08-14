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
  // The page must **generate** its routes from the exported kind list, not restate one.
  //
  // This used to grep this file for the five state names as bare words, and slice 10C
  // broke it by replacing the hand-kept array with `STATE_KINDS` — which is the change
  // that made the page correct: three kinds had just been added, and a literal copy is how
  // a kind ships with no page to look at it on. The gate fired, and it was right to.
  //
  // What replaced it is stronger rather than looser. The old check passed if the word
  // "loading" appeared anywhere in the file — in a comment, in an unrelated identifier —
  // while the page rendered nothing at all. This one requires the page to enumerate
  // whatever `@gold/ui` declares. The names themselves are checked below, against the file
  // that declares them.
  requireText(`apps/${app}/app/states/[kind]/page.tsx`, [
    // The assignment, not the mention. Matching a bare `STATE_KINDS` passed while the
    // page reverted to a two-element literal, because the import line still carried the
    // word — which is the same weakness this check replaced, reintroduced one line later.
    // The sabotage run is what reported it.
    ["state routes are not generated from the exported kind list", /stateKinds\s*=\s*STATE_KINDS/],
    ["the page does not render StateView", /<StateView/],
    ["the page does not generate a route per kind", /generateStaticParams/],
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

// The five mandatory application states, checked **inside the exported list** rather than
// anywhere in the file.
//
// Grepping the whole file for `"conflict"` passed after the union member was renamed,
// because the word survived in three other places — the label table, the state-to-kind
// table and the list itself. A membership check against the parsed array is the only form
// of this that means what it says.
//
// Deliberately still five and not eighteen. §7 requires eighteen and slice 10C mapped all
// of them, but the wider claim is proved by
// `packages/api-client/test/application-state.test.ts`, which parses the document itself;
// restating eighteen names here would be a second list to keep in step with that one.
{
  const stateView = "packages/ui/src/state-view.tsx";
  const path = requireFile(stateView);
  if (existsSync(path)) {
    const content = readFileSync(path, "utf8");
    const declared = /export const STATE_KINDS\s*=\s*\[([\s\S]*?)\]/.exec(content);
    if (!declared) {
      failures.push(`${stateView}: STATE_KINDS is not exported as an array literal`);
    } else {
      const kinds = [...declared[1].matchAll(/"([a-z-]+)"/g)].map((match) => match[1]);
      // Guard the guard: a pattern that stopped matching would yield an empty list, and
      // "every required kind is absent" would then report five failures rather than
      // passing — but an empty list with a *shortened* required set would pass silently.
      if (kinds.length < 5) {
        failures.push(`${stateView}: only ${kinds.length} kinds parsed out of STATE_KINDS`);
      }
      for (const required of ["loading", "error", "empty", "forbidden", "conflict"]) {
        if (!kinds.includes(required)) {
          failures.push(`${stateView}: STATE_KINDS does not carry the ${required} state`);
        }
      }
    }
  }
}

requireFile("packages/api-client/src/index.ts");
requireFile("packages/auth-client/src/index.ts");
requireFile("packages/ui/src/index.ts");
requireFile("packages/localization/src/index.ts");

if (failures.length > 0) {
  throw new Error(`Static M1 validation failed:\n- ${failures.join("\n- ")}`);
}

process.stdout.write("Static M1 workspace validation passed.\n");
