use super::*;
use sha2::Digest as _;

#[cfg(test)]
#[path = "project_operation_command_support_tests.rs"]
mod tests;

const MAX_OPERATION_LOG_BYTES: usize = 12_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum OperationCommand {
    Local(String),
    GitHubActions {
        repository: String,
        workflow: String,
        reference: String,
        version: String,
    },
}

impl OperationCommand {
    pub(crate) fn adapter(&self) -> &'static str {
        match self {
            Self::Local(_) => "localCommand",
            Self::GitHubActions { .. } => "githubActions",
        }
    }

    pub(crate) fn configuration_digest(&self) -> String {
        let encoded = match self {
            Self::Local(command) => format!("localCommand\0{command}"),
            Self::GitHubActions {
                repository,
                workflow,
                reference,
                version,
            } => format!("githubActions\0{repository}\0{workflow}\0{reference}\0{version}"),
        };
        sha256_hex(encoded.as_bytes())
    }
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct OperationResult {
    pub(crate) exit_code: i32,
    pub(crate) logs: String,
}

pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn environment_by_id<'a>(lifecycle: &'a Value, environment_id: &str) -> ApiResult<&'a Value> {
    lifecycle["operations"]["environments"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|environment| environment.get("id").and_then(Value::as_str) == Some(environment_id))
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project environment was not found."))
}

fn release_by_id<'a>(lifecycle: &'a Value, release_id: &str) -> ApiResult<&'a Value> {
    lifecycle["release"]["releases"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|release| release.get("id").and_then(Value::as_str) == Some(release_id))
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project release was not found."))
}

fn safe_repository(value: &str) -> bool {
    let Some((owner, name)) = value.split_once('/') else {
        return false;
    };
    !owner.is_empty()
        && !name.is_empty()
        && !name.contains('/')
        && [owner, name].into_iter().all(|part| {
            part.starts_with(|character: char| character.is_ascii_alphanumeric())
                && part
                    .chars()
                    .all(|character| character.is_ascii_alphanumeric() || "_.-".contains(character))
        })
}

fn safe_github_path(value: &str) -> bool {
    value.starts_with(|character: char| character.is_ascii_alphanumeric() || character == '.')
        && !value.contains("..")
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "_./-".contains(character))
}

fn safe_release_version(value: &str) -> bool {
    value.starts_with(|character: char| character.is_ascii_alphanumeric())
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "._+-".contains(character))
}

pub(crate) fn deployment_command(
    lifecycle: &Value,
    release_id: &str,
    environment_id: &str,
) -> ApiResult<OperationCommand> {
    let release = release_by_id(lifecycle, release_id)?;
    if release.get("status").and_then(Value::as_str) != Some("released") {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Deployment requires a released release.",
        ));
    }
    if release.get("targetEnvironmentId").and_then(Value::as_str) != Some(environment_id) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Deployment environment must match the release target environment.",
        ));
    }
    let environment = environment_by_id(lifecycle, environment_id)?;
    if environment.get("adapter").and_then(Value::as_str) == Some("githubActions") {
        let repository = environment
            .get("githubRepository")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let workflow = environment
            .get("githubWorkflow")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let reference = environment
            .get("githubRef")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let version = release
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if !safe_repository(repository)
            || !safe_github_path(workflow)
            || !safe_github_path(reference)
            || !safe_release_version(version)
        {
            return Err(api_error(
                StatusCode::CONFLICT,
                "The saved GitHub Actions adapter configuration is invalid.",
            ));
        }
        return Ok(OperationCommand::GitHubActions {
            repository: repository.to_string(),
            workflow: workflow.to_string(),
            reference: reference.to_string(),
            version: version.to_string(),
        });
    }

    let command = environment
        .get("deployCommand")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "The environment does not have a saved deployment command.",
            )
        })?;
    Ok(OperationCommand::Local(command.to_string()))
}

pub(crate) fn health_check_command(
    lifecycle: &Value,
    environment_id: &str,
) -> ApiResult<OperationCommand> {
    let command = environment_by_id(lifecycle, environment_id)?
        .get("healthCommand")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "The environment does not have a saved health check command.",
            )
        })?;
    Ok(OperationCommand::Local(command.to_string()))
}

pub(crate) async fn validated_project_root(
    state: &AppState,
    root_path: &str,
) -> ApiResult<PathBuf> {
    let root = tokio_fs::canonicalize(root_path).await.map_err(|_| {
        api_error(
            StatusCode::CONFLICT,
            "The bound project root directory is unavailable.",
        )
    })?;
    let metadata = tokio_fs::metadata(&root).await.map_err(|_| {
        api_error(
            StatusCode::CONFLICT,
            "The bound project root directory is unavailable.",
        )
    })?;
    let allowed = metadata.is_dir()
        && resolved_allowed_roots(&state.config)
            .await
            .iter()
            .any(|allowed_root| path_is_within(allowed_root, &root));
    if !allowed {
        return Err(api_error(
            StatusCode::FORBIDDEN,
            "The bound project root must stay within an allowed root.",
        ));
    }
    Ok(root)
}

fn bounded_logs(stdout: &[u8], stderr: &[u8]) -> String {
    let stdout = String::from_utf8_lossy(stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(stderr).trim().to_string();
    let combined = match (stdout.is_empty(), stderr.is_empty()) {
        (false, false) => format!("[stdout]\n{stdout}\n\n[stderr]\n{stderr}"),
        (false, true) => stdout,
        (true, false) => stderr,
        (true, true) => String::new(),
    };
    let combined = redact_engineering_evidence(&combined);
    if combined.len() <= MAX_OPERATION_LOG_BYTES {
        return combined;
    }
    let mut start = combined.len() - MAX_OPERATION_LOG_BYTES;
    while !combined.is_char_boundary(start) {
        start += 1;
    }
    format!("… earlier output truncated …\n{}", &combined[start..])
}

fn command_builder(command: &OperationCommand) -> Command {
    match command {
        OperationCommand::Local(script) => {
            #[cfg(windows)]
            let builder = {
                let mut builder = Command::new("powershell.exe");
                builder.args([
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ]);
                builder
            };
            #[cfg(not(windows))]
            let builder = {
                let mut builder = Command::new("sh");
                builder.args(["-lc", script]);
                builder
            };
            builder
        }
        OperationCommand::GitHubActions {
            repository,
            workflow,
            reference,
            version,
        } => {
            let mut builder = Command::new("gh");
            builder.args([
                "workflow",
                "run",
                workflow,
                "--repo",
                repository,
                "--ref",
                reference,
                "-f",
                &format!("forgeos_release={version}"),
            ]);
            builder
        }
    }
}

pub(crate) async fn run_operation_command(
    root: &Path,
    operation: &OperationCommand,
    timeout: Duration,
) -> OperationResult {
    let mut command = command_builder(operation);
    command
        .current_dir(root)
        .env("GH_PAGER", "cat")
        .env("GH_PROMPT_DISABLED", "1")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("PAGER", "cat")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    command.process_group(0);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            return OperationResult {
                exit_code: -1,
                logs: format!("Failed to start the saved operation: {error}"),
            };
        }
    };
    let child_pid = child.id();
    let Some(stdout) = child.stdout.take() else {
        terminate_child_process_group(&mut child, child_pid).await;
        return OperationResult {
            exit_code: -1,
            logs: "Failed to capture operation stdout.".to_string(),
        };
    };
    let Some(stderr) = child.stderr.take() else {
        terminate_child_process_group(&mut child, child_pid).await;
        return OperationResult {
            exit_code: -1,
            logs: "Failed to capture operation stderr.".to_string(),
        };
    };

    match tokio::time::timeout(timeout, async {
        tokio::try_join!(
            async {
                child
                    .wait()
                    .await
                    .with_context(|| "failed to wait for saved project operation")
            },
            read_child_pipe_limited(stdout, "stdout"),
            read_child_pipe_limited(stderr, "stderr")
        )
    })
    .await
    {
        Ok(Ok((status, stdout, stderr))) => OperationResult {
            exit_code: status.code().unwrap_or(1),
            logs: bounded_logs(&stdout, &stderr),
        },
        Ok(Err(error)) => {
            terminate_child_process_group(&mut child, child_pid).await;
            OperationResult {
                exit_code: 1,
                logs: format!("Saved operation failed: {error}"),
            }
        }
        Err(_) => {
            terminate_child_process_group(&mut child, child_pid).await;
            OperationResult {
                exit_code: 124,
                logs: "Saved operation timed out and was terminated.".to_string(),
            }
        }
    }
}
