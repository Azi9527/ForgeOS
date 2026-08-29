import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProjectManifestPath,
  buildProjectRootPath,
  normalizeProjectFolderName,
  normalizeProjectRootPath
} from "../src/lib/project-paths.ts";

test("a Windows project is created as a child folder named after the project", () => {
  assert.equal(buildProjectRootPath("D:\\codex", "WebTest"), "D:\\codex\\WebTest");
  assert.equal(
    buildProjectManifestPath("D:\\codex\\WebTest"),
    "D:\\codex\\WebTest\\.forgeos\\project.json"
  );
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
