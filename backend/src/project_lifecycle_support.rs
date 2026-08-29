use super::*;
#[cfg(test)]
#[path = "project_lifecycle_support_tests.rs"]
mod tests;

const MAX_VALIDATION_CHECKS: usize = 12;
const MAX_ARTIFACTS: usize = 50;
const MAX_RELEASES: usize = 30;
const MAX_ENVIRONMENTS: usize = 20;

fn default_project_governance() -> Value {
    json!({
        "approvalPolicy": {
            "standardApprovals": 1,
            "productionApprovals": 2
        },
        "artifactRetention": {
            "maxArtifacts": 50,
            "maxAgeDays": 180
        },
        "notificationRoutes": {
            "approvalRequested": true,
            "releaseCompleted": true,
            "rollbackCompleted": true,
            "deploymentFailed": true
        }
    })
}

pub(crate) fn lifecycle_default(project_id: &str, project_name: &str) -> Value {
    json!({
        "projectId": project_id,
        "projectName": project_name,
        "revision": 0,
        "updatedAt": Value::Null,
        "validation": { "checks": [], "runs": [] },
        "release": { "artifacts": [], "releases": [] },
        "operations": { "environments": [], "deployments": [] },
        "governance": default_project_governance()
    })
}

fn normalized_project_governance(value: Option<&Value>) -> Value {
    let approval = value.and_then(|entry| entry.get("approvalPolicy"));
    let retention = value.and_then(|entry| entry.get("artifactRetention"));
    let routes = value.and_then(|entry| entry.get("notificationRoutes"));
    json!({
        "approvalPolicy": {
            "standardApprovals": approval.and_then(|entry| entry.get("standardApprovals")).and_then(Value::as_u64).unwrap_or(1).clamp(1, 5),
            "productionApprovals": approval.and_then(|entry| entry.get("productionApprovals")).and_then(Value::as_u64).unwrap_or(2).clamp(2, 5)
        },
        "artifactRetention": {
            "maxArtifacts": retention.and_then(|entry| entry.get("maxArtifacts")).and_then(Value::as_u64).unwrap_or(50).clamp(1, MAX_ARTIFACTS as u64),
            "maxAgeDays": retention.and_then(|entry| entry.get("maxAgeDays")).and_then(Value::as_u64).unwrap_or(180).clamp(1, 3_650)
        },
        "notificationRoutes": {
            "approvalRequested": routes.and_then(|entry| entry.get("approvalRequested")).and_then(Value::as_bool).unwrap_or(true),
            "releaseCompleted": routes.and_then(|entry| entry.get("releaseCompleted")).and_then(Value::as_bool).unwrap_or(true),
            "rollbackCompleted": routes.and_then(|entry| entry.get("rollbackCompleted")).and_then(Value::as_bool).unwrap_or(true),
            "deploymentFailed": routes.and_then(|entry| entry.get("deploymentFailed")).and_then(Value::as_bool).unwrap_or(true)
        }
    })
}

fn governance_u64(lifecycle: &Value, section: &str, field: &str, fallback: u64) -> u64 {
    lifecycle
        .get("governance")
        .and_then(|value| value.get(section))
        .and_then(|value| value.get(field))
        .and_then(Value::as_u64)
        .unwrap_or(fallback)
}

pub(crate) fn require_lifecycle_project_id(params: &Value) -> ApiResult<String> {
    params
        .get("projectId")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| value.starts_with("prj_") && value.len() > 4)
        .map(str::to_string)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "projectId is required"))
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

pub(crate) fn auth_operator(auth: &AuthContext) -> Value {
    let role = match auth.role {
        UserRole::Owner => "owner",
        UserRole::Admin => "admin",
        UserRole::Viewer => "viewer",
    };
    json!({ "profileId": auth.profile_id, "role": role })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerApprovalPolicy {
    AdminEquivalent,
    DedicatedOwner,
}

fn owner_approval_policy(config: &Config) -> OwnerApprovalPolicy {
    if role_has_owner_access(config, UserRole::Admin) {
        OwnerApprovalPolicy::AdminEquivalent
    } else {
        OwnerApprovalPolicy::DedicatedOwner
    }
}

fn approval_satisfies_owner_policy(approval: &Value, policy: OwnerApprovalPolicy) -> bool {
    match approval.get("role").and_then(Value::as_str) {
        Some("owner") => true,
        Some("admin") => policy == OwnerApprovalPolicy::AdminEquivalent,
        Some(_) | None => false,
    }
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
        let role = bounded_string(operator.get("role"), 40);
        if !approvals.iter().any(|entry| {
            entry.get("profileId").and_then(Value::as_str) == Some(profile_id.as_str())
                && entry.get("role").and_then(Value::as_str) == Some(role.as_str())
        }) {
            approvals.push(json!({
                "profileId": profile_id,
                "role": role,
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

fn release_target_environment<'a>(lifecycle: &'a Value, release: &Value) -> Option<&'a Value> {
    let target_id = release
        .get("targetEnvironmentId")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())?;
    lifecycle["operations"]["environments"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|environment| environment.get("id").and_then(Value::as_str) == Some(target_id))
}

fn validate_release_environment_binding(lifecycle: &Value, release: &Value) -> ApiResult<()> {
    if !matches!(
        release.get("status").and_then(Value::as_str),
        Some("awaitingApproval" | "approved" | "released")
    ) {
        return Ok(());
    }
    if release_target_environment(lifecycle, release).is_none() {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Release approval and publication require an existing target environment.",
        ));
    }
    Ok(())
}

fn legacy_targetless_release_is_unchanged(current: &Value, release: &Value) -> bool {
    let release_id = release.get("id").and_then(Value::as_str);
    let targetless = release
        .get("targetEnvironmentId")
        .and_then(Value::as_str)
        .map(str::trim)
        .is_none_or(str::is_empty);
    targetless
        && current["release"]["releases"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|existing| existing.get("id").and_then(Value::as_str) == release_id)
            .is_some_and(|existing| existing == release)
}

fn validate_release_environment_upgrade(
    current: &Value,
    proposed: &Value,
    release: &Value,
) -> ApiResult<()> {
    match validate_release_environment_binding(proposed, release) {
        Ok(()) => Ok(()),
        Err(_) if legacy_targetless_release_is_unchanged(current, release) => Ok(()),
        Err(error) => Err(error),
    }
}

fn validate_release_policy(
    lifecycle: &Value,
    release: &Value,
    owner_policy: OwnerApprovalPolicy,
) -> ApiResult<()> {
    if release.get("status").and_then(Value::as_str) != Some("released") {
        return Ok(());
    }
    validate_release_environment_binding(lifecycle, release)?;
    let approvals = release
        .get("approvals")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let production = release_target_environment(lifecycle, release)
        .and_then(|environment| environment.get("kind"))
        .and_then(Value::as_str)
        == Some("production");
    let distinct_approvers = approvals
        .iter()
        .filter_map(|approval| {
            Some((
                approval.get("profileId").and_then(Value::as_str)?,
                approval.get("role").and_then(Value::as_str)?,
            ))
        })
        .collect::<HashSet<_>>()
        .len();
    let owner_approved = approvals
        .iter()
        .any(|approval| approval_satisfies_owner_policy(approval, owner_policy));
    let required_approvals = governance_u64(
        lifecycle,
        "approvalPolicy",
        if production {
            "productionApprovals"
        } else {
            "standardApprovals"
        },
        if production { 2 } else { 1 },
    ) as usize;
    if production && (distinct_approvers < required_approvals || !owner_approved) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Production release does not satisfy the configured approval policy.",
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
    if !production && distinct_approvers < required_approvals {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Release does not satisfy the configured approval policy.",
        ));
    }
    Ok(())
}

fn validate_published_release_history(current: &Value, proposed: &Value) -> ApiResult<()> {
    let current_releases = current["release"]["releases"]
        .as_array()
        .into_iter()
        .flatten();
    let proposed_releases = proposed["release"]["releases"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let proposed_artifacts = proposed["release"]["artifacts"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    const IMMUTABLE_FIELDS: [&str; 7] = [
        "version",
        "artifactIds",
        "targetEnvironmentId",
        "rollbackOf",
        "createdAt",
        "releasedAt",
        "id",
    ];

    for existing in current_releases.filter(|release| {
        matches!(
            release.get("status").and_then(Value::as_str),
            Some("released" | "rolledBack")
        )
    }) {
        let release_id = existing
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let next = proposed_releases
            .iter()
            .find(|release| release.get("id").and_then(Value::as_str) == Some(release_id))
            .ok_or_else(|| {
                api_error(
                    StatusCode::CONFLICT,
                    "Published release history cannot be removed.",
                )
            })?;
        if IMMUTABLE_FIELDS
            .iter()
            .any(|field| existing.get(*field) != next.get(*field))
        {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Published release identity, artifacts, target, and timestamps are immutable.",
            ));
        }
    }

    for release in proposed_releases.iter().filter(|release| {
        matches!(
            release.get("status").and_then(Value::as_str),
            Some("released" | "rolledBack")
        )
    }) {
        for artifact_id in release
            .get("artifactIds")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
        {
            if !proposed_artifacts
                .iter()
                .any(|artifact| artifact.get("id").and_then(Value::as_str) == Some(artifact_id))
            {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Published release artifacts cannot be removed.",
                ));
            }
        }
    }
    Ok(())
}

fn artifact_retention_status(lifecycle: &Value) -> Value {
    let releases = lifecycle["release"]["releases"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let protected_ids = releases
        .iter()
        .filter(|release| {
            matches!(
                release.get("status").and_then(Value::as_str),
                Some("released" | "rolledBack")
            )
        })
        .flat_map(|release| {
            release
                .get("artifactIds")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
        })
        .collect::<HashSet<_>>();
    let max_artifacts = governance_u64(
        lifecycle,
        "artifactRetention",
        "maxArtifacts",
        MAX_ARTIFACTS as u64,
    ) as usize;
    let max_age_ms = governance_u64(lifecycle, "artifactRetention", "maxAgeDays", 180)
        .saturating_mul(24 * 60 * 60 * 1_000);
    let cutoff = now_unix_ms().saturating_sub(max_age_ms);
    let artifacts = lifecycle["release"]["artifacts"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let mut active_count = 0;
    let mut eligible_ids = Vec::new();
    for artifact in artifacts {
        let artifact_id = artifact
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let protected = protected_ids.contains(artifact_id);
        let fresh = artifact
            .get("createdAt")
            .and_then(Value::as_u64)
            .is_none_or(|created_at| created_at >= cutoff);
        if protected {
            continue;
        }
        if fresh && active_count < max_artifacts {
            active_count += 1;
        } else if !artifact_id.is_empty() {
            eligible_ids.push(artifact_id.to_string());
        }
    }
    json!({
        "eligibleForArchive": eligible_ids,
        "protectedCount": protected_ids.len(),
        "automaticDeletion": false
    })
}

fn normalized_environment(value: &Value, existing: Option<&Value>) -> Option<Value> {
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
    let health_command = optional_bounded_string(value.get("healthCommand"), 4_096);
    let health_config_unchanged = existing
        .and_then(|entry| entry.get("healthCommand"))
        .is_some_and(|current| current == &health_command);
    let health = if health_config_unchanged {
        existing
            .and_then(|entry| entry.get("health"))
            .and_then(Value::as_str)
            .filter(|status| matches!(*status, "healthy" | "unhealthy" | "checking"))
            .unwrap_or("unknown")
    } else {
        "unknown"
    };
    let last_checked_at = existing
        .and_then(|entry| entry.get("lastCheckedAt"))
        .cloned()
        .unwrap_or(Value::Null);
    let last_health_output = existing
        .and_then(|entry| entry.get("lastHealthOutput"))
        .cloned()
        .unwrap_or(Value::Null);
    let last_health_check = existing
        .and_then(|entry| entry.get("lastHealthCheck"))
        .cloned()
        .unwrap_or(Value::Null);
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
        "healthCommand": health_command,
        "health": health,
        "lastCheckedAt": last_checked_at,
        "lastHealthOutput": last_health_output,
        "lastHealthCheck": last_health_check
    }))
}

fn validate_deployment_release_binding(
    lifecycle: &Value,
    deployment: &Value,
    existing: Option<&Value>,
) -> ApiResult<()> {
    if let Some(existing) = existing {
        let binding_changed = existing.get("releaseId") != deployment.get("releaseId")
            || existing.get("environmentId") != deployment.get("environmentId");
        if binding_changed {
            return Err(api_error(
                StatusCode::CONFLICT,
                "A deployment release and environment binding cannot be changed.",
            ));
        }
        if existing == deployment {
            return Ok(());
        }
    }

    let release_id = deployment
        .get("releaseId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let environment_id = deployment
        .get("environmentId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let environment_exists = lifecycle["operations"]["environments"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|environment| environment.get("id").and_then(Value::as_str) == Some(environment_id));
    if !environment_exists {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Deployment requires an existing environment.",
        ));
    }
    let release = lifecycle["release"]["releases"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|release| release.get("id").and_then(Value::as_str) == Some(release_id))
        .ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "Deployment requires an existing released release.",
            )
        })?;
    if release.get("targetEnvironmentId").and_then(Value::as_str) != Some(environment_id) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Deployment environment must match the release target environment.",
        ));
    }
    let release_status = release.get("status").and_then(Value::as_str);
    let records_completed_rollback = existing.is_some()
        && deployment.get("status").and_then(Value::as_str) == Some("rolledBack")
        && release_status == Some("rolledBack");
    if release_status != Some("released") && !records_completed_rollback {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Deployment requires a released release.",
        ));
    }
    Ok(())
}

pub(crate) fn lifecycle_project_record(ui_state: &Value, project_id: &str) -> ApiResult<Value> {
    project_record(ui_state, project_id)
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))
}

fn lifecycle_revision(value: &Value) -> u64 {
    value.get("revision").and_then(Value::as_u64).unwrap_or(0)
}

fn require_matching_revision(current: &Value, params: &Value) -> ApiResult<()> {
    if let Some(expected) = params
        .get("expectedRevision")
        .or_else(|| params.get("revision"))
        .and_then(Value::as_u64)
        && expected != lifecycle_revision(current)
    {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Project lifecycle state changed. Reload and retry.",
        ));
    }
    Ok(())
}

pub(crate) fn lifecycle_from_state(
    ui_state: &Value,
    project_id: &str,
    project_name: &str,
) -> Value {
    let mut lifecycle = ui_state
        .get("projectLifecycleById")
        .and_then(Value::as_object)
        .and_then(|entries| entries.get(project_id))
        .cloned()
        .unwrap_or_else(|| lifecycle_default(project_id, project_name));
    lifecycle["projectId"] = json!(project_id);
    lifecycle["projectName"] = json!(project_name);
    lifecycle["governance"] = normalized_project_governance(lifecycle.get("governance"));
    lifecycle["retentionStatus"] = artifact_retention_status(&lifecycle);
    lifecycle
}

pub(crate) async fn get_project_lifecycle_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    recover_interrupted_project_operations(state, profile_id, &project_id).await?;
    recover_interrupted_project_validations(state, profile_id, &project_id).await?;
    with_ui_state_read(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, &project_id)?;
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        Ok(lifecycle_from_state(ui_state, &project_id, project_name))
    })
    .await
}

fn redact_lifecycle_operator(value: &mut Value) {
    if let Some(operator) = value.as_object_mut()
        && operator.contains_key("profileId")
    {
        operator.insert("profileId".to_string(), json!("redacted"));
    }
}

pub(crate) fn redact_project_lifecycle_for_viewer(lifecycle: &mut Value) {
    for check in lifecycle["validation"]["checks"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        check["command"] = json!("");
    }
    for run in lifecycle["validation"]["runs"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        redact_lifecycle_operator(&mut run["operator"]);
        for check in run["checks"].as_array_mut().into_iter().flatten() {
            check["command"] = json!("");
            check["output"] = json!("");
        }
    }
    for artifact in lifecycle["release"]["artifacts"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        redact_lifecycle_operator(&mut artifact["createdBy"]);
    }
    for release in lifecycle["release"]["releases"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        for approval in release["approvals"].as_array_mut().into_iter().flatten() {
            redact_lifecycle_operator(approval);
        }
    }
    for environment in lifecycle["operations"]["environments"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        environment["deployCommand"] = Value::Null;
        environment["healthCommand"] = Value::Null;
        environment["lastHealthOutput"] = Value::Null;
        if let Some(evidence) = environment.get_mut("lastHealthCheck")
            && !evidence.is_null()
        {
            evidence["logs"] = Value::Null;
            redact_lifecycle_operator(&mut evidence["operator"]);
        }
    }
    for deployment in lifecycle["operations"]["deployments"]
        .as_array_mut()
        .into_iter()
        .flatten()
    {
        deployment["logs"] = Value::Null;
        redact_lifecycle_operator(&mut deployment["operator"]);
    }
}

pub(crate) async fn update_project_lifecycle<F>(
    state: &AppState,
    profile_id: &str,
    params: Value,
    update: F,
) -> ApiResult<Value>
where
    F: FnOnce(&mut Value, &Value, &Value) -> ApiResult<()>,
{
    let project_id = require_lifecycle_project_id(&params)?;
    with_ui_state_write(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, &project_id)?;
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let mut lifecycle = lifecycle_from_state(ui_state, &project_id, project_name);
        require_matching_revision(&lifecycle, &params)?;
        update(&mut lifecycle, &params, &project)?;
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
            .get_mut("projectLifecycleById")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "project lifecycle state is missing",
                )
            })?
            .insert(project_id, lifecycle.clone());
        Ok(lifecycle)
    })
    .await
}

pub(crate) async fn save_project_validation_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    if !role_has_admin_access(auth.role) || !role_has_owner_access(&state.config, auth.role) {
        return Err(api_error(
            StatusCode::FORBIDDEN,
            "Only an owner-authorized admin or owner can configure project validation.",
        ));
    }
    update_project_lifecycle(
        state,
        &auth.profile_id,
        params,
        |lifecycle, params, _project| {
            let checks = normalized_validation_checks(params.get("checks"));
            lifecycle["validation"]["checks"] = json!(checks);
            Ok(())
        },
    )
    .await
}

pub(crate) async fn save_project_governance_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    if !role_has_admin_access(auth.role) || !role_has_owner_access(&state.config, auth.role) {
        return Err(api_error(
            StatusCode::FORBIDDEN,
            "Only the owner can change project governance policy.",
        ));
    }
    update_project_lifecycle(
        state,
        &auth.profile_id,
        params,
        |lifecycle, params, _project| {
            lifecycle["governance"] = normalized_project_governance(params.get("governance"));
            lifecycle["retentionStatus"] = artifact_retention_status(lifecycle);
            Ok(())
        },
    )
    .await
}

fn project_notification_route_enabled(lifecycle: &Value, route: &str) -> bool {
    lifecycle
        .get("governance")
        .and_then(|value| value.get("notificationRoutes"))
        .and_then(|value| value.get(route))
        .and_then(Value::as_bool)
        .unwrap_or(true)
}

fn item_status<'a>(items: &'a [Value], id: &str) -> Option<&'a str> {
    items
        .iter()
        .find(|item| item.get("id").and_then(Value::as_str) == Some(id))
        .and_then(|item| item.get("status"))
        .and_then(Value::as_str)
}

async fn emit_project_release_notifications(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    project_name: &str,
    previous: &Value,
    current: &Value,
) {
    let previous_releases = previous["release"]["releases"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let current_releases = current["release"]["releases"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for release in current_releases {
        let id = release
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let status = release
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if item_status(&previous_releases, id) == Some(status) {
            continue;
        }
        let route = match status {
            "awaitingApproval" => Some(("approvalRequested", "projectApprovalRequested")),
            "released" => Some(("releaseCompleted", "projectReleaseCompleted")),
            "rolledBack" => Some(("rollbackCompleted", "projectRollbackCompleted")),
            _ => None,
        };
        if let Some((route, event_type)) = route
            && project_notification_route_enabled(current, route)
        {
            enqueue_profile_notification(
                state,
                profile_id,
                event_type,
                None,
                json!({
                    "projectId": project_id,
                    "projectName": project_name,
                    "releaseId": id,
                    "version": release.get("version").cloned().unwrap_or(Value::Null),
                    "status": status
                }),
            )
            .await;
        }
    }
}

pub(crate) async fn emit_project_deployment_notifications(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    project_name: &str,
    previous: &Value,
    current: &Value,
) {
    if !project_notification_route_enabled(current, "deploymentFailed") {
        return;
    }
    let previous_deployments = previous["operations"]["deployments"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let current_deployments = current["operations"]["deployments"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for deployment in current_deployments {
        let id = deployment
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if deployment.get("status").and_then(Value::as_str) == Some("failed")
            && item_status(&previous_deployments, id) != Some("failed")
        {
            enqueue_profile_notification(
                state,
                profile_id,
                "projectDeploymentFailed",
                None,
                json!({
                    "projectId": project_id,
                    "projectName": project_name,
                    "deploymentId": id,
                    "releaseId": deployment.get("releaseId").cloned().unwrap_or(Value::Null),
                    "environmentId": deployment.get("environmentId").cloned().unwrap_or(Value::Null),
                    "exitCode": deployment.get("exitCode").cloned().unwrap_or(Value::Null)
                }),
            )
            .await;
        }
    }
}

pub(crate) async fn save_project_release_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    let previous = get_project_lifecycle_payload(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id.clone() }),
    )
    .await?;
    let project_name = previous
        .get("projectName")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let published_artifact_ids = params
        .get("releases")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|release| {
            matches!(
                release.get("status").and_then(Value::as_str),
                Some("released" | "rolledBack")
            )
        })
        .flat_map(|release| {
            release
                .get("artifactIds")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
        })
        .map(str::to_string)
        .collect::<HashSet<_>>();
    for artifact_id in published_artifact_ids {
        verify_project_artifact(state, &auth.profile_id, &project_id, &artifact_id).await?;
    }
    let signing_key = artifact_signing_key(state, &auth.profile_id).await?;
    let signing_project_id = project_id.clone();
    let owner_policy = owner_approval_policy(&state.config);
    let updated = update_project_lifecycle(
        state,
        &auth.profile_id,
        params,
        move |lifecycle, params, _project| {
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
                    let signature_verified = artifact_manifest_signature_is_valid(
                        &signing_key,
                        &signing_project_id,
                        value,
                    );
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
            let mut proposed = lifecycle.clone();
            proposed["release"] = json!({
                "artifacts": artifacts,
                "releases": releases
            });
            validate_published_release_history(lifecycle, &proposed)?;
            for release in proposed["release"]["releases"]
                .as_array()
                .into_iter()
                .flatten()
            {
                validate_release_environment_upgrade(lifecycle, &proposed, release)?;
                if !legacy_targetless_release_is_unchanged(lifecycle, release) {
                    validate_release_policy(&proposed, release, owner_policy)?;
                }
            }
            proposed["retentionStatus"] = artifact_retention_status(&proposed);
            *lifecycle = proposed;
            Ok(())
        },
    )
    .await?;
    emit_project_release_notifications(
        state,
        &auth.profile_id,
        &project_id,
        &project_name,
        &previous,
        &updated,
    )
    .await;
    Ok(updated)
}

pub(crate) async fn save_project_operations_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    if !role_has_admin_access(auth.role) {
        return Err(api_error(
            StatusCode::FORBIDDEN,
            "Only an admin or owner can change project operations.",
        ));
    }
    let owner_access = role_has_owner_access(&state.config, auth.role);
    let project_id = require_lifecycle_project_id(&params)?;
    let previous = get_project_lifecycle_payload(
        state,
        &auth.profile_id,
        json!({ "projectId": project_id.clone() }),
    )
    .await?;
    let project_name = previous
        .get("projectName")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let updated = update_project_lifecycle(
        state,
        &auth.profile_id,
        params,
        |lifecycle, params, _project| {
            let current_deployments = lifecycle["operations"]["deployments"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            if params
                .get("deployments")
                .and_then(Value::as_array)
                .is_some_and(|requested| requested != &current_deployments)
            {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "Deployment evidence is managed by the gateway.",
                ));
            }
            let current_environments = lifecycle["operations"]["environments"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            let environments = params
                .get("environments")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|value| {
                    let existing = current_environments
                        .iter()
                        .find(|entry| entry.get("id") == value.get("id"));
                    normalized_environment(value, existing)
                })
                .take(MAX_ENVIRONMENTS)
                .collect::<Vec<_>>();
            if !owner_access
                && environments.iter().any(|environment| {
                    let existing = current_environments
                        .iter()
                        .find(|entry| entry.get("id") == environment.get("id"));
                    let health_command_changed = environment
                        .get("healthCommand")
                        .is_some_and(|value| !value.is_null())
                        && existing.and_then(|entry| entry.get("healthCommand"))
                            != environment.get("healthCommand");
                    let local_deploy_command_changed =
                        environment.get("adapter").and_then(Value::as_str) == Some("localCommand")
                            && environment
                                .get("deployCommand")
                                .is_some_and(|value| !value.is_null())
                            && (existing.and_then(|entry| entry.get("adapter"))
                                != environment.get("adapter")
                                || existing.and_then(|entry| entry.get("deployCommand"))
                                    != environment.get("deployCommand"));
                    health_command_changed || local_deploy_command_changed
                })
            {
                return Err(api_error(
                    StatusCode::FORBIDDEN,
                    "Only the owner can configure saved local project commands.",
                ));
            }
            if current_environments.iter().any(|environment| {
                environment.get("health").and_then(Value::as_str) == Some("checking")
                    && !environments
                        .iter()
                        .any(|candidate| candidate.get("id") == environment.get("id"))
            }) {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "An environment cannot be removed while its health check is running.",
                ));
            }
            let mut proposed = lifecycle.clone();
            proposed["operations"] = json!({
                "environments": environments,
                "deployments": current_deployments
            });
            for release in proposed["release"]["releases"]
                .as_array()
                .into_iter()
                .flatten()
            {
                validate_release_environment_upgrade(lifecycle, &proposed, release)?;
            }
            for deployment in proposed["operations"]["deployments"]
                .as_array()
                .into_iter()
                .flatten()
            {
                let existing = current_deployments
                    .iter()
                    .find(|entry| entry.get("id") == deployment.get("id"));
                validate_deployment_release_binding(&proposed, deployment, existing)?;
            }
            *lifecycle = proposed;
            Ok(())
        },
    )
    .await?;
    emit_project_deployment_notifications(
        state,
        &auth.profile_id,
        &project_id,
        &project_name,
        &previous,
        &updated,
    )
    .await;
    Ok(updated)
}

pub(crate) async fn save_project_operations_compat_payload(
    state: &AppState,
    auth: &AuthContext,
    params: Value,
) -> ApiResult<Value> {
    if params.get("deployments").is_some() {
        return Err(api_error(
            StatusCode::CONFLICT,
            "ForgeOS client upgrade required: reload the workspace before running a deployment.",
        ));
    }
    save_project_operations_payload(state, auth, params).await
}

pub(crate) async fn list_project_audit_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    let limit = params
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(100)
        .clamp(1, 200) as usize;
    with_ui_state_read(state, profile_id, |ui_state| {
        lifecycle_project_record(ui_state, &project_id)?;
        Ok(())
    })
    .await?;
    let payload = list_audit_log(&state.config, 500)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let entries = payload
        .get("entries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|entry| entry.get("target").and_then(Value::as_str) == Some(project_id.as_str()))
        .take(limit)
        .cloned()
        .collect::<Vec<_>>();
    Ok(json!({ "projectId": project_id, "entries": entries }))
}
