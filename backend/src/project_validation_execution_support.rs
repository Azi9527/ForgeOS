use super::*;
use sha2::Digest as _;
use tokio_util::sync::CancellationToken;

#[cfg(test)]
#[path = "project_validation_execution_support_tests.rs"]
mod tests;

const MAX_VALIDATION_CHECKS: usize = 12;
const MAX_VALIDATION_RUNS: usize = 20;
const MAX_EVIDENCE_OUTPUT_BYTES: usize = 12_000;
const VALIDATION_CHECK_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const VALIDATION_RUN_TIMEOUT: Duration = Duration::from_secs(30 * 60);

#[derive(Clone, Debug, Eq, PartialEq)]
struct ValidationCheckConfig {
    id: String,
    label: String,
    command: String,
    required: bool,
}

#[derive(Clone, Debug)]
struct ValidationSnapshot {
    root_path: String,
    persisted_checks: Value,
    configuration_digest: String,
    checks: Vec<ValidationCheckConfig>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ValidationCommandStatus {
    Passed,
    Failed,
    Cancelled,
}

#[derive(Debug, Eq, PartialEq)]
struct ValidationCommandResult {
    status: ValidationCommandStatus,
    exit_code: Option<i32>,
    duration_ms: u64,
    output: String,
}

#[derive(Debug)]
struct CapturedPipe {
    bytes: Vec<u8>,
    truncated: bool,
}

#[derive(Clone)]
struct ActiveValidation {
    run_id: String,
    cancellation: CancellationToken,
}

struct ActiveValidationGuard {
    key: String,
    run_id: String,
}

impl Drop for ActiveValidationGuard {
    fn drop(&mut self) {
        if let Ok(mut active) = active_validations().lock()
            && active
                .get(&self.key)
                .is_some_and(|validation| validation.run_id == self.run_id)
        {
            active.remove(&self.key);
        }
    }
}

fn active_validations() -> &'static std::sync::Mutex<HashMap<String, ActiveValidation>> {
    static ACTIVE: std::sync::OnceLock<std::sync::Mutex<HashMap<String, ActiveValidation>>> =
        std::sync::OnceLock::new();
    ACTIVE.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

fn active_validation_key(profile_id: &str, project_id: &str) -> String {
    format!("{profile_id}\0{project_id}")
}

fn validation_run_is_active(profile_id: &str, project_id: &str, run_id: &str) -> bool {
    active_validations().lock().is_ok_and(|active| {
        active
            .get(&active_validation_key(profile_id, project_id))
            .is_some_and(|validation| validation.run_id == run_id)
    })
}

fn register_active_validation(
    profile_id: &str,
    project_id: &str,
    run_id: &str,
    cancellation: CancellationToken,
) -> ApiResult<ActiveValidationGuard> {
    let key = active_validation_key(profile_id, project_id);
    let mut active = active_validations().lock().map_err(|_| {
        api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Project validation executor is unavailable.",
        )
    })?;
    if active.contains_key(&key) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "A project validation run is already active.",
        ));
    }
    active.insert(
        key.clone(),
        ActiveValidation {
            run_id: run_id.to_string(),
            cancellation,
        },
    );
    Ok(ActiveValidationGuard {
        key,
        run_id: run_id.to_string(),
    })
}

fn require_validation_role(state: &AppState, auth: &AuthContext) -> ApiResult<()> {
    if role_has_admin_access(auth.role) && role_has_owner_access(&state.config, auth.role) {
        Ok(())
    } else {
        Err(api_error(
            StatusCode::FORBIDDEN,
            "Only an owner-authorized admin or owner can control project validation.",
        ))
    }
}

fn reject_unsupported_params(params: &Value, allowed: &[&str]) -> ApiResult<()> {
    let object = params
        .as_object()
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "params must be an object"))?;
    if let Some(field) = object.keys().find(|field| {
        !allowed.contains(&field.as_str())
            && !matches!(field.as_str(), "requestProfileId" | "request_profile_id")
    }) {
        return Err(api_error(
            StatusCode::BAD_REQUEST,
            format!("Unsupported project validation parameter: {field}"),
        ));
    }
    Ok(())
}

fn require_validation_run_params(params: &Value) -> ApiResult<(String, u64)> {
    reject_unsupported_params(params, &["projectId", "expectedRevision"])?;
    let project_id = require_lifecycle_project_id(params)?;
    let expected_revision = params
        .get("expectedRevision")
        .and_then(Value::as_u64)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "expectedRevision is required"))?;
    Ok((project_id, expected_revision))
}

fn require_validation_cancel_params(params: &Value) -> ApiResult<String> {
    reject_unsupported_params(params, &["projectId"])?;
    require_lifecycle_project_id(params)
}

fn validation_check_config(value: &Value) -> ApiResult<Option<ValidationCheckConfig>> {
    let id = value
        .get("id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| api_error(StatusCode::CONFLICT, "A saved validation check has no id."))?;
    let label = value
        .get("label")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "A saved validation check has no label.",
            )
        })?;
    let command = value
        .get("command")
        .and_then(Value::as_str)
        .map(str::trim)
        .unwrap_or_default();
    if command.is_empty() {
        return Ok(None);
    }
    Ok(Some(ValidationCheckConfig {
        id: id.to_string(),
        label: label.to_string(),
        command: command.to_string(),
        required: value
            .get("required")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    }))
}

fn configured_validation_checks(value: &Value) -> ApiResult<Vec<ValidationCheckConfig>> {
    let checks = value
        .as_array()
        .ok_or_else(|| api_error(StatusCode::CONFLICT, "Project validation state is invalid."))?
        .iter()
        .take(MAX_VALIDATION_CHECKS)
        .filter_map(|check| validation_check_config(check).transpose())
        .collect::<ApiResult<Vec<_>>>()?;
    if checks.is_empty() {
        return Err(api_error(
            StatusCode::CONFLICT,
            "The project does not have any configured validation commands.",
        ));
    }
    Ok(checks)
}

fn require_expected_revision(lifecycle: &Value, expected_revision: u64) -> ApiResult<()> {
    if lifecycle
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        == expected_revision
    {
        Ok(())
    } else {
        Err(api_error(
            StatusCode::CONFLICT,
            "Project lifecycle state changed. Reload and retry.",
        ))
    }
}

async fn validation_snapshot(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    expected_revision: u64,
) -> ApiResult<ValidationSnapshot> {
    with_ui_state_read(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, project_id)?;
        if project.get("status").and_then(Value::as_str) == Some("archived") {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Archived projects cannot run validation.",
            ));
        }
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let root_path = project
            .get("rootPath")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                api_error(
                    StatusCode::CONFLICT,
                    "The project does not have a bound root directory.",
                )
            })?;
        let lifecycle = lifecycle_from_state(ui_state, project_id, project_name);
        require_expected_revision(&lifecycle, expected_revision)?;
        let persisted_checks = lifecycle["validation"]["checks"].clone();
        let checks = configured_validation_checks(&persisted_checks)?;
        let configuration_digest =
            sha256_hex(&serde_json::to_vec(&persisted_checks).map_err(|error| {
                api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string())
            })?);
        Ok(ValidationSnapshot {
            root_path: root_path.to_string(),
            persisted_checks,
            configuration_digest,
            checks,
        })
    })
    .await
}

async fn validated_validation_root(state: &AppState, root_path: &str) -> ApiResult<PathBuf> {
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

async fn git_validation_evidence(
    state: &AppState,
    root: &Path,
) -> (Option<String>, Option<String>) {
    let root_text = root.display().to_string();
    let Ok(repo_root) = resolve_git_repo_root(state, &root_text).await else {
        return (None, None);
    };
    let branch = run_git_text_payload(
        state,
        &repo_root,
        vec![
            "rev-parse".to_string(),
            "--abbrev-ref".to_string(),
            "HEAD".to_string(),
        ],
    )
    .await
    .ok()
    .map(|value| value.trim().to_string())
    .filter(|value| !value.is_empty() && value != "HEAD");
    let commit = run_git_text_payload(
        state,
        &repo_root,
        vec!["rev-parse".to_string(), "HEAD".to_string()],
    )
    .await
    .ok()
    .map(|value| value.trim().to_string())
    .filter(|value| !value.is_empty());
    (branch, commit)
}

fn validation_command(command: &str) -> Command {
    #[cfg(windows)]
    {
        let wrapped = format!(
            "$global:LASTEXITCODE = 0; & {{ {command} }}; \
             $forgeExit = if ($?) {{ if ($null -eq $LASTEXITCODE) {{ 0 }} else {{ $LASTEXITCODE }} }} \
             else {{ if ($null -eq $LASTEXITCODE) {{ 1 }} else {{ $LASTEXITCODE }} }}; exit $forgeExit"
        );
        let mut process = Command::new("powershell.exe");
        process.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            &wrapped,
        ]);
        process
    }
    #[cfg(not(windows))]
    {
        let mut process = Command::new("sh");
        process.args(["-lc", command]);
        process
    }
}

async fn read_pipe_tail<R>(mut reader: R) -> std::io::Result<CapturedPipe>
where
    R: tokio::io::AsyncRead + Unpin,
{
    let mut bytes = Vec::with_capacity(MAX_EVIDENCE_OUTPUT_BYTES);
    let mut chunk = [0_u8; 8192];
    let mut truncated = false;
    loop {
        let count = reader.read(&mut chunk).await?;
        if count == 0 {
            break;
        }
        if count >= MAX_EVIDENCE_OUTPUT_BYTES {
            bytes.clear();
            bytes.extend_from_slice(&chunk[count - MAX_EVIDENCE_OUTPUT_BYTES..count]);
            truncated = true;
            continue;
        }
        let overflow = bytes
            .len()
            .saturating_add(count)
            .saturating_sub(MAX_EVIDENCE_OUTPUT_BYTES);
        if overflow > 0 {
            bytes.drain(..overflow);
            truncated = true;
        }
        bytes.extend_from_slice(&chunk[..count]);
    }
    Ok(CapturedPipe { bytes, truncated })
}

fn bounded_output_tail(value: &str) -> String {
    if value.len() <= MAX_EVIDENCE_OUTPUT_BYTES {
        return value.to_string();
    }
    const PREFIX: &str = "… earlier output truncated …\n";
    let tail_limit = MAX_EVIDENCE_OUTPUT_BYTES.saturating_sub(PREFIX.len());
    let mut start = value.len().saturating_sub(tail_limit);
    while !value.is_char_boundary(start) {
        start += 1;
    }
    format!("{PREFIX}{}", &value[start..])
}

fn combined_validation_output(stdout: CapturedPipe, stderr: CapturedPipe) -> String {
    let stdout_text = String::from_utf8_lossy(&stdout.bytes).trim().to_string();
    let stderr_text = String::from_utf8_lossy(&stderr.bytes).trim().to_string();
    let combined = match (stdout_text.is_empty(), stderr_text.is_empty()) {
        (false, false) => format!("[stdout]\n{stdout_text}\n\n[stderr]\n{stderr_text}"),
        (false, true) => stdout_text,
        (true, false) => stderr_text,
        (true, true) => String::new(),
    };
    let combined = if stdout.truncated || stderr.truncated {
        format!("… earlier output truncated …\n{combined}")
    } else {
        combined
    };
    bounded_output_tail(&combined)
}

async fn terminate_validation_process(pid: Option<u32>) {
    let Some(pid) = pid else {
        return;
    };
    #[cfg(windows)]
    {
        let _ = run_command_with_timeout(
            "taskkill",
            vec![
                "/PID".to_string(),
                pid.to_string(),
                "/T".to_string(),
                "/F".to_string(),
            ],
            Duration::from_secs(4),
        )
        .await;
    }
    #[cfg(unix)]
    {
        let group = format!("-{pid}");
        let _ = run_command_with_timeout(
            "kill",
            vec!["-TERM".to_string(), "--".to_string(), group.clone()],
            Duration::from_secs(4),
        )
        .await;
        tokio::time::sleep(Duration::from_millis(200)).await;
        let _ = run_command_with_timeout(
            "kill",
            vec!["-KILL".to_string(), "--".to_string(), group],
            Duration::from_secs(4),
        )
        .await;
    }
}

async fn captured_pipe_result(
    task: tokio::task::JoinHandle<std::io::Result<CapturedPipe>>,
) -> CapturedPipe {
    match tokio::time::timeout(Duration::from_secs(2), task).await {
        Ok(Ok(Ok(captured))) => captured,
        Ok(Ok(Err(_))) | Ok(Err(_)) | Err(_) => CapturedPipe {
            bytes: Vec::new(),
            truncated: false,
        },
    }
}

async fn run_validation_command(
    root: &Path,
    command_text: &str,
    cancellation: &CancellationToken,
    timeout: Duration,
) -> ValidationCommandResult {
    let started = Instant::now();
    if cancellation.is_cancelled() {
        return ValidationCommandResult {
            status: ValidationCommandStatus::Cancelled,
            exit_code: None,
            duration_ms: 0,
            output: "Validation cancelled by the operator before the command started.".to_string(),
        };
    }
    let mut command = validation_command(command_text);
    command
        .current_dir(root)
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("PAGER", "cat")
        .kill_on_drop(true)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    command.process_group(0);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            return ValidationCommandResult {
                status: ValidationCommandStatus::Failed,
                exit_code: Some(-1),
                duration_ms: started.elapsed().as_millis() as u64,
                output: format!("Failed to start the saved validation command: {error}"),
            };
        }
    };
    let pid = child.id();
    let stdout = child
        .stdout
        .take()
        .map(|stdout| tokio::spawn(read_pipe_tail(stdout)));
    let stderr = child
        .stderr
        .take()
        .map(|stderr| tokio::spawn(read_pipe_tail(stderr)));

    enum WaitResult {
        Completed(std::io::Result<std::process::ExitStatus>),
        Cancelled,
        TimedOut,
    }
    let wait_result = tokio::select! {
        biased;
        _ = cancellation.cancelled() => WaitResult::Cancelled,
        result = child.wait() => WaitResult::Completed(result),
        _ = tokio::time::sleep(timeout) => WaitResult::TimedOut,
    };
    if !matches!(wait_result, WaitResult::Completed(_)) {
        terminate_validation_process(pid).await;
        let _ = child.wait().await;
    }

    let stdout = match stdout {
        Some(task) => captured_pipe_result(task).await,
        None => CapturedPipe {
            bytes: Vec::new(),
            truncated: false,
        },
    };
    let stderr = match stderr {
        Some(task) => captured_pipe_result(task).await,
        None => CapturedPipe {
            bytes: Vec::new(),
            truncated: false,
        },
    };
    let captured = combined_validation_output(stdout, stderr);
    let duration_ms = started.elapsed().as_millis() as u64;
    match wait_result {
        WaitResult::Completed(Ok(status)) => ValidationCommandResult {
            status: if status.success() {
                ValidationCommandStatus::Passed
            } else {
                ValidationCommandStatus::Failed
            },
            exit_code: Some(status.code().unwrap_or(1)),
            duration_ms,
            output: captured,
        },
        WaitResult::Completed(Err(error)) => ValidationCommandResult {
            status: ValidationCommandStatus::Failed,
            exit_code: Some(-1),
            duration_ms,
            output: bounded_output_tail(&format!(
                "{captured}\nFailed to wait for the saved validation command: {error}"
            )),
        },
        WaitResult::Cancelled => ValidationCommandResult {
            status: ValidationCommandStatus::Cancelled,
            exit_code: None,
            duration_ms,
            output: bounded_output_tail(&format!(
                "{captured}\nValidation cancelled by the operator."
            )),
        },
        WaitResult::TimedOut => ValidationCommandResult {
            status: ValidationCommandStatus::Failed,
            exit_code: Some(124),
            duration_ms,
            output: bounded_output_tail(&format!(
                "{captured}\nValidation command exceeded its server timeout and was terminated."
            )),
        },
    }
}

fn pending_validation_evidence(check: &ValidationCheckConfig) -> Value {
    json!({
        "id": check.id,
        "label": check.label,
        "command": check.command,
        "required": check.required,
        "status": "pending",
        "exitCode": Value::Null,
        "durationMs": Value::Null,
        "output": ""
    })
}

fn apply_command_result(evidence: &mut Value, result: ValidationCommandResult) {
    evidence["status"] = json!(match result.status {
        ValidationCommandStatus::Passed => "passed",
        ValidationCommandStatus::Failed => "failed",
        ValidationCommandStatus::Cancelled => "cancelled",
    });
    evidence["exitCode"] = result.exit_code.map_or(Value::Null, |value| json!(value));
    evidence["durationMs"] = json!(result.duration_ms);
    evidence["output"] = json!(bounded_output_tail(&redact_engineering_evidence(
        &result.output
    )));
}

async fn execute_validation_checks(
    root: &Path,
    checks: &[ValidationCheckConfig],
    cancellation: &CancellationToken,
) -> Vec<Value> {
    let started = Instant::now();
    let mut evidence = checks
        .iter()
        .map(pending_validation_evidence)
        .collect::<Vec<_>>();
    for (index, check) in checks.iter().enumerate() {
        if cancellation.is_cancelled() {
            for pending in &mut evidence[index..] {
                pending["status"] = json!("cancelled");
                pending["output"] = json!("Validation cancelled before this check started.");
            }
            break;
        }
        let Some(remaining) = VALIDATION_RUN_TIMEOUT.checked_sub(started.elapsed()) else {
            evidence[index]["status"] = json!("failed");
            evidence[index]["exitCode"] = json!(124);
            evidence[index]["durationMs"] = json!(0);
            evidence[index]["output"] =
                json!("The project validation run exceeded its server timeout.");
            break;
        };
        let result = run_validation_command(
            root,
            &check.command,
            cancellation,
            remaining.min(VALIDATION_CHECK_TIMEOUT),
        )
        .await;
        let status = result.status;
        apply_command_result(&mut evidence[index], result);
        if status == ValidationCommandStatus::Cancelled {
            for pending in &mut evidence[index + 1..] {
                pending["status"] = json!("cancelled");
                pending["output"] = json!("Validation cancelled before this check started.");
            }
            break;
        }
        if check.required && status == ValidationCommandStatus::Failed {
            break;
        }
    }
    evidence
}

fn validation_run_status(checks: &[Value]) -> &'static str {
    if checks
        .iter()
        .any(|check| check.get("status").and_then(Value::as_str) == Some("cancelled"))
    {
        return "cancelled";
    }
    if checks.iter().any(|check| {
        check
            .get("required")
            .and_then(Value::as_bool)
            .unwrap_or(true)
            && check.get("status").and_then(Value::as_str) != Some("passed")
    }) {
        "failed"
    } else {
        "passed"
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn finalize_validation_run(mut run: Value) -> ApiResult<Value> {
    run.as_object_mut()
        .expect("validation run is an object")
        .remove("evidenceDigest");
    let encoded = serde_json::to_vec(&run)
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    run.as_object_mut()
        .expect("validation run is an object")
        .insert("evidenceDigest".to_string(), json!(sha256_hex(&encoded)));
    Ok(run)
}

fn interrupted_validation_run(mut run: Value, finished_at: u64) -> ApiResult<Value> {
    run["status"] = json!("interrupted");
    run["finishedAt"] = json!(finished_at);
    if let Some(checks) = run.get_mut("checks").and_then(Value::as_array_mut) {
        for check in checks {
            if let Some(output) = check.get("output").and_then(Value::as_str) {
                check["output"] = json!(bounded_output_tail(&redact_engineering_evidence(output)));
            }
            if matches!(
                check.get("status").and_then(Value::as_str),
                Some("pending" | "running")
            ) {
                check["status"] = json!("cancelled");
                check["output"] = json!(
                    "Gateway execution was interrupted before completion; no client-reported result was accepted."
                );
            }
        }
    }
    finalize_validation_run(run)
}

pub(crate) async fn recover_interrupted_project_validations(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
) -> ApiResult<()> {
    let interrupted_ids = with_ui_state_read(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, project_id)?;
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let lifecycle = lifecycle_from_state(ui_state, project_id, project_name);
        Ok(lifecycle["validation"]["runs"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|run| run.get("status").and_then(Value::as_str) == Some("running"))
            .filter_map(|run| run.get("id").and_then(Value::as_str))
            .filter(|run_id| !validation_run_is_active(profile_id, project_id, run_id))
            .map(str::to_string)
            .collect::<HashSet<_>>())
    })
    .await?;
    if interrupted_ids.is_empty() {
        return Ok(());
    }

    let finished_at = now_unix_ms();
    update_project_lifecycle(
        state,
        profile_id,
        json!({ "projectId": project_id }),
        move |lifecycle, _params, _project| {
            let runs = lifecycle["validation"]["runs"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "Project validation runs state is invalid.",
                    )
                })?;
            for run in runs {
                let interrupted = run.get("status").and_then(Value::as_str) == Some("running")
                    && run
                        .get("id")
                        .and_then(Value::as_str)
                        .is_some_and(|run_id| interrupted_ids.contains(run_id));
                if interrupted {
                    *run = interrupted_validation_run(run.clone(), finished_at)?;
                }
            }
            Ok(())
        },
    )
    .await?;
    let _ = append_audit_log(
        &state.config,
        AuditLogEntry {
            id: Uuid::new_v4().to_string(),
            at: now_unix_ms(),
            role: "system".to_string(),
            method: "projectLifecycle/validation/recover".to_string(),
            target: Some(project_id.to_string()),
            ok: true,
            error: None,
        },
    )
    .await;
    Ok(())
}

pub(crate) async fn run_project_validation_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    require_validation_role(state, auth)?;
    let (project_id, expected_revision) = require_validation_run_params(&params)?;
    recover_interrupted_project_validations(state, &auth.profile_id, &project_id).await?;
    let snapshot =
        validation_snapshot(state, &auth.profile_id, &project_id, expected_revision).await?;
    let root = validated_validation_root(state, &snapshot.root_path).await?;
    let run_id = format!("validation_{}", Uuid::new_v4().simple());
    let cancellation = CancellationToken::new();
    let _active =
        register_active_validation(&auth.profile_id, &project_id, &run_id, cancellation.clone())?;
    let started_at = now_unix_ms();
    let (branch, commit) = git_validation_evidence(state, &root).await;
    let running_run = finalize_validation_run(json!({
        "id": run_id,
        "startedAt": started_at,
        "finishedAt": Value::Null,
        "status": "running",
        "rootPath": root.display().to_string(),
        "branch": branch,
        "commit": commit,
        "configurationDigest": snapshot.configuration_digest,
        "checks": snapshot
            .checks
            .iter()
            .map(pending_validation_evidence)
            .collect::<Vec<_>>(),
        "operator": auth_operator(auth)
    }))?;
    let expected_root_path = snapshot.root_path.clone();
    let expected_checks = snapshot.persisted_checks.clone();
    update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({
            "projectId": project_id,
            "expectedRevision": expected_revision
        }),
        move |lifecycle, _params, project| {
            if project.get("rootPath").and_then(Value::as_str) != Some(&expected_root_path) {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Project root changed before validation started. Reload and retry.",
                ));
            }
            if lifecycle["validation"]["checks"] != expected_checks {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Project validation configuration changed before validation started. Reload and retry.",
                ));
            }
            let runs = lifecycle["validation"]["runs"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "Project validation runs state is invalid.",
                    )
                })?;
            runs.insert(0, running_run);
            runs.truncate(MAX_VALIDATION_RUNS);
            Ok(())
        },
    )
    .await?;

    let check_evidence = execute_validation_checks(&root, &snapshot.checks, &cancellation).await;
    let status = validation_run_status(&check_evidence);
    let run = finalize_validation_run(json!({
        "id": run_id,
        "startedAt": started_at,
        "finishedAt": now_unix_ms(),
        "status": status,
        "rootPath": root.display().to_string(),
        "branch": branch,
        "commit": commit,
        "configurationDigest": snapshot.configuration_digest,
        "checks": check_evidence,
        "operator": auth_operator(auth)
    }))?;

    let run_id_for_update = run_id.clone();
    update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id }),
        move |lifecycle, _params, _project| {
            let runs = lifecycle["validation"]["runs"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "Project validation runs state is invalid.",
                    )
                })?;
            let persisted_run = runs
                .iter_mut()
                .find(|entry| entry.get("id").and_then(Value::as_str) == Some(&run_id_for_update))
                .ok_or_else(|| {
                    api_error(
                        StatusCode::CONFLICT,
                        "Running validation evidence was removed before completion.",
                    )
                })?;
            *persisted_run = run;
            Ok(())
        },
    )
    .await
}

pub(crate) async fn run_legacy_project_validation_payload(
    state: &AppState,
    auth: &AuthContext,
    _params: Value,
) -> ApiResult<Value> {
    require_validation_role(state, auth)?;
    Err(api_error(
        StatusCode::CONFLICT,
        "UPGRADE_REQUIRED: Client-submitted validation evidence is no longer accepted. Refresh or upgrade the client, then run validation again through the project gateway.",
    ))
}

pub(crate) async fn cancel_project_validation_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    require_validation_role(state, auth)?;
    let project_id = require_validation_cancel_params(&params)?;
    let key = active_validation_key(&auth.profile_id, &project_id);
    let active = active_validations()
        .lock()
        .map_err(|_| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project validation executor is unavailable.",
            )
        })?
        .get(&key)
        .cloned()
        .ok_or_else(|| {
            api_error(
                StatusCode::NOT_FOUND,
                "No active project validation run was found.",
            )
        })?;
    active.cancellation.cancel();
    Ok(json!({
        "ok": true,
        "projectId": project_id,
        "runId": active.run_id
    }))
}
