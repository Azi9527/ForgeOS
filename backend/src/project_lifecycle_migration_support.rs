use super::*;
use sha2::Digest as _;

#[cfg(test)]
#[path = "project_lifecycle_migration_support_tests.rs"]
mod tests;

const LIFECYCLE_MIGRATION_SCHEMA_VERSION: u64 = 1;

fn lifecycle_content_digest(value: &Value) -> String {
    let mut normalized = value.clone();
    if let Some(object) = normalized.as_object_mut() {
        for key in [
            "projectId",
            "projectName",
            "revision",
            "updatedAt",
            "retentionStatus",
        ] {
            object.remove(key);
        }
    }
    Sha256::digest(serde_json::to_vec(&normalized).unwrap_or_default())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn lifecycle_migration_record(ui_state: &Value, project_id: &str) -> Option<Value> {
    ui_state
        .get("projectLifecycleMigration")?
        .get("commitsByProjectId")?
        .get(project_id)
        .cloned()
}

fn lifecycle_migration_records_mut(
    ui_state: &mut Value,
) -> ApiResult<&mut serde_json::Map<String, Value>> {
    ui_state
        .get_mut("projectLifecycleMigration")
        .and_then(|migration| migration.get_mut("commitsByProjectId"))
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project lifecycle migration state is missing.",
            )
        })
}

fn lifecycle_by_id(ui_state: &Value, project_id: &str) -> Option<Value> {
    ui_state
        .get("projectLifecycleById")?
        .get(project_id)
        .cloned()
}

fn legacy_project_names(project: &Value) -> Vec<String> {
    let mut names = Vec::new();
    if let Some(name) = project.get("name").and_then(Value::as_str) {
        names.push(name.to_string());
    }
    if let Some(name) = project.get("legacyName").and_then(Value::as_str) {
        names.push(name.to_string());
    }
    if let Some(aliases) = project.get("aliases").and_then(Value::as_array) {
        names.extend(aliases.iter().filter_map(Value::as_str).map(str::to_string));
    }
    names.retain(|name| !name.trim().is_empty());
    names.sort();
    names.dedup();
    names
}

fn legacy_lifecycle_sources(ui_state: &Value, project: &Value) -> Vec<Value> {
    let Some(entries) = ui_state
        .get("projectLifecycleByName")
        .and_then(Value::as_object)
    else {
        return Vec::new();
    };
    legacy_project_names(project)
        .into_iter()
        .filter_map(|project_name| {
            let lifecycle = entries.get(&project_name)?.clone();
            Some(json!({
                "projectName": project_name,
                "revision": lifecycle.get("revision").and_then(Value::as_u64).unwrap_or(0),
                "digest": lifecycle_content_digest(&lifecycle),
                "validationRuns": lifecycle.pointer("/validation/runs").and_then(Value::as_array).map(Vec::len).unwrap_or(0),
                "artifacts": lifecycle.pointer("/release/artifacts").and_then(Value::as_array).map(Vec::len).unwrap_or(0),
                "releases": lifecycle.pointer("/release/releases").and_then(Value::as_array).map(Vec::len).unwrap_or(0),
                "deployments": lifecycle.pointer("/operations/deployments").and_then(Value::as_array).map(Vec::len).unwrap_or(0)
            }))
        })
        .collect()
}

fn lifecycle_migration_payload(ui_state: &Value, project_id: &str) -> ApiResult<Value> {
    let project = lifecycle_project_record(ui_state, project_id)?;
    let current = lifecycle_by_id(ui_state, project_id);
    let sources = legacy_lifecycle_sources(ui_state, &project);
    let record = lifecycle_migration_record(ui_state, project_id);
    let record_status = record
        .as_ref()
        .and_then(|record| record.get("status"))
        .and_then(Value::as_str);
    let status = match record_status {
        Some("copying") => "recoveryRequired",
        Some("rolledBack") => "rolledBack",
        Some("applied") => "migrated",
        _ if sources.is_empty() => "notRequired",
        _ if current.is_none() => "ready",
        _ => {
            let current_digest = lifecycle_content_digest(current.as_ref().unwrap_or(&Value::Null));
            if sources
                .iter()
                .all(|source| source.get("digest").and_then(Value::as_str) == Some(&current_digest))
            {
                "alreadyConsolidated"
            } else {
                "conflict"
            }
        }
    };
    let commit = record
        .as_ref()
        .map(|record| {
            json!({
                "migrationId": record.get("migrationId").cloned().unwrap_or(Value::Null),
                "sourceProjectName": record.get("sourceProjectName").cloned().unwrap_or(Value::Null),
                "strategy": record.get("strategy").cloned().unwrap_or(Value::Null),
                "status": record.get("status").cloned().unwrap_or(Value::Null),
                "startedAt": record.get("startedAt").cloned().unwrap_or(Value::Null),
                "appliedAt": record.get("appliedAt").cloned().unwrap_or(Value::Null),
                "rolledBackAt": record.get("rolledBackAt").cloned().unwrap_or(Value::Null),
                "appliedRevision": record.get("appliedRevision").cloned().unwrap_or(Value::Null)
            })
        })
        .unwrap_or(Value::Null);
    Ok(json!({
        "schemaVersion": LIFECYCLE_MIGRATION_SCHEMA_VERSION,
        "projectId": project_id,
        "projectName": project.get("name").cloned().unwrap_or(Value::Null),
        "status": status,
        "legacySources": sources,
        "current": current.as_ref().map(|value| json!({
            "revision": value.get("revision").and_then(Value::as_u64).unwrap_or(0),
            "digest": lifecycle_content_digest(value)
        })).unwrap_or(Value::Null),
        "commit": commit,
        "canMigrate": matches!(status, "ready" | "conflict" | "rolledBack"),
        "canRollback": status == "migrated",
        "canRecover": status == "recoveryRequired"
    }))
}

pub(crate) async fn get_project_lifecycle_migration_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    with_ui_state_read(state, profile_id, |ui_state| {
        lifecycle_migration_payload(ui_state, &project_id)
    })
    .await
}

fn require_migration_source(params: &Value) -> ApiResult<String> {
    params
        .get("sourceProjectName")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "sourceProjectName is required."))
}

fn migration_strategy(params: &Value) -> ApiResult<&str> {
    match params.get("strategy").and_then(Value::as_str) {
        Some("preferLegacy") => Ok("preferLegacy"),
        Some("keepCurrent") => Ok("keepCurrent"),
        _ => Err(api_error(
            StatusCode::BAD_REQUEST,
            "strategy must be preferLegacy or keepCurrent.",
        )),
    }
}

async fn apply_project_lifecycle_migration(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
) -> ApiResult<Value> {
    let (project_name, source_name, strategy, mut source) =
        with_ui_state_read(state, profile_id, |ui_state| {
            let project = lifecycle_project_record(ui_state, project_id)?;
            let record = lifecycle_migration_record(ui_state, project_id).ok_or_else(|| {
                api_error(
                    StatusCode::CONFLICT,
                    "Lifecycle migration was not prepared.",
                )
            })?;
            Ok((
                project
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                record
                    .get("sourceProjectName")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                record
                    .get("strategy")
                    .and_then(Value::as_str)
                    .unwrap_or("preferLegacy")
                    .to_string(),
                record.get("sourceSnapshot").cloned().unwrap_or(Value::Null),
            ))
        })
        .await?;

    if strategy == "preferLegacy" {
        migrate_legacy_project_artifacts(
            state,
            profile_id,
            project_id,
            &project_name,
            &source_name,
            &mut source,
        )
        .await?;
    }

    with_ui_state_write(state, profile_id, |ui_state| {
        let record = lifecycle_migration_record(ui_state, project_id).ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "Lifecycle migration journal was lost.",
            )
        })?;
        let before = record.get("beforeSnapshot").cloned().unwrap_or(Value::Null);
        let mut applied = if strategy == "keepCurrent" && !before.is_null() {
            before
        } else {
            source.clone()
        };
        let revision = applied
            .get("revision")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            .saturating_add(1);
        applied["projectId"] = json!(project_id);
        applied["projectName"] = json!(project_name);
        applied["revision"] = json!(revision);
        applied["updatedAt"] = json!(now_unix_ms());
        ui_state
            .get_mut("projectLifecycleById")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Project lifecycle state is missing.",
                )
            })?
            .insert(project_id.to_string(), applied);
        let records = lifecycle_migration_records_mut(ui_state)?;
        let record = records.get_mut(project_id).ok_or_else(|| {
            api_error(
                StatusCode::CONFLICT,
                "Lifecycle migration journal was lost.",
            )
        })?;
        record["status"] = json!("applied");
        record["appliedAt"] = json!(now_unix_ms());
        record["appliedRevision"] = json!(revision);
        lifecycle_migration_payload(ui_state, project_id)
    })
    .await
}

pub(crate) async fn commit_project_lifecycle_migration_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    let source_name = require_migration_source(&params)?;
    let strategy = migration_strategy(&params)?.to_string();
    let already_applied = with_ui_state_write(state, profile_id, |ui_state| {
        let project = lifecycle_project_record(ui_state, &project_id)?;
        if !legacy_project_names(&project).contains(&source_name) {
            return Err(api_error(
                StatusCode::BAD_REQUEST,
                "Legacy lifecycle source does not belong to this project.",
            ));
        }
        let source = ui_state
            .get("projectLifecycleByName")
            .and_then(Value::as_object)
            .and_then(|entries| entries.get(&source_name))
            .cloned()
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Legacy lifecycle was not found."))?;
        if let Some(record) = lifecycle_migration_record(ui_state, &project_id)
            && record.get("status").and_then(Value::as_str) == Some("applied")
            && record.get("sourceProjectName").and_then(Value::as_str) == Some(source_name.as_str())
            && record.get("strategy").and_then(Value::as_str) == Some(strategy.as_str())
        {
            return Ok(true);
        }
        let before = lifecycle_by_id(ui_state, &project_id).unwrap_or(Value::Null);
        lifecycle_migration_records_mut(ui_state)?.insert(
            project_id.clone(),
            json!({
                "migrationId": Uuid::new_v4().to_string(),
                "projectId": project_id,
                "sourceProjectName": source_name,
                "strategy": strategy,
                "status": "copying",
                "startedAt": now_unix_ms(),
                "appliedAt": Value::Null,
                "rolledBackAt": Value::Null,
                "beforeSnapshot": before,
                "sourceSnapshot": source
            }),
        );
        Ok(false)
    })
    .await?;
    if already_applied {
        return get_project_lifecycle_migration_payload(
            state,
            profile_id,
            json!({ "projectId": project_id }),
        )
        .await;
    }
    apply_project_lifecycle_migration(state, profile_id, &project_id).await
}

pub(crate) async fn rollback_project_lifecycle_migration_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    with_ui_state_write(state, profile_id, |ui_state| {
        lifecycle_project_record(ui_state, &project_id)?;
        let record = lifecycle_migration_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Migration was not found."))?;
        if record.get("status").and_then(Value::as_str) != Some("applied") {
            return Err(api_error(StatusCode::CONFLICT, "Migration is not applied."));
        }
        let applied_revision = record
            .get("appliedRevision")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let current_revision = lifecycle_by_id(ui_state, &project_id)
            .as_ref()
            .and_then(|value| value.get("revision"))
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if current_revision != applied_revision {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Lifecycle changed after migration. Rollback would discard newer data.",
            ));
        }
        let before = record.get("beforeSnapshot").cloned().unwrap_or(Value::Null);
        let entries = ui_state
            .get_mut("projectLifecycleById")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Project lifecycle state is missing.",
                )
            })?;
        if before.is_null() {
            entries.remove(&project_id);
        } else {
            entries.insert(project_id.clone(), before);
        }
        let record = lifecycle_migration_records_mut(ui_state)?
            .get_mut(&project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Migration was not found."))?;
        record["status"] = json!("rolledBack");
        record["rolledBackAt"] = json!(now_unix_ms());
        lifecycle_migration_payload(ui_state, &project_id)
    })
    .await
}

pub(crate) async fn recover_project_lifecycle_migration_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_lifecycle_project_id(&params)?;
    let status = with_ui_state_read(state, profile_id, |ui_state| {
        lifecycle_project_record(ui_state, &project_id)?;
        Ok(
            lifecycle_migration_record(ui_state, &project_id).and_then(|record| {
                record
                    .get("status")
                    .and_then(Value::as_str)
                    .map(str::to_string)
            }),
        )
    })
    .await?;
    if !matches!(status.as_deref(), Some("copying" | "rolledBack")) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Migration does not require recovery.",
        ));
    }
    if status.as_deref() == Some("rolledBack") {
        with_ui_state_write(state, profile_id, |ui_state| {
            let record = lifecycle_migration_records_mut(ui_state)?
                .get_mut(&project_id)
                .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Migration was not found."))?;
            record["status"] = json!("copying");
            record["startedAt"] = json!(now_unix_ms());
            Ok(())
        })
        .await?;
    }
    apply_project_lifecycle_migration(state, profile_id, &project_id).await
}
