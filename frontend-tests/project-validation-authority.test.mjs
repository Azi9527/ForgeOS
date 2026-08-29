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
  assert.doesNotMatch(api, /"projectLifecycle\/validation\/record"/u);
  assert.match(dispatch, /"projectLifecycle\/validation\/run"/u);
  assert.match(dispatch, /"projectLifecycle\/validation\/cancel"/u);
  assert.doesNotMatch(dispatch, /"projectLifecycle\/validation\/record"/u);
});
