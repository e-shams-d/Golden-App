import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../../..");
const roots = [join(repositoryRoot, "apps"), join(repositoryRoot, "packages")];
const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".ts", ".tsx"]);
const unsafePublicName = /NEXT_PUBLIC_[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PRIVATE|CREDENTIAL|API_KEY)/g;
const findings = [];

function scan(path) {
  const stat = statSync(path);

  if (stat.isDirectory()) {
    if (["node_modules", ".next", "coverage", "dist"].includes(path.split(/[\\/]/).at(-1))) {
      return;
    }

    for (const entry of readdirSync(path)) scan(join(path, entry));
    return;
  }

  if (!sourceExtensions.has(extname(path))) return;

  const matches = readFileSync(path, "utf8").match(unsafePublicName);
  if (matches) findings.push(`${path}: ${matches.join(", ")}`);
}

for (const root of roots) scan(root);

if (findings.length > 0) {
  throw new Error(`Secret-like NEXT_PUBLIC names are forbidden:\n${findings.join("\n")}`);
}

process.stdout.write("Public environment variable scan passed.\n");
