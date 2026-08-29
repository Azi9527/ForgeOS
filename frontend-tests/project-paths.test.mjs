import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProjectRootPath,
  normalizeProjectFolderName,
  normalizeProjectRootPath
} from "../src/lib/project-paths.ts";

test("a Windows project is created as a child folder named after the project", () => {
  assert.equal(buildProjectRootPath("D:\\codex", "WebTest"), "D:\\codex\\WebTest");
});

test("a POSIX project is created as a child folder named after the project", () => {
  assert.equal(buildProjectRootPath("/srv/forgeos", "WebTest"), "/srv/forgeos/WebTest");
});

test("project folder names cannot escape the selected parent", () => {
  assert.throws(() => normalizeProjectFolderName("../WebTest"));
  assert.throws(() => normalizeProjectFolderName("Web/Test"));
  assert.throws(() => normalizeProjectFolderName("CON"));
});

test("project roots match across Windows casing and extended path prefixes", () => {
  assert.equal(normalizeProjectRootPath("\\\\?\\D:\\codex\\APS\\"), "d:\\codex\\aps");
  assert.equal(normalizeProjectRootPath("D:\\CODEX\\aps"), "d:\\codex\\aps");
  assert.equal(normalizeProjectRootPath("  "), null);
});

test("POSIX project roots remain case-sensitive", () => {
  assert.equal(normalizeProjectRootPath("/srv/ForgeOS/App/"), "/srv/ForgeOS/App");
  assert.notEqual(normalizeProjectRootPath("/srv/ForgeOS/App"), normalizeProjectRootPath("/srv/forgeos/app"));
});
