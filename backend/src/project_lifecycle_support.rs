use super::*;
use sha2::Digest as _;

#[cfg(test)]
#[path = "project_lifecycle_support_tests.rs"]
mod tests;

const MAX_VALIDATION_CHECKS: usize = 12;
const MAX_VALIDATION_RUNS: usize = 20;
const MAX_ARTIFACTS: usize = 50;
const MAX_RELEASES: usize = 30;
const MAX_ENVIRONMENTS: usize = 20;
const MAX_DEPLOYMENTS: usize = 50;
const MAX_EVIDENCE_OUTPUT_BYTES: usize = 12_000;

fn lifecycle_default(project_name: &str) -> Value {
    json!({
        "projectName": project_name,
        "revision": 0,
        "updatedAt": Value::Null,
        "validation": { "checks": [], "runs": [] },
        "release": { "artifacts": [], "releases": [] },
        "operations": { "environments": [], "deployments": [] }
    })
}

fn require_project_name(params: &Value) -> ApiResult<String> {
    params
        .get("projectName")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "projectName is required"))
}

fn bounded_string(value: Option<&Value>, max_bytes: usize) -> String {
    let value = value.and_then(Value::as_str).unwrap_or_default().trim();
    value.chars().take(max_bytes).collect()
}

fn optional_bounded_string(value: Option<&Value>, max_bytes: usize) -> Value {
    let value = bounded_string(value, max_bytes);
    if value.is_empty() {
        Value::Null
    } else {
        Value::String(value)
    }
}

fn normalized_validation_check(value: &Value) -> Option<Value> {
    let id = bounded_string(value.get("id"), 80);
    let label = bounded_string(value.get("label"), 120);
    let command = bounded_string(value.get("command"), 4_096);
    if id.is_empty() || label.is_empty() {
        return None;
    }
    Some(json!({
        "id": id,
        "label": label,
        "command": command,
        "required": value.get("required").and_then(Value::as_bool).unwrap_or(true)
    }))
}

fn normalized_validation_checks(value: Option<&Value>) -> Vec<Value> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(normalized_validation_check)
        .take(MAX_VALIDATION_CHECKS)
        .collect()
}

fn normalized_validation_evidence(value: &Value) -> Option<Value> {
    let check = normalized_validation_check(value)?;
    let status = match value.get("status").and_then(Value::as_str) {
        Some("running") => "running",
        Some("passed") => "passed",
        Some("failed") => "failed",
        Some("cancelled") => "cancelled",
        _ => "pending",
    };
    let mut check = check.as_object().cloned().unwrap_or_default();
    check.insert("status".to_string(), json!(status));
    check.insert(
        "exitCode".to_string(),
        value.get("exitCode").cloned().unwrap_or(Value::Null),
    );
    check.insert(
        "durationMs".to_string(),
        value.get("durationMs").cloned().unwrap_or(Value::Null),
    );
    check.insert(
        "output".to_string(),
        json!(bounded_string(
            value.get("output"),
            MAX_EVIDENCE_OUTPUT_BYTES
        )),
    );
    Some(Value::Object(check))
}

fn normalized_validation_run(value: &Value, auth: &AuthContext) -> ApiResult<Value> {
    let id = bounded_string(value.get("id"), 100);
    if id.is_empty() {
        return Err(api_error(
            StatusCode::BAD_REQUEST,
            "validation run id is required",
        ));
    }
    let status = match value.get("status").and_then(Value::as_str) {
        Some("passed") => "passed",
        Some("failed") => "failed",
        Some("cancelled") => "cancelled",
        _ => "running",
    };
    let checks = value
        .get("checks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(normalized_validation_evidence)
        .take(MAX_VALIDATION_CHECKS)
        .collect::<Vec<_>>();
    let role = match auth.role {
        UserRole::Owner => "owner",
        UserRole::Admin => "admin",
        UserRole::Viewer => "viewer",
    };
    let mut run = json!({
        "id": id,
        "startedAt": value.get("startedAt").and_then(Value::as_u64).unwrap_or_else(now_unix_ms),
        "finishedAt": value.get("finishedAt").cloned().unwrap_or(Value::Null),
        "status": status,
        "rootPath": optional_bounded_string(value.get("rootPath"), 2_048),
        "branch": optional_bounded_string(value.get("branch"), 256),
        "commit": optional_bounded_string(value.get("commit"), 128),
        "checks": checks,
        "operator": { "profileId": auth.profile_id, "role": role }
    });
    let digest_input = serde_json::to_vec(&run)
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let digest = Sha256::digest(digest_input)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    run.as_object_mut()
        .expect("validation run is an object")
        .insert("evidenceDigest".to_string(), json!(digest));
    Ok(run)
}

fn auth_operator(auth: &AuthContext) -> Value {
    let role = match auth.role {
        UserRole::Owner => "owner",
        UserRole::Admin => "admin",
        UserRole::Viewer => "viewer",
    };
    json!({ "profileId": auth.profile_id, "role": role })
}

fn normalized_artifact(
    value: &Value,
    auth: &AuthContext,
    existing: Option<&Value>,
    signature_verified: bool,
) -> Option<Value> {
    let id = bounded_string(value.get("id"), 100);
    let name = bounded_string(value.get("name"), 180);
    let version = bounded_string(value.get("version"), 80);
    if id.is_empty() || name.is_empty() || version.is_empty() {
        return None;
    }
    let status = match value.get("status").and_then(Value::as_str) {
        Some("ready") => "ready",
        Some("retired") => "retired",
        _ => "draft",
    };
    Some(json!({
        "id": id,
        "name": name,
        "version": version,
        "sourceCommit": optional_bounded_string(value.get("sourceCommit"), 128),
        "sha256": optional_bounded_string(value.get("sha256"), 128),
        "size": value.get("size").and_then(Value::as_u64).map_or(Value::Null, |size| json!(size)),
        "signature": optional_bounded_string(value.get("signature"), 256),
        "signatureAlgorithm": optional_bounded_string(value.get("signatureAlgorithm"), 64),
        "signatureVerified": signature_verified,
        "status": status,
        "createdAt": value.get("createdAt").and_then(Value::as_u64).unwrap_or_else(now_unix_ms),
        "createdBy": existing.and_then(|entry| entry.get("createdBy")).filter(|value| !value.is_null()).cloned().unwrap_or_else(|| auth_operator(auth))
    }))
}

fn normalized_release(
    value: &Value,
    auth: &AuthContext,
    existing: Option<&Value>,
) -> Option<Value> {
    let id = bounded_string(value.get("id"), 100);
    let version = bounded_string(value.get("version"), 80);
    if id.is_empty() || version.is_empty() {
        return None;
    }
    let status = match value.get("status").and_then(Value::as_str) {
        Some("awaitingApproval") => "awaitingApproval",
        Some("approved") => "approved",
        Some("released") => "released",
        Some("rolledBack") => "rolledBack",
        _ => "draft",
    };
    let artifact_ids = value
        .get("artifactIds")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .take(20)
        .map(str::to_string)
        .collect::<Vec<_>>();
    let incoming_approvals = value
        .get("approvals")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .take(20)
        .collect::<Vec<_>>();
    let mut approvals = existing
        .and_then(|entry| entry.get("approvals"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for approval in incoming_approvals.iter().skip(approvals.len()) {
        let operator = auth_operator(auth);
        let profile_id = bounded_string(operator.get("profileId"), 100);
        if !approvals.iter().any(|entry| {
            entry.get("profileId").and_then(Value::as_str) == Some(profile_id.as_str())
        }) {
            approvals.push(json!({
                "profileId": profile_id,
                "role": bounded_string(operator.get("role"), 40),
                "approvedAt": approval.get("approvedAt").and_then(Value::as_u64).unwrap_or_else(now_unix_ms)
            }));
        }
    }
    approvals.truncate(20);
    Some(json!({
        "id": id,
        "version": version,
        "artifactIds": artifact_ids,
        "status": status,
        "targetEnvironmentId": optional_bounded_string(value.get("targetEnvironmentId"), 100),
        "approvals": approvals,
        "createdAt": value.get("createdAt").and_then(Value::as_u64).unwrap_or_else(now_unix_ms),
        "releasedAt": value.get("releasedAt").cloned().unwrap_or(Value::Null),
        "rollbackOf": optional_bounded_string(value.get("rollbackOf"), 100)
    }))
}

fn validate_release_transition(value: &Value, existing: Option<&Value>) -> ApiResult<()> {
    let next_status = value
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("draft");
    let current_status = existing
        .and_then(|entry| entry.get("status"))
        .and_then(Value::as_str);
    let current_approvals = existing
        .and_then(|entry| entry.get("approvals"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let next_approvals = value
        .get("approvals")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let allowed = match current_status {
        None => matches!(next_status, "draft" | "awaitingApproval"),
        Some(current) if current == next_status => true,
        Some("draft") => next_status == "awaitingApproval",
        Some("awaitingApproval") => next_status == "approved" && next_approvals > current_approvals,
        Some("approved") => next_status == "released" && current_approvals > 0,
        Some("released") => next_status == "rolledBack",
        Some(_) => false,
    };
    if !allowed {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Invalid release state transition.",
        ));
    }
    Ok(())
}

fn validate_release_policy(lifecycle: &Value, release: &Value) -> ApiResult<()> {
    if release.get("status").and_then(Value::as_str) != Some("released") {
        return Ok(());
    }
    let approvals = release
        .get("approvals")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let target_id = release.get("targetEnvironmentId").and_then(Value::as_str);
    let production = target_id.is_some_and(|target_id| {
        lifecycle["operations"]["environments"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|environment| {
                environment.get("id").and_then(Value::as_str) == Some(target_id)
                    && environment.get("kind").and_then(Value::as_str) == Some("production")
            })
    });
    let distinct_approvers = approvals
        .iter()
        .filter_map(|approval| approval.get("profileId").and_then(Value::as_str))
        .collect::<HashSet<_>>()
        .len();
    let owner_approved = approvals
        .iter()
        .any(|approval| approval.get("role").and_then(Value::as_str) == Some("owner"));
    if production && (distinct_approvers < 2 || !owner_approved) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Production release requires two distinct approvers including an owner.",
        ));
    }
    if production {
        let artifact_ids = release
            .get("artifactIds")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        let artifacts = lifecycle["release"]["artifacts"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let all_artifacts_verified = !artifact_ids.is_empty()
            && artifact_ids.iter().all(|artifact_id| {
                artifacts.iter().any(|artifact| {
                    artifact.get("id").and_then(Value::as_str) == Some(*artifact_id)
                        && artifact
                            .get("signatureVerified")
                            .and_then(Value::as_bool)
                            .unwrap_or(false)
                })
            });
        if !all_artifacts_verified {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Production release requires server-verified signed artifacts.",
            ));
        }
    }
    if !production && distinct_approvers < 1 {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Release requires at least one approver.",
        ));
    }
    Ok(())
}

fn normalized_environment(value: &Value) -> Option<Value> {
    let id = bounded_string(value.get("id"), 100);
    let name = bounded_string(value.get("name"), 120);
    if id.is_empty() || name.is_empty() {
        return None;
    }
    let kind = match value.get("kind").and_then(Value::as_str) {
        Some("test") => "test",
        Some("staging") => "staging",
        Some("production") => "production",
        _ => "development",
    };
    let health = match value.get("health").and_then(Value::as_str) {
        Some("healthy") => "healthy",
        Some("unhealthy") => "unhealthy",
        Some("checking") => "checking",
        _ => "unknown",
    };
    Some(json!({
        "id": id,
        "name": name,
        "kind": kind,
        "url": optional_bounded_string(value.get("url"), 2_048),
        "deployCommand": optional_bounded_string(value.get("deployCommand"), 4_096),
        "adapter": match value.get("adapter").and_then(Value::as_str) {
            Some("githubActions") => "githubActions",
            _ => "localCommand"
        },
        "githubRepository": optional_bounded_string(value.get("githubRepository"), 300),
        "githubWorkflow": optional_bounded_string(value.get("githubWorkflow"), 300),
        "githubRef": optional_bounded_string(value.get("githubRef"), 200),
        "healthCommand": optional_bounded_string(value.get("healthCommand"), 4_096),
        "health": health,
        "lastCheckedAt": value.get("lastCheckedAt").cloned().unwrap_or(Value::Null),
        "lastHealthOutput": optional_bounded_string(
            value.get("lastHealthOutput"),
            MAX_EVIDENCE_OUTPUT_BYTES
        )
    }))
}

fn normalized_deployment(
    value: &Value,
    auth: &AuthContext,
    existing: Option<&Value>,
) -> Option<Value> {
    let id = bounded_string(value.get("id"), 100);
    let release_id = bounded_string(value.get("releaseId"), 100);
    let environment_id = bounded_string(value.get("environmentId"), 100);
    if id.is_empty() || release_id.is_empty() || environment_id.is_empty() {
        return None;
    }
    let status = match value.get("status").and_then(Value::as_str) {
        Some("running") => "running",
        Some("succeeded") => "succeeded",
        Some("failed") => "failed",
        Some("rolledBack") => "rolledBack",
        _ => "queued",
    };
    Some(json!({
        "id": id,
        "releaseId": release_id,
        "environmentId": environment_id,
        "status": status,
        "startedAt": value.get("startedAt").and_then(Value::as_u64).unwrap_or_else(now_unix_ms),
        "finishedAt": value.get("finishedAt").cloned().unwrap_or(Value::Null),
        "exitCode": value.get("exitCode").cloned().unwrap_or(Value::Null),
        "logs": optional_bounded_string(value.get("logs"), MAX_EVIDENCE_OUTPUT_BYTES),
        "operator": existing.and_then(|entry| entry.get("operator")).filter(|value| !value.is_null()).cloned().unwrap_or_else(|| auth_operator(auth))
    }))
}

fn project_exists(ui_state: &Value, project_name: &str) -> bool {
    ui_state
        .get("sessionFoldersByName")
        .and_then(Value::as_object)
        .is_some_and(|folders| folders.contains_key(project_name))
}

fn lifecycle_revision(value: &Value) -> u64 {
    value.get("revision").and_then(Value::as_u64).unwrap_or(0)
}

fn require_matching_revision(current: &Value, params: &Value) -> ApiResult<()> {
    if let Some(expected) = params.get("revision").and_then(Value::as_u64)
        && expected != lifecycle_revision(current)
    {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Project lifecycle state changed. Reload and retry.",
        ));
    }
    Ok(())
}

fn lifecycle_from_state(ui_state: &Value, project_name: &str) -> Value {
    ui_state
        .get("projectLifecycleByName")
        .and_then(Value::as_object)
        .and_then(|entries| entries.get(project_name))
        .cloned()
        .unwrap_or_else(|| lifecycle_default(project_name))
}

pub(crate) async fn get_project_lifecycle_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_name = require_project_name(&params)?;
    with_ui_state_read(state, profile_id, |ui_state| {
        if !project_exists(ui_state, &project_name) {
            return Err(api_error(StatusCode::NOT_FOUND, "Project was not found."));
        }
        Ok(lifecycle_from_state(ui_state, &project_name))
    })
    .await
}

async fn update_project_lifecycle<F>(
    state: &AppState,
    profile_id: &str,
    params: Value,
    update: F,
) -> ApiResult<Value>
where
    F: FnOnce(&mut Value, &Value) -> ApiResult<()>,
{
    let project_name = require_project_name(&params)?;
    with_ui_state_write(state, profile_id, |ui_state| {
        if !project_exists(ui_state, &project_name) {
            return Err(api_error(StatusCode::NOT_FOUND, "Project was not found."));
        }
        let mut lifecycle = lifecycle_from_state(ui_state, &project_name);
        require_matching_revision(&lifecycle, &params)?;
        update(&mut lifecycle, &params)?;
        let revision = lifecycle_revision(&lifecycle).saturating_add(1);
        let lifecycle_object = lifecycle.as_object_mut().ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "project lifecycle is invalid",
            )
        })?;
        lifecycle_object.insert("revision".to_string(), json!(revision));
        lifecycle_object.insert("updatedAt".to_string(), json!(now_unix_ms()));
        ui_state
            .get_mut("projectLifecycleByName")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "project lifecycle state is missing",
                )
            })?
            .insert(project_name, lifecycle.clone());
        Ok(lifecycle)
    })
    .await
}

pub(crate) async fn save_project_validation_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    update_project_lifecycle(state, profile_id, params, |lifecycle, params| {
        let checks = normalized_validation_checks(params.get("checks"));
        lifecycle["validation"]["checks"] = json!(checks);
        Ok(())
    })
    .await
}

pub(crate) async fn record_project_validation_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    let run = normalized_validation_run(
        params
            .get("run")
            .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "validation run is required"))?,
        auth,
    )?;
    update_project_lifecycle(
        state,
        &auth.profile_id,
        params,
        move |lifecycle, _params| {
            let runs = lifecycle["validation"]["runs"]
                .as_array_mut()
                .ok_or_else(|| {
                    api_error(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "validation runs state is invalid",
                    )
                })?;
            runs.retain(|entry| entry.get("id") != run.get("id"));
            runs.insert(0, run);
            runs.truncate(MAX_VALIDATION_RUNS);
            Ok(())
        },
    )
    .await
}

pub(crate) async fn save_project_release_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    let project_name = require_project_name(&params)?;
    let signing_key = artifact_signing_key(state, &auth.profile_id).await?;
    update_project_lifecycle(state, &auth.profile_id, params, move |lifecycle, params| {
        let current_artifacts = lifecycle["release"]["artifacts"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let current_releases = lifecycle["release"]["releases"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        for value in params
            .get("releases")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let existing = current_releases
                .iter()
                .find(|entry| entry.get("id") == value.get("id"));
            validate_release_transition(value, existing)?;
        }
        let artifacts = params
            .get("artifacts")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|value| {
                let existing = current_artifacts
                    .iter()
                    .find(|entry| entry.get("id") == value.get("id"));
                let signature_verified =
                    artifact_manifest_signature_is_valid(&signing_key, &project_name, value);
                normalized_artifact(value, auth, existing, signature_verified)
            })
            .take(MAX_ARTIFACTS)
            .collect::<Vec<_>>();
        let releases = params
            .get("releases")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|value| {
                let existing = current_releases
                    .iter()
                    .find(|entry| entry.get("id") == value.get("id"));
                normalized_release(value, auth, existing)
            })
            .take(MAX_RELEASES)
            .collect::<Vec<_>>();
        for release in &releases {
            validate_release_policy(lifecycle, release)?;
        }
        lifecycle["release"] = json!({
            "artifacts": artifacts,
            "releases": releases
        });
        Ok(())
    })
    .await
}

pub(crate) async fn save_project_operations_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    update_project_lifecycle(state, &auth.profile_id, params, |lifecycle, params| {
        let current_deployments = lifecycle["operations"]["deployments"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let environments = params
            .get("environments")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(normalized_environment)
            .take(MAX_ENVIRONMENTS)
            .collect::<Vec<_>>();
        let deployments = params
            .get("deployments")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|value| {
                let existing = current_deployments
                    .iter()
                    .find(|entry| entry.get("id") == value.get("id"));
                normalized_deployment(value, auth, existing)
            })
            .take(MAX_DEPLOYMENTS)
            .collect::<Vec<_>>();
        lifecycle["operations"] = json!({
            "environments": environments,
            "deployments": deployments
        });
        Ok(())
    })
    .await
}

pub(crate) async fn list_project_audit_payload(
    state: &AppState,
    params: Value,
) -> ApiResult<Value> {
    let project_name = require_project_name(&params)?;
    let limit = params
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(100)
        .clamp(1, 200) as usize;
    let payload = list_audit_log(&state.config, 500)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let entries = payload
        .get("entries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|entry| entry.get("target").and_then(Value::as_str) == Some(project_name.as_str()))
        .take(limit)
        .cloned()
        .collect::<Vec<_>>();
    Ok(json!({ "entries": entries }))
}
