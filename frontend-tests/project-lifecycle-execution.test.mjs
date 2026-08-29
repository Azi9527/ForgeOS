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

test("project lifecycle reloads by stable project id and rejects stale responses", async () => {
  const source = await readFile("src/lib/components/ProjectLifecycleWorkspace.svelte", "utf8");

  assert.doesNotMatch(source, /import\s*\{\s*onMount\s*\}/u);
  assert.match(source, /\$effect\(\(\) => \{[\s\S]*const targetProjectId = project\.projectId;[\s\S]*const generation = \+\+loadGeneration;/u);
  assert.match(source, /api\.getProjectLifecycle\(targetProjectId\)/u);
  assert.match(source, /generation !== loadGeneration \|\| project\.projectId !== targetProjectId/u);
  assert.match(source, /void loadLifecycle\(targetProjectId, generation\)/u);
});

test("a release request requires a currently registered target environment", async () => {
  const source = await readFile("src/lib/components/ProjectLifecycleWorkspace.svelte", "utf8");
  const createStart = source.indexOf("function createRelease(");
  const approveStart = source.indexOf("function approveRelease(", createStart);
  assert.notEqual(createStart, -1);
  assert.notEqual(approveStart, -1);

  const createRelease = source.slice(createStart, approveStart);
  assert.match(createRelease, /environments\.find\([\s\S]*environment\.id === releaseTargetEnvironmentId/u);
  assert.match(createRelease, /if \(!targetEnvironment\) throw new Error/u);
  assert.match(createRelease, /targetEnvironmentId: targetEnvironment\.id/u);
  assert.doesNotMatch(createRelease, /releaseTargetEnvironmentId \|\| null/u);
  assert.match(source, /disabled=\{busy \|\| readOnly \|\| !selectedReleaseEnvironment\}/u);
});

test("project mutations keep their original project context when the workspace switches", async () => {
  const source = await readFile("src/lib/components/ProjectLifecycleWorkspace.svelte", "utf8");
  const contextStart = source.indexOf("type MutationContext");
  const effectStart = source.indexOf("$effect(() =>", contextStart);
  assert.notEqual(contextStart, -1);
  assert.notEqual(effectStart, -1);
  const mutationSource = source.slice(contextStart, effectStart);
  const effectSource = source.slice(effectStart);

  assert.match(mutationSource, /projectId: string;[\s\S]*lifecycleSnapshot: ProjectLifecyclePayload;[\s\S]*loadGeneration: number;[\s\S]*mutationToken: number;/u);
  assert.match(mutationSource, /const targetProjectId = project\.projectId;[\s\S]*const lifecycleSnapshot = lifecycle;/u);
  assert.match(mutationSource, /projectId: targetProjectId,[\s\S]*lifecycleSnapshot,[\s\S]*loadGeneration,[\s\S]*mutationToken: \+\+mutationSequence/u);
  assert.match(mutationSource, /project\.projectId === context\.projectId[\s\S]*loadGeneration === context\.loadGeneration[\s\S]*activeMutationToken === context\.mutationToken/u);
  assert.match(mutationSource, /if \(!mutationIsCurrent\(context\)\) return false;[\s\S]*applyLifecycle\(nextLifecycle\)/u);
  assert.match(mutationSource, /activeMutationToken === context\.mutationToken && project\.projectId === context\.projectId/u);
  assert.match(effectSource, /const generation = \+\+loadGeneration;[\s\S]*activeMutationToken = null;[\s\S]*busy = false;/u);
  assert.doesNotMatch(mutationSource, /projectId\(\)/u);
  assert.doesNotMatch(mutationSource, /void mutate\(async \(\) =>/u);
});

test("artifact upload and lifecycle writes use only the captured project snapshot", async () => {
  const source = await readFile("src/lib/components/ProjectLifecycleWorkspace.svelte", "utf8");
  const artifactStart = source.indexOf("function createArtifact(");
  const verifyStart = source.indexOf("function verifyArtifact(", artifactStart);
  assert.notEqual(artifactStart, -1);
  assert.notEqual(verifyStart, -1);
  const createArtifact = source.slice(artifactStart, verifyStart);

  assert.match(createArtifact, /const releaseSnapshot = context\.lifecycleSnapshot\.release/u);
  assert.match(createArtifact, /api\.uploadProjectArtifact\([\s\S]*context\.projectId,[\s\S]*version,[\s\S]*sourceCommit,[\s\S]*selectedFile/u);
  assert.match(createArtifact, /storeRelease\([\s\S]*context,[\s\S]*\[artifact, \.\.\.releaseSnapshot\.artifacts\],[\s\S]*releaseSnapshot\.releases/u);
  assert.match(createArtifact, /if \(mutationIsCurrent\(context\)\)/u);
  assert.match(source, /api\.saveProjectRelease\([\s\S]*context\.projectId,[\s\S]*context\.lifecycleSnapshot\.revision/u);
  assert.match(source, /api\.saveProjectOperations\([\s\S]*context\.projectId,[\s\S]*context\.lifecycleSnapshot\.revision/u);
  assert.match(source, /disabled=\{busy \|\| readOnly \|\| persistenceMode !== "gateway"\}[\s\S]*验证/u);
  assert.match(source, /disabled=\{busy \|\| readOnly \|\| persistenceMode !== "gateway"\}[\s\S]*下载/u);
});
