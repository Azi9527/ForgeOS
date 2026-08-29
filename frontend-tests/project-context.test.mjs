import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { resolveProjectContext } from "../src/lib/project-context.ts";

function project(overrides = {}) {
  return {
    name: "APS",
    managed: true,
    pinned: false,
    sessionCount: 0,
    rootPath: "D:\\codex\\APS",
    repoPath: "D:\\codex\\APS",
    lastSessionId: null,
    lastOpenedAt: null,
    createdAt: null,
    updatedAt: null,
    ...overrides
  };
}

function session(id, overrides = {}) {
  return {
    id,
    name: id,
    preview: "",
    queueCount: 0,
    highlight: null,
    pinned: false,
    tags: [],
    cwd: "D:\\codex\\APS",
    archived: false,
    createdAt: 1,
    updatedAt: 1,
    status: "idle",
    isSubagent: false,
    agentNickname: null,
    agentRole: null,
    preferences: null,
    ...overrides
  };
}

test("explicit project context owns every conversation under the same root", () => {
  const sessions = [session("one"), session("two", { cwd: "D:\\codex\\other" })];
  const context = resolveProjectContext({
    projects: [project()],
    sessions,
    activeProjectName: "APS",
    selectedSessionId: "one"
  });

  assert.equal(context?.project.name, "APS");
  assert.deepEqual(context?.sessions.map((entry) => entry.id), ["one"]);
  assert.equal(context?.activeSession?.id, "one");
});

test("selected conversation restores its project by tag before cwd", () => {
  const context = resolveProjectContext({
    projects: [project(), project({ name: "Tagged", rootPath: "D:\\codex\\Tagged" })],
    sessions: [session("selected", { tags: ["Tagged"] })],
    activeProjectName: null,
    selectedSessionId: "selected"
  });

  assert.equal(context?.project.name, "Tagged");
});

test("selected conversation restores its project across Windows path formats", () => {
  const context = resolveProjectContext({
    projects: [project()],
    sessions: [session("selected", { cwd: "\\\\?\\D:\\CODEX\\aps\\" })],
    activeProjectName: null,
    selectedSessionId: "selected"
  });

  assert.equal(context?.identity, "d:\\codex\\aps");
  assert.equal(context?.repoPath, "D:\\codex\\APS");
});

test("V2 project identity owns conversations independently of display name and tags", () => {
  const context = resolveProjectContext({
    projects: [project({ projectId: "prj_aps", name: "APS Renamed", conversationIds: ["selected"] })],
    sessions: [session("selected", { cwd: "D:\\another-root", tags: [] })],
    activeProjectName: null,
    selectedSessionId: "selected"
  });

  assert.equal(context?.identity, "prj_aps");
  assert.equal(context?.project.name, "APS Renamed");
  assert.deepEqual(context?.sessions.map((entry) => entry.id), ["selected"]);
});

test("a moved V2 conversation follows its new explicit binding after compatibility cleanup", () => {
  const context = resolveProjectContext({
    projects: [
      project({ projectId: "prj_old", name: "Old", conversationIds: [] }),
      project({ projectId: "prj_new", name: "New", rootPath: "D:\\codex\\New", conversationIds: ["selected"] })
    ],
    sessions: [session("selected", { cwd: "D:\\codex\\APS", tags: ["keep"] })],
    activeProjectName: null,
    selectedSessionId: "selected"
  });

  assert.equal(context?.identity, "prj_new");
  assert.equal(context?.project.name, "New");
  assert.deepEqual(context?.sessions.map((entry) => entry.id), ["selected"]);
});

test("an archived project cleanup leaves its retained conversation unfiled", () => {
  const context = resolveProjectContext({
    projects: [],
    sessions: [session("selected", { tags: ["keep"] })],
    activeProjectName: null,
    selectedSessionId: "selected"
  });

  assert.equal(context, null);
});

test("projectId URL context survives a rename and wins over a stale display name", () => {
  const context = resolveProjectContext({
    projects: [
      project({ projectId: "prj_aps", name: "APS Renamed", conversationIds: ["selected"] }),
      project({ projectId: "prj_old", name: "APS", rootPath: "/srv/old", conversationIds: [] })
    ],
    sessions: [session("selected", { cwd: "D:\\another-root", tags: [] })],
    activeProjectId: "prj_aps",
    activeProjectName: "APS",
    selectedSessionId: null
  });

  assert.equal(context?.identity, "prj_aps");
  assert.equal(context?.project.name, "APS Renamed");
  assert.deepEqual(context?.sessions.map((entry) => entry.id), ["selected"]);
});

test("a project-scoped draft resolves its stable project id before applying workspace preferences", async () => {
  const source = await readFile(new URL("../src/routes/+page.svelte", import.meta.url), "utf8");
  const bootstrapStart = source.indexOf("async function bootstrap()");
  const bootstrapEnd = source.indexOf("async function refreshSessions", bootstrapStart);
  const bootstrap = source.slice(bootstrapStart, bootstrapEnd);
  const projectResolution = bootstrap.indexOf("const requestedProject = activeProjectId");
  const draftActivation = bootstrap.indexOf("if (draftSessionRequested)");

  assert.notEqual(projectResolution, -1);
  assert.notEqual(draftActivation, -1);
  assert.ok(projectResolution < draftActivation);
  assert.match(
    bootstrap,
    /activateDraftSession\(projectSessionPreferences\(requestedProject, config\.defaults\)\)/u
  );
});

test("a registered project exposes its immutable root without a broken change-root action", async () => {
  const source = await readFile(new URL("../src/lib/components/ProjectWorkspace.svelte", import.meta.url), "utf8");

  assert.match(source, /project\.rootPath/u);
  assert.match(source, /根目录已锁定/u);
  assert.match(source, /Import another directory as a new project/u);
  assert.doesNotMatch(source, /更换根目录|Change root/u);
});
