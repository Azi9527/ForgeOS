use super::*;

#[cfg(test)]
#[path = "project_lifecycle_execution_support_tests.rs"]
mod tests;

const MAX_DEPLOYMENT_RECORDS: usize = 50;
const DEPLOYMENT_TIMEOUT: Duration = Duration::from_secs(30 * 60);
const HEALTH_CHECK_TIMEOUT: Duration = Duration::from_secs(5 * 60);

#[derive(Clone, Debug)]
struct OperationSnapshot {
    project_name: String,
    root_path: String,
    lifecycle: Value,
}

struct ActiveOperation {
    id: String,
}

impl ActiveOperation {
    fn begin(id: &str) -> Self {
        if let Ok(mut active) = active_operation_ids().lock() {
            active.insert(id.to_string());
        }
        Self { id: id.to_string() }
    }
}

impl Drop for ActiveOperation {
    fn drop(&mut self) {
        if let Ok(mut active) = active_operation_ids().lock() {
            active.remove(&self.id);
        }
    }
}

fn active_operation_ids() -> &'static std::sync::Mutex<HashSet<String>> {
    static ACTIVE: std::sync::OnceLock<std::sync::Mutex<HashSet<String>>> =
        std::sync::OnceLock::new();
    ACTIVE.get_or_init(|| std::sync::Mutex::new(HashSet::new()))
}

fn operation_is_active(id: &str) -> bool {
    active_operation_ids()
        .lock()
        .is_ok_and(|active| active.contains(id))
}

fn require_operation_role(auth: &AuthContext) -> ApiResult<()> {
    if role_has_admin_access(auth.role) {
        Ok(())
    } else {
        Err(api_error(
            StatusCode::FORBIDDEN,
            "Only an admin or owner can run project operations.",
        ))
    }
}

fn require_local_operation_owner(
    state: &AppState,
    auth: &AuthContext,
    command: &OperationCommand,
) -> ApiResult<()> {
    if !matches!(command, OperationCommand::Local(_))
        || role_has_owner_access(&state.config, auth.role)
    {
        return Ok(());
    }
    Err(api_error(
        StatusCode::FORBIDDEN,
        "Saved local commands require the owner role when dedicated owner access is configured.",
    ))
}

fn require_operation_params(
    params: &Value,
    required_ids: &[&str],
    allowed: &[&str],
) -> ApiResult<(String, u64, Vec<String>)> {
    let object = params
        .as_object()
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "params must be an object"))?;
    if let Some(field) = object.keys().find(|field| {
        !allowed.contains(&field.as_str())
            && !matches!(field.as_str(), "requestProfileId" | "request_profile_id")
    }) {
        return Err(api_error(
            StatusCode::BAD_REQUEST,
            format!("Unsupported project operation parameter: {field}"),
        ));
    }
    let project_id = require_lifecycle_project_id(params)?;
    let expected_revision = params
        .get("expectedRevision")
        .and_then(Value::as_u64)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "expectedRevision is required"))?;
    let ids = required_ids
        .iter()
        .map(|field| {
            params
                .get(*field)
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty() && value.len() <= 100)
                .map(str::to_string)
                .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, format!("{field} is required")))
        })
        .collect::<ApiResult<Vec<_>>>()?;
    Ok((project_id, expected_revision, ids))
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

async fn operation_snapshot(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    expected_revision: u64,
) -> ApiResult<OperationSnapshot> {
    with_ui_state_read(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, project_id)?;
        if project.get("status").and_then(Value::as_str) == Some("archived") {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Archived projects cannot run operations.",
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
        Ok(OperationSnapshot {
            project_name: project_name.to_string(),
            root_path: root_path.to_string(),
            lifecycle,
        })
    })
    .await
}

fn operator_evidence(auth: &AuthContext) -> Value {
    auth_operator(auth)
}

fn finalize_evidence(mut evidence: Value) -> ApiResult<Value> {
    evidence
        .as_object_mut()
        .expect("operation evidence is an object")
        .remove("evidenceDigest");
    let encoded = serde_json::to_vec(&evidence)
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    evidence
        .as_object_mut()
        .expect("operation evidence is an object")
        .insert("evidenceDigest".to_string(), json!(sha256_hex(&encoded)));
    Ok(evidence)
}

fn has_interrupted_operations(lifecycle: &Value) -> bool {
    let deployment_interrupted = lifecycle["operations"]["deployments"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|deployment| {
            deployment.get("status").and_then(Value::as_str) == Some("running")
                && deployment
                    .get("id")
                    .and_then(Value::as_str)
                    .is_none_or(|id| !operation_is_active(id))
        });
    let health_interrupted = lifecycle["operations"]["environments"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|environment| {
            environment.get("health").and_then(Value::as_str) == Some("checking")
                && environment
                    .get("lastHealthCheck")
                    .and_then(|evidence| evidence.get("id"))
                    .and_then(Value::as_str)
                    .is_none_or(|id| !operation_is_active(id))
        });
    deployment_interrupted || health_interrupted
}

pub(crate) async fn recover_interrupted_project_operations(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
) -> ApiResult<()> {
    let previous = with_ui_state_read(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, project_id)?;
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        Ok(lifecycle_from_state(ui_state, project_id, project_name))
    })
    .await?;
    if !has_interrupted_operations(&previous) {
        return Ok(());
    }

    let finished_at = now_unix_ms();
    let updated = update_project_lifecycle(
        state,
        profile_id,
        json!({ "projectId": project_id }),
        move |lifecycle, _params, _project| {
            if let Some(deployments) = lifecycle["operations"]["deployments"].as_array_mut() {
                for deployment in deployments {
                    let interrupted = deployment.get("status").and_then(Value::as_str)
                        == Some("running")
                        && deployment
                            .get("id")
                            .and_then(Value::as_str)
                            .is_none_or(|id| !operation_is_active(id));
                    if interrupted {
                        deployment["status"] = json!("failed");
                        deployment["finishedAt"] = json!(finished_at);
                        deployment["exitCode"] = json!(-1);
                        deployment["logs"] = json!(
                            "Gateway execution was interrupted before completion; the saved result is not a client report."
                        );
                        *deployment = finalize_evidence(deployment.clone())?;
                    }
                }
            }
            if let Some(environments) = lifecycle["operations"]["environments"].as_array_mut() {
                for environment in environments {
                    let interrupted = environment.get("health").and_then(Value::as_str)
                        == Some("checking")
                        && environment
                            .get("lastHealthCheck")
                            .and_then(|evidence| evidence.get("id"))
                            .and_then(Value::as_str)
                            .is_none_or(|id| !operation_is_active(id));
                    if interrupted {
                        let mut evidence = environment
                            .get("lastHealthCheck")
                            .cloned()
                            .unwrap_or_else(|| json!({ "id": format!("health_{}", Uuid::new_v4().simple()) }));
                        evidence["status"] = json!("interrupted");
                        evidence["finishedAt"] = json!(finished_at);
                        evidence["exitCode"] = json!(-1);
                        evidence["logs"] = json!(
                            "Gateway health check was interrupted before completion; the saved result is not a client report."
                        );
                        let evidence = finalize_evidence(evidence)?;
                        environment["health"] = json!("unhealthy");
                        environment["lastCheckedAt"] = json!(finished_at);
                        environment["lastHealthOutput"] = evidence["logs"].clone();
                        environment["lastHealthCheck"] = evidence;
                    }
                }
            }
            Ok(())
        },
    )
    .await?;
    emit_project_deployment_notifications(
        state,
        profile_id,
        project_id,
        previous
            .get("projectName")
            .and_then(Value::as_str)
            .unwrap_or_default(),
        &previous,
        &updated,
    )
    .await;
    let _ = append_audit_log(
        &state.config,
        AuditLogEntry {
            id: Uuid::new_v4().to_string(),
            at: now_unix_ms(),
            role: "system".to_string(),
            method: "projectLifecycle/operations/recover".to_string(),
            target: Some(project_id.to_string()),
            ok: true,
            error: None,
        },
    )
    .await;
    Ok(())
}

pub(crate) async fn run_project_deployment_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    require_operation_role(auth)?;
    let (project_id, expected_revision, ids) = require_operation_params(
        &params,
        &["releaseId", "environmentId"],
        &[
            "projectId",
            "releaseId",
            "environmentId",
            "expectedRevision",
        ],
    )?;
    let release_id = &ids[0];
    let environment_id = &ids[1];
    recover_interrupted_project_operations(state, &auth.profile_id, &project_id).await?;
    let snapshot =
        operation_snapshot(state, &auth.profile_id, &project_id, expected_revision).await?;
    let planned_command = deployment_command(&snapshot.lifecycle, release_id, environment_id)?;
    require_local_operation_owner(state, auth, &planned_command)?;
    let root = validated_project_root(state, &snapshot.root_path).await?;
    let deployment_id = format!("dep_{}", Uuid::new_v4().simple());
    let _active_operation = ActiveOperation::begin(&deployment_id);
    let started_at = now_unix_ms();
    let running = json!({
        "id": deployment_id,
        "releaseId": release_id,
        "environmentId": environment_id,
        "status": "running",
        "startedAt": started_at,
        "finishedAt": Value::Null,
        "exitCode": Value::Null,
        "logs": Value::Null,
        "operator": operator_evidence(auth),
        "adapter": planned_command.adapter(),
        "configurationDigest": planned_command.configuration_digest(),
        "evidenceDigest": Value::Null
    });
    let expected_root_path = snapshot.root_path.clone();
    let command_at_start = planned_command.clone();
    let running_for_start = running.clone();
    let release_id_at_start = release_id.clone();
    let environment_id_at_start = environment_id.clone();
    let started_lifecycle = update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id, "expectedRevision": expected_revision }),
        move |lifecycle, _params, project| {
            if project.get("rootPath").and_then(Value::as_str) != Some(&expected_root_path) {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Project root changed. Reload and retry.",
                ));
            }
            if deployment_command(lifecycle, &release_id_at_start, &environment_id_at_start)?
                != command_at_start
            {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Deployment configuration changed. Reload and retry.",
                ));
            }
            let deployments = lifecycle["operations"]["deployments"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "deployment state is invalid",
                    )
                })?;
            deployments.insert(0, running_for_start);
            deployments.truncate(MAX_DEPLOYMENT_RECORDS);
            Ok(())
        },
    )
    .await?;

    let result = run_operation_command(&root, &planned_command, DEPLOYMENT_TIMEOUT).await;
    let completed = finalize_evidence(json!({
        "id": deployment_id,
        "releaseId": release_id,
        "environmentId": environment_id,
        "status": if result.exit_code == 0 { "succeeded" } else { "failed" },
        "startedAt": started_at,
        "finishedAt": now_unix_ms(),
        "exitCode": result.exit_code,
        "logs": result.logs,
        "operator": operator_evidence(auth),
        "adapter": planned_command.adapter(),
        "configurationDigest": planned_command.configuration_digest()
    }))?;
    let completed_for_update = completed.clone();
    let deployment_id_for_update = deployment_id.clone();
    let updated = update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id }),
        move |lifecycle, _params, _project| {
            let deployments = lifecycle["operations"]["deployments"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "deployment state is invalid",
                    )
                })?;
            let deployment = deployments
                .iter_mut()
                .find(|entry| {
                    entry.get("id").and_then(Value::as_str) == Some(&deployment_id_for_update)
                })
                .ok_or_else(|| {
                    api_error(
                        StatusCode::CONFLICT,
                        "Running deployment evidence was removed.",
                    )
                })?;
            *deployment = completed_for_update;
            Ok(())
        },
    )
    .await?;
    emit_project_deployment_notifications(
        state,
        &auth.profile_id,
        &project_id,
        &snapshot.project_name,
        &started_lifecycle,
        &updated,
    )
    .await;
    Ok(updated)
}

pub(crate) async fn check_project_environment_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    require_operation_role(auth)?;
    let (project_id, expected_revision, ids) = require_operation_params(
        &params,
        &["environmentId"],
        &["projectId", "environmentId", "expectedRevision"],
    )?;
    let environment_id = &ids[0];
    recover_interrupted_project_operations(state, &auth.profile_id, &project_id).await?;
    let snapshot =
        operation_snapshot(state, &auth.profile_id, &project_id, expected_revision).await?;
    let planned_command = health_check_command(&snapshot.lifecycle, environment_id)?;
    require_local_operation_owner(state, auth, &planned_command)?;
    let root = validated_project_root(state, &snapshot.root_path).await?;
    let health_check_id = format!("health_{}", Uuid::new_v4().simple());
    let _active_operation = ActiveOperation::begin(&health_check_id);
    let started_at = now_unix_ms();
    let checking = json!({
        "id": health_check_id,
        "status": "checking",
        "startedAt": started_at,
        "finishedAt": Value::Null,
        "exitCode": Value::Null,
        "logs": Value::Null,
        "operator": operator_evidence(auth),
        "adapter": planned_command.adapter(),
        "configurationDigest": planned_command.configuration_digest(),
        "evidenceDigest": Value::Null
    });
    let expected_root_path = snapshot.root_path.clone();
    let command_at_start = planned_command.clone();
    let environment_id_at_start = environment_id.clone();
    update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id, "expectedRevision": expected_revision }),
        move |lifecycle, _params, project| {
            if project.get("rootPath").and_then(Value::as_str) != Some(&expected_root_path) {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Project root changed. Reload and retry.",
                ));
            }
            if health_check_command(lifecycle, &environment_id_at_start)? != command_at_start {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Health check configuration changed. Reload and retry.",
                ));
            }
            let environment = lifecycle["operations"]["environments"]
                .as_array_mut()
                .and_then(|environments| {
                    environments.iter_mut().find(|environment| {
                        environment.get("id").and_then(Value::as_str)
                            == Some(&environment_id_at_start)
                    })
                })
                .ok_or_else(|| {
                    api_error(StatusCode::CONFLICT, "Project environment was removed.")
                })?;
            environment["health"] = json!("checking");
            environment["lastHealthCheck"] = checking;
            Ok(())
        },
    )
    .await?;

    let result = run_operation_command(&root, &planned_command, HEALTH_CHECK_TIMEOUT).await;
    let finished_at = now_unix_ms();
    let status = if result.exit_code == 0 {
        "healthy"
    } else {
        "unhealthy"
    };
    let logs = result.logs;
    let evidence = finalize_evidence(json!({
        "id": health_check_id,
        "status": status,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "exitCode": result.exit_code,
        "logs": logs,
        "operator": operator_evidence(auth),
        "adapter": planned_command.adapter(),
        "configurationDigest": planned_command.configuration_digest()
    }))?;
    let evidence_for_update = evidence.clone();
    let environment_id_for_update = environment_id.clone();
    update_project_lifecycle(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id }),
        move |lifecycle, _params, _project| {
            let environment = lifecycle["operations"]["environments"]
                .as_array_mut()
                .and_then(|environments| {
                    environments.iter_mut().find(|environment| {
                        environment.get("id").and_then(Value::as_str)
                            == Some(&environment_id_for_update)
                    })
                })
                .ok_or_else(|| {
                    api_error(StatusCode::CONFLICT, "Project environment was removed.")
                })?;
            environment["health"] = json!(status);
            environment["lastCheckedAt"] = json!(finished_at);
            environment["lastHealthOutput"] = json!(logs);
            environment["lastHealthCheck"] = evidence_for_update;
            Ok(())
        },
    )
    .await
}
