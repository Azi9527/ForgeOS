import type { SessionFolder, SessionSummary } from "./types";

function normalizeProjectRootPath(value: string | null | undefined) {
  const raw = value?.trim() ?? "";
  if (!raw) {
    return null;
  }
  const windowsPath = /^[a-z]:[\\/]/iu.test(raw) || /^\\\\/u.test(raw);
  const normalized = raw.replace(/^\\\\\?\\/u, "").replace(/[\\/]+$/u, "");
  return windowsPath ? normalized.toLocaleLowerCase() : normalized;
}

export type ProjectContext = {
  project: SessionFolder;
  identity: string;
  rootPath: string | null;
  repoPath: string | null;
  managed: boolean;
  sessions: SessionSummary[];
  activeSession: SessionSummary | null;
};

type ResolveProjectContextOptions = {
  projects: SessionFolder[];
  sessions: SessionSummary[];
  activeProjectId?: string | null;
  activeProjectName: string | null;
  selectedSessionId: string | null;
};

function projectMatchesSession(project: SessionFolder, session: SessionSummary) {
  if (project.projectId) {
    return project.conversationIds?.includes(session.id) ?? false;
  }
  if (session.tags.includes(project.name)) {
    return true;
  }
  const projectRoot = normalizeProjectRootPath(project.rootPath);
  return projectRoot !== null && normalizeProjectRootPath(session.cwd) === projectRoot;
}

export function resolveProjectContext({
  projects,
  sessions,
  activeProjectId = null,
  activeProjectName,
  selectedSessionId
}: ResolveProjectContextOptions): ProjectContext | null {
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const identifiedProject = activeProjectId
    ? projects.find((project) => project.projectId === activeProjectId) ?? null
    : null;
  const explicitProject = projects.find((project) => project.name === activeProjectName) ?? null;
  const boundProject = selectedSession
    ? projects.find((project) => project.projectId && project.conversationIds?.includes(selectedSession.id)) ?? null
    : null;
  const taggedProject = selectedSession
    ? projects.find((project) => selectedSession.tags.includes(project.name)) ?? null
    : null;
  const selectedRoot = normalizeProjectRootPath(selectedSession?.cwd);
  const rootedProject = selectedRoot
    ? projects.find((project) => normalizeProjectRootPath(project.rootPath) === selectedRoot) ?? null
    : null;
  const project = identifiedProject ?? explicitProject ?? boundProject ?? taggedProject ?? rootedProject;
  if (!project) {
    return null;
  }

  const projectSessions = sessions.filter((session) => projectMatchesSession(project, session));
  const activeSession = selectedSession && projectMatchesSession(project, selectedSession)
    ? selectedSession
    : projectSessions.find((session) => session.id === project.lastSessionId) ?? null;
  const rootPath = project.rootPath ?? activeSession?.cwd ?? null;

  return {
    project,
    identity: project.projectId ?? normalizeProjectRootPath(rootPath) ?? project.name.toLocaleLowerCase(),
    rootPath,
    repoPath: project.repoPath ?? activeSession?.preferences?.gitRepoPath ?? null,
    managed: project.managed !== false,
    sessions: projectSessions,
    activeSession
  };
}
