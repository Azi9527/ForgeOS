import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const target = String(process.argv[2] ?? "").trim();
if (!/^[a-zA-Z0-9._-]+$/u.test(target)) {
  throw new Error("Usage: node scripts/create-gateway-bundle.mjs <rust-target>");
}

const packagePayload = JSON.parse(await fs.readFile(path.join(projectRoot, "package.json"), "utf8"));
const rawVersion = String(process.env.FORGEOS_GATEWAY_VERSION ?? packagePayload.version ?? "dev").trim();
const version = /^[a-zA-Z0-9._-]+$/u.test(rawVersion)
  ? rawVersion
  : String(process.env.GITHUB_SHA ?? "manual").slice(0, 12);
const binaryName = target.includes("windows") ? "backend.exe" : "backend";
const sourceBinary = path.join(projectRoot, "dist", "backend", target, binaryName);
const sourceStatic = path.join(projectRoot, "build", "static");
const artifactsRoot = path.join(projectRoot, "artifacts");
const bundleRoot = path.join(artifactsRoot, `forgeos-gateway-${version}-${target}`);
if (path.dirname(bundleRoot) !== artifactsRoot) {
  throw new Error("Gateway bundle output escaped the artifacts directory.");
}

const hash = createHash("sha256");
for await (const chunk of createReadStream(sourceBinary)) {
  hash.update(chunk);
}
const digest = hash.digest("hex");

await fs.rm(bundleRoot, { recursive: true, force: true });
await fs.mkdir(path.join(bundleRoot, "dist", "backend", target), { recursive: true });
await fs.copyFile(sourceBinary, path.join(bundleRoot, "dist", "backend", target, binaryName));
await fs.cp(sourceStatic, path.join(bundleRoot, "build", "static"), { recursive: true });
await fs.writeFile(
  path.join(bundleRoot, "forgeos-gateway.json"),
  `${JSON.stringify({
    schemaVersion: 1,
    product: "ForgeOS",
    version,
    target,
    binary: `dist/backend/${target}/${binaryName}`,
    staticDir: "build/static",
    sha256: digest,
    builtAt: new Date().toISOString(),
    commit: String(process.env.GITHUB_SHA ?? "").trim() || null
  }, null, 2)}\n`
);

console.log(bundleRoot);
