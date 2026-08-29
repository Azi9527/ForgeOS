import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("project operations request gateway execution instead of driving a browser terminal", async () => {
  const source = await readFile("src/lib/components/ProjectLifecycleWorkspace.svelte", "utf8");

  assert.match(source, /api\.runProjectDeployment\(/u);
  assert.match(source, /api\.checkProjectEnvironment\(/u);
  assert.doesNotMatch(source, /executeProjectCommand|commandPayload|createTerminal|sendTerminalInput|readTerminal|closeTerminal/u);
  assert.doesNotMatch(source, /localStorage|restoreLocal|persistLocal/u);
  assert.doesNotMatch(source, /const running:\s*ProjectDeployment|exitCode:\s*result\.exitCode/u);
});

test("project operation APIs send only stable ids and expected revision", async () => {
  const source = await readFile("src/lib/api.ts", "utf8");
  const deploymentStart = source.indexOf("runProjectDeployment(");
  const healthStart = source.indexOf("checkProjectEnvironment(");
  const operationsEnd = source.indexOf("getGitWorktrees(", healthStart);
  assert.notEqual(deploymentStart, -1);
  assert.notEqual(healthStart, -1);
  assert.notEqual(operationsEnd, -1);

  const methods = source.slice(deploymentStart, operationsEnd);
  assert.match(methods, /"projectLifecycle\/deployment\/run"/u);
  assert.match(methods, /\{ projectId, releaseId, environmentId, expectedRevision \}/u);
  assert.match(methods, /"projectLifecycle\/environment\/check"/u);
  assert.match(methods, /\{ projectId, environmentId, expectedRevision \}/u);
  assert.doesNotMatch(methods, /command|logs|exitCode|status/u);
});
