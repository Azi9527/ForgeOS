const windowsReservedNames = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/iu;
const invalidProjectNameCharacters = /[<>:"/\\|?*\u0000-\u001f]/u;

export function normalizeProjectFolderName(value: string) {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error("项目名称不能为空。");
  }
  if (normalized === "." || normalized === "..") {
    throw new Error("项目名称不能是 . 或 ..。");
  }
  if (invalidProjectNameCharacters.test(normalized)) {
    throw new Error("项目名称不能包含路径分隔符或 Windows 文件名保留字符。");
  }
  if (/[. ]$/u.test(normalized)) {
    throw new Error("项目名称不能以空格或句点结尾。");
  }
  if (windowsReservedNames.test(normalized)) {
    throw new Error("项目名称不能使用 Windows 保留名称。");
  }
  return normalized;
}

export function buildProjectRootPath(parentPath: string, projectName: string) {
  const parent = parentPath.trim();
  if (!parent) {
    throw new Error("请选择项目保存位置。");
  }
  const name = normalizeProjectFolderName(projectName);
  const separator = parent.includes("\\") ? "\\" : "/";
  const normalizedParent = parent === "/" ? "/" : parent.replace(/[\\/]+$/u, "");
  return normalizedParent === "/" ? `/${name}` : `${normalizedParent}${separator}${name}`;
}

export function normalizeProjectRootPath(value: string | null | undefined) {
  const raw = value?.trim() ?? "";
  if (!raw) {
    return null;
  }
  const windowsPath = /^[a-z]:[\\/]/iu.test(raw) || /^\\\\/u.test(raw);
  const normalized = raw.replace(/^\\\\\?\\/u, "").replace(/[\\/]+$/u, "");
  return windowsPath ? normalized.toLocaleLowerCase() : normalized;
}
