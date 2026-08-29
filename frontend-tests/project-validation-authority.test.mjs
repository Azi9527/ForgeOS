import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspacePath = new URL("../src/lib/components/ProjectValidationWorkspace.svelte", import.meta.url);
const apiPath = new URL("../src/lib/api.ts", import.meta.url);
const dispatchPath = new URL("../backend/src/ws_dispatch_support.rs", import.meta.url);

test("managed project validation is executed and evidenced only by the gateway", async () => {
  const [workspace, api, dispatch] = await Promise.all([
    readFile(workspacePath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(dispatchPath, "utf8")
  ]);

  for (const forbidden of [
    "localStorage",
    "createTerminal",
    "readTerminal",
    "sendTerminalInput",
    "recordProjectValidation"
  ]) {
    assert.doesNotMatch(workspace, new RegExp(forbidden, "u"));
  }
  assert.match(workspace, /api\.runProjectValidation\(targetProjectId, expectedRevision\)/u);
  assert.match(workspace, /api\.cancelProjectValidation\(targetProjectId\)/u);
  assert.match(workspace, /gatewayRunning = \$derived\(latestRun\?\.status === "running"\)/u);
  assert.match(workspace, /未展示任何本机缓存/u);

  assert.match(api, /"projectLifecycle\/validation\/run"/u);
  assert.match(api, /"projectLifecycle\/validation\/cancel"/u);
  assert.match(dispatch, /"projectLifecycle\/validation\/run"/u);
  assert.match(dispatch, /"projectLifecycle\/validation\/cancel"/u);
  assert.match(dispatch, /"projectLifecycle\/validation\/record"[\s\S]*run_legacy_project_validation_payload/u);
  assert.doesNotMatch(workspace, /recordProjectValidation/u);
});

test("validation mutations preserve visible evidence and reload authority on revision conflicts", async () => {
  const workspace = await readFile(workspacePath, "utf8");
  const mutationHandlerStart = workspace.indexOf("async function handleMutationFailure(");
  const saveStart = workspace.indexOf("async function saveConfiguration(", mutationHandlerStart);
  const initialRestoreStart = workspace.indexOf("async function restoreLifecycle(", saveStart);
  assert.notEqual(mutationHandlerStart, -1);
  assert.notEqual(saveStart, -1);
  assert.notEqual(initialRestoreStart, -1);

  const mutationHandler = workspace.slice(mutationHandlerStart, saveStart);
  const mutationActions = workspace.slice(saveStart, initialRestoreStart);
  const initialRestore = workspace.slice(initialRestoreStart);
  assert.match(mutationHandler, /isRevisionConflict\(message\)/u);
  assert.match(mutationHandler, /const generation = \+\+loadGeneration/u);
  assert.match(mutationHandler, /api\.getProjectLifecycle\(targetProjectId\)/u);
  assert.match(mutationHandler, /applyLifecycle\(lifecycle\)/u);
  assert.match(mutationHandler, /当前画面已保留/u);
  assert.doesNotMatch(mutationHandler, /showGatewayFailure/u);
  assert.match(mutationActions, /handleMutationFailure\("验证配置未保存"/u);
  assert.match(mutationActions, /handleMutationFailure\("网关验证未完成"/u);
  assert.match(mutationActions, /handleMutationFailure\("验证停止请求失败"/u);
  assert.doesNotMatch(mutationActions, /showGatewayFailure/u);
  assert.match(initialRestore, /showGatewayFailure\(`无法从项目网关读取验证证据/u);
});
