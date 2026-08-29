import assert from "node:assert/strict";
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
