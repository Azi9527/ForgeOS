import type { SessionFolder, SessionSummary } from "./types";

function normalizeProjectRootPath(value: string | null | undefined) {
  const normalized = value?.trim().replace(/^\\\\\?\\/u, "").replace(/[\\/]+$/u, "").toLocaleLowerCase() ?? "";
  return normalized || null;
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
  activeProjectName: string | null;
  selectedSessionId: string | null;
};

function projectMatchesSession(project: SessionFolder, session: SessionSummary) {
  if (session.tags.includes(project.name)) {
    return true;
  }
  const projectRoot = normalizeProjectRootPath(project.rootPath);
  return projectRoot !== null && normalizeProjectRootPath(session.cwd) === projectRoot;
}

export function resolveProjectContext({
  projects,
  sessions,
  activeProjectName,
  selectedSessionId
}: ResolveProjectContextOptions): ProjectContext | null {
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const explicitProject = projects.find((project) => project.name === activeProjectName) ?? null;
  const taggedProject = selectedSession
    ? projects.find((project) => selectedSession.tags.includes(project.name)) ?? null
    : null;
  const selectedRoot = normalizeProjectRootPath(selectedSession?.cwd);
  const rootedProject = selectedRoot
    ? projects.find((project) => normalizeProjectRootPath(project.rootPath) === selectedRoot) ?? null
    : null;
  const project = explicitProject ?? taggedProject ?? rootedProject;
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
    identity: normalizeProjectRootPath(rootPath) ?? project.name.toLocaleLowerCase(),
    rootPath,
    repoPath: project.repoPath ?? activeSession?.preferences?.gitRepoPath ?? null,
    managed: project.managed !== false,
    sessions: projectSessions,
    activeSession
  };
}
