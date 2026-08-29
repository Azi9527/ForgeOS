use super::*;
use sha2::Digest;

const PROJECT_REGISTRY_SCHEMA_VERSION: u64 = 2;
const PROJECT_IMPORT_SESSION_LIMIT: usize = 1_000;

#[derive(Clone, Debug, PartialEq)]
struct PreparedProjectImport {
    candidate_key: String,
    project_id: String,
    name: String,
    root_path: String,
    repository_root: Option<String>,
    conversation_ids: Vec<String>,
    source: String,
}

fn require_project_name(value: Option<&Value>) -> ApiResult<String> {
    let name = value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "Project name is required."))?;
    if name.chars().count() > 120
        || name.chars().any(|character| {
            character.is_control()
                || matches!(
                    character,
                    '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|'
                )
        })
    {
        return Err(api_error(
            StatusCode::BAD_REQUEST,
            "Project name contains unsupported characters or is too long.",
        ));
    }
    Ok(name.to_string())
}

fn require_project_id(params: &Value) -> ApiResult<String> {
    params
        .get("projectId")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| value.starts_with("prj_") && value.len() > 4)
        .map(str::to_string)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "projectId is required."))
}

fn require_conversation_id(params: &Value) -> ApiResult<String> {
    params
        .get("conversationId")
        .or_else(|| params.get("sessionId"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "conversationId is required."))
}

fn normalized_path_key(value: &str) -> String {
    let path = PathBuf::from(value.trim());
    let normalized = path
        .to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_string();
    if cfg!(windows) {
        normalized.to_lowercase()
    } else {
        normalized
    }
}

fn stable_project_id(profile_id: &str, candidate_key: &str) -> String {
    let digest = Sha256::digest(format!("{profile_id}\0{candidate_key}").as_bytes());
    let suffix = digest
        .iter()
        .take(16)
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    format!("prj_{suffix}")
}

fn registry_from_ui_state(ui_state: &Value) -> Option<&serde_json::Map<String, Value>> {
    ui_state.get("projectRegistry").and_then(Value::as_object)
}

pub(crate) fn project_record(ui_state: &Value, project_id: &str) -> Option<Value> {
    registry_from_ui_state(ui_state)?
        .get("projectsById")?
        .as_object()?
        .get(project_id)
        .cloned()
}

fn project_conversation_ids(ui_state: &Value, project_id: &str) -> Vec<String> {
    let mut ids = registry_from_ui_state(ui_state)
        .and_then(|registry| registry.get("projectIdByThreadId"))
        .and_then(Value::as_object)
        .map(|bindings| {
            bindings
                .iter()
                .filter(|(_, bound_project_id)| bound_project_id.as_str() == Some(project_id))
                .map(|(conversation_id, _)| conversation_id.clone())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    ids.sort();
    ids
}

fn project_payload(ui_state: &Value, project: &Value) -> Value {
    let project_id = project
        .get("projectId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let conversation_ids = project_conversation_ids(ui_state, project_id);
    let mut payload = project.clone();
    if let Some(payload) = payload.as_object_mut() {
        payload.insert("conversationIds".to_string(), json!(conversation_ids));
        payload.insert(
            "conversationCount".to_string(),
            json!(
                payload
                    .get("conversationIds")
                    .and_then(Value::as_array)
                    .map(Vec::len)
                    .unwrap_or(0)
            ),
        );
    }
    payload
}

pub(crate) fn project_registry_payload_from_ui_state(ui_state: &Value) -> Value {
    let mut projects = registry_from_ui_state(ui_state)
        .and_then(|registry| registry.get("projectsById"))
        .and_then(Value::as_object)
        .map(|projects| {
            projects
                .values()
                .map(|project| project_payload(ui_state, project))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    projects.sort_by(|left, right| {
        let left_archived = left.get("status").and_then(Value::as_str) == Some("archived");
        let right_archived = right.get("status").and_then(Value::as_str) == Some("archived");
        left_archived
            .cmp(&right_archived)
            .then_with(|| {
                right
                    .get("pinned")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                    .cmp(&left.get("pinned").and_then(Value::as_bool).unwrap_or(false))
            })
            .then_with(|| {
                right
                    .get("lastOpenedAt")
                    .and_then(Value::as_u64)
                    .unwrap_or(0)
                    .cmp(
                        &left
                            .get("lastOpenedAt")
                            .and_then(Value::as_u64)
                            .unwrap_or(0),
                    )
            })
            .then_with(|| {
                left.get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_lowercase()
                    .cmp(
                        &right
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_lowercase(),
                    )
            })
    });
    json!({
        "schemaVersion": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projects": projects
    })
}

fn project_registry_mut(ui_state: &mut Value) -> ApiResult<&mut serde_json::Map<String, Value>> {
    ui_state
        .get_mut("projectRegistry")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project registry state is missing.",
            )
        })
}

fn projects_by_id_mut(ui_state: &mut Value) -> ApiResult<&mut serde_json::Map<String, Value>> {
    project_registry_mut(ui_state)?
        .get_mut("projectsById")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project registry records are missing.",
            )
        })
}

fn sync_legacy_folder(ui_state: &mut Value, project: &Value) -> ApiResult<()> {
    let project_id = project
        .get("projectId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let name = project
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let now = now_unix_ms();
    let folders = ui_state
        .get_mut("sessionFoldersByName")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Session folder compatibility state is missing.",
            )
        })?;
    let current = folders
        .get(name)
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let folder = json!({
        "projectId": project_id,
        "name": name,
        "pinned": project.get("pinned").and_then(Value::as_bool).unwrap_or(false),
        "rootPath": project.get("rootPath").cloned().unwrap_or(Value::Null),
        "repoPath": project.get("repositoryRoot").cloned().unwrap_or(Value::Null),
        "lastSessionId": project.get("lastConversationId").cloned().unwrap_or(Value::Null),
        "lastOpenedAt": project.get("lastOpenedAt").cloned().unwrap_or(Value::Null),
        "settings": project.get("settings").cloned().unwrap_or_else(|| json!({ "model": Value::Null })),
        "createdAt": current.get("createdAt").cloned().unwrap_or_else(|| json!(now)),
        "updatedAt": project.get("updatedAt").cloned().unwrap_or_else(|| json!(now))
    });
    folders.insert(name.to_string(), folder);
    Ok(())
}

fn project_record_value(
    project_id: &str,
    name: &str,
    root_path: &str,
    repository_root: Option<&str>,
    source: &str,
    legacy_name: Option<&str>,
    now: u64,
) -> Value {
    json!({
        "schemaVersion": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projectId": project_id,
        "name": name,
        "rootPath": root_path,
        "repositoryRoot": repository_root,
        "status": "active",
        "pinned": false,
        "settings": { "model": Value::Null },
        "aliases": legacy_name.into_iter().filter(|legacy| *legacy != name).collect::<Vec<_>>(),
        "source": source,
        "legacyName": legacy_name,
        "lastConversationId": Value::Null,
        "lastOpenedAt": Value::Null,
        "createdAt": now,
        "updatedAt": now,
        "revision": 1
    })
}

fn find_project_by_name_or_root(ui_state: &Value, name: &str, root_path: &str) -> Option<Value> {
    let root_key = normalized_path_key(root_path);
    registry_from_ui_state(ui_state)
        .and_then(|registry| registry.get("projectsById"))
        .and_then(Value::as_object)
        .and_then(|projects| {
            projects.values().find(|project| {
                project
                    .get("name")
                    .and_then(Value::as_str)
                    .is_some_and(|value| value.eq_ignore_ascii_case(name))
                    || project
                        .get("rootPath")
                        .and_then(Value::as_str)
                        .is_some_and(|value| normalized_path_key(value) == root_key)
            })
        })
        .cloned()
}

async fn resolve_optional_repository_root(
    state: &AppState,
    params: &Value,
    root_path: &str,
) -> ApiResult<Option<String>> {
    let requested = params
        .get("repositoryRoot")
        .or_else(|| params.get("repoPath"));
    match requested {
        Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if !value.trim().is_empty() => {
            Ok(Some(resolve_git_repo_root(state, value).await?))
        }
        Some(Value::String(_)) => Ok(None),
        Some(_) => Err(api_error(
            StatusCode::BAD_REQUEST,
            "repositoryRoot must be a string or null.",
        )),
        None => Ok(resolve_git_repo_root(state, root_path).await.ok()),
    }
}

async fn emit_project_registry_updated(state: &AppState, profile_id: &str, payload: &Value) {
    emit_profile_config_updated(
        state,
        profile_id,
        json!({
            "projectRegistry": payload.get("projectRegistry").cloned().unwrap_or(Value::Null),
            "sessionOrganization": {
                "knownTags": payload.get("knownTags").cloned().unwrap_or_else(|| json!([])),
                "sessionFolders": payload.get("sessionFolders").cloned().unwrap_or_else(|| json!([]))
            }
        }),
    )
    .await;
    emit_profile_global_notification(
        state,
        profile_id,
        json!({
            "kind": "notification",
            "method": "forgeos/projectRegistryUpdated",
            "params": payload.get("projectRegistry").cloned().unwrap_or(Value::Null)
        }),
    )
    .await;
}

pub(crate) async fn list_projects_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let include_archived = params
        .get("includeArchived")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let start = params
        .get("cursor")
        .and_then(Value::as_str)
        .and_then(|cursor| cursor.parse::<usize>().ok())
        .unwrap_or(0);
    let limit = params
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(100)
        .clamp(1, 200) as usize;
    with_ui_state_read(state, profile_id, |ui_state| {
        let mut payload = project_registry_payload_from_ui_state(ui_state);
        if let Some(projects) = payload.get_mut("projects").and_then(Value::as_array_mut) {
            if !include_archived {
                projects.retain(|project| {
                    project.get("status").and_then(Value::as_str) != Some("archived")
                });
            }
            let total = projects.len();
            let page = projects
                .iter()
                .skip(start)
                .take(limit)
                .cloned()
                .collect::<Vec<_>>();
            *projects = page;
            payload
                .as_object_mut()
                .expect("project registry payload is an object")
                .insert(
                    "nextCursor".to_string(),
                    if start.saturating_add(limit) < total {
                        Value::String(start.saturating_add(limit).to_string())
                    } else {
                        Value::Null
                    },
                );
        }
        Ok(payload)
    })
    .await
}

pub(crate) async fn get_project_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    with_ui_state_read(state, profile_id, |ui_state| {
        let project = project_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
        Ok(json!({ "project": project_payload(ui_state, &project) }))
    })
    .await
}

pub(crate) async fn create_project_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let name = require_project_name(params.get("name"))?;
    let requested_root = params
        .get("rootPath")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "rootPath is required."))?;
    let root_path = resolve_allowed_directory(state, requested_root).await?;
    let repository_root = resolve_optional_repository_root(state, &params, &root_path).await?;
    let source = params
        .get("source")
        .and_then(Value::as_str)
        .filter(|source| matches!(*source, "created" | "imported"))
        .unwrap_or("created");
    let project_id = format!("prj_{}", Uuid::new_v4().simple());

    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        if let Some(existing) = find_project_by_name_or_root(ui_state, &name, &root_path) {
            let existing_matches = existing
                .get("name")
                .and_then(Value::as_str)
                .is_some_and(|value| value.eq_ignore_ascii_case(&name))
                && existing
                    .get("rootPath")
                    .and_then(Value::as_str)
                    .is_some_and(|value| {
                        normalized_path_key(value) == normalized_path_key(&root_path)
                    });
            if !existing_matches {
                return Err(api_error(
                    StatusCode::CONFLICT,
                    "A project with this name or root directory already exists.",
                ));
            }
            return Ok(json!({
                "created": false,
                "project": project_payload(ui_state, &existing),
                "projectRegistry": project_registry_payload_from_ui_state(ui_state),
                "knownTags": known_tags_from_ui_state(ui_state),
                "sessionFolders": session_folders_from_ui_state(ui_state)
            }));
        }
        let now = now_unix_ms();
        let project = project_record_value(
            &project_id,
            &name,
            &root_path,
            repository_root.as_deref(),
            source,
            None,
            now,
        );
        projects_by_id_mut(ui_state)?.insert(project_id.clone(), project.clone());
        sync_legacy_folder(ui_state, &project)?;
        Ok(json!({
            "created": true,
            "project": project_payload(ui_state, &project),
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

pub(crate) async fn update_project_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    let name_patch = params
        .get("name")
        .map(|value| require_project_name(Some(value)))
        .transpose()?;
    let root_path_patch = match params.get("rootPath") {
        None => None,
        Some(Value::String(value)) if !value.trim().is_empty() => {
            Some(resolve_allowed_directory(state, value).await?)
        }
        Some(_) => {
            return Err(api_error(
                StatusCode::BAD_REQUEST,
                "rootPath must be a non-empty string.",
            ));
        }
    };
    let repository_root_patch =
        if params.get("repositoryRoot").is_some() || params.get("repoPath").is_some() {
            Some(
                resolve_optional_repository_root(
                    state,
                    &params,
                    root_path_patch.as_deref().unwrap_or(""),
                )
                .await?,
            )
        } else {
            None
        };
    let expected_revision = params.get("revision").and_then(Value::as_u64);
    let pinned_patch = params.get("pinned").and_then(Value::as_bool);
    let mark_opened = params
        .get("markOpened")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let last_conversation_patch = match params
        .get("lastConversationId")
        .or_else(|| params.get("lastSessionId"))
    {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::String(value)) if !value.trim().is_empty() => {
            Some(Some(value.trim().to_string()))
        }
        Some(_) => {
            return Err(api_error(
                StatusCode::BAD_REQUEST,
                "lastConversationId must be a string or null.",
            ));
        }
    };
    let model_patch = params
        .get("settings")
        .and_then(Value::as_object)
        .and_then(|settings| settings.get("model"))
        .map(|model| match model {
            Value::Null => Ok(None),
            Value::String(value) => {
                Ok((!value.trim().is_empty()).then(|| value.trim().to_string()))
            }
            _ => Err(api_error(
                StatusCode::BAD_REQUEST,
                "settings.model must be a string or null.",
            )),
        })
        .transpose()?;

    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        let current = project_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
        let current_revision = current.get("revision").and_then(Value::as_u64).unwrap_or(1);
        if expected_revision.is_some_and(|expected| expected != current_revision) {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Project was updated by another request.",
            ));
        }
        let current_name = current
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let next_name = name_patch.clone().unwrap_or_else(|| current_name.clone());
        let next_root = root_path_patch.clone().unwrap_or_else(|| {
            current
                .get("rootPath")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string()
        });
        if registry_from_ui_state(ui_state)
            .and_then(|registry| registry.get("projectsById"))
            .and_then(Value::as_object)
            .is_some_and(|projects| {
                projects.iter().any(|(other_id, project)| {
                    other_id != &project_id
                        && (project
                            .get("name")
                            .and_then(Value::as_str)
                            .is_some_and(|value| value.eq_ignore_ascii_case(&next_name))
                            || project.get("rootPath").and_then(Value::as_str).is_some_and(
                                |value| {
                                    normalized_path_key(value) == normalized_path_key(&next_root)
                                },
                            ))
                })
            })
        {
            return Err(api_error(
                StatusCode::CONFLICT,
                "A project with this name or root directory already exists.",
            ));
        }

        let now = now_unix_ms();
        let mut next = current.as_object().cloned().unwrap_or_default();
        next.insert("name".to_string(), Value::String(next_name.clone()));
        if current_name != next_name {
            let mut aliases = current
                .get("aliases")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if !aliases
                .iter()
                .any(|alias| alias.as_str() == Some(current_name.as_str()))
            {
                aliases.push(Value::String(current_name.clone()));
            }
            aliases.truncate(20);
            next.insert("aliases".to_string(), Value::Array(aliases));
        }
        next.insert("rootPath".to_string(), Value::String(next_root));
        if let Some(repository_root) = repository_root_patch.clone() {
            next.insert(
                "repositoryRoot".to_string(),
                repository_root.map(Value::String).unwrap_or(Value::Null),
            );
        }
        if let Some(pinned) = pinned_patch {
            next.insert("pinned".to_string(), Value::Bool(pinned));
        }
        if let Some(last_conversation_id) = last_conversation_patch.clone() {
            next.insert(
                "lastConversationId".to_string(),
                last_conversation_id
                    .map(Value::String)
                    .unwrap_or(Value::Null),
            );
        }
        if mark_opened {
            next.insert("lastOpenedAt".to_string(), json!(now));
        }
        if let Some(model) = model_patch.clone() {
            next.insert("settings".to_string(), json!({ "model": model }));
        }
        next.insert("updatedAt".to_string(), json!(now));
        next.insert("revision".to_string(), json!(current_revision + 1));
        let next = Value::Object(next);

        if current_name != next_name {
            if let Some(folder) = ui_state
                .get_mut("sessionFoldersByName")
                .and_then(Value::as_object_mut)
                .and_then(|folders| folders.remove(&current_name))
            {
                ui_state
                    .get_mut("sessionFoldersByName")
                    .and_then(Value::as_object_mut)
                    .expect("session folder state is ensured")
                    .insert(next_name.clone(), folder);
            }
            if let Some(entries) = ui_state
                .get_mut("sessionMetaByThreadId")
                .and_then(Value::as_object_mut)
            {
                for meta in entries.values_mut() {
                    if let Some(tags) = meta.get_mut("tags").and_then(Value::as_array_mut) {
                        for tag in tags {
                            if tag.as_str() == Some(current_name.as_str()) {
                                *tag = Value::String(next_name.clone());
                            }
                        }
                    }
                }
            }
        }
        projects_by_id_mut(ui_state)?.insert(project_id.clone(), next.clone());
        sync_legacy_folder(ui_state, &next)?;
        Ok(json!({
            "project": project_payload(ui_state, &next),
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

pub(crate) async fn archive_project_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        let mut project = project_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
        let now = now_unix_ms();
        let object = project
            .as_object_mut()
            .expect("project records are objects");
        object.insert("status".to_string(), Value::String("archived".to_string()));
        object.insert("updatedAt".to_string(), json!(now));
        let revision = object.get("revision").and_then(Value::as_u64).unwrap_or(1) + 1;
        object.insert("revision".to_string(), json!(revision));
        projects_by_id_mut(ui_state)?.insert(project_id.clone(), project.clone());
        Ok(json!({
            "project": project_payload(ui_state, &project),
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

fn session_tags(session: &Value) -> Vec<&str> {
    session
        .get("tags")
        .and_then(Value::as_array)
        .map(|tags| tags.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default()
}

fn migration_candidates(ui_state: &Value, sessions: &[Value]) -> Vec<Value> {
    let registry = project_registry_payload_from_ui_state(ui_state);
    let projects = registry
        .get("projects")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let project_roots = projects
        .iter()
        .filter_map(|project| {
            project
                .get("rootPath")
                .and_then(Value::as_str)
                .map(normalized_path_key)
        })
        .collect::<HashSet<_>>();
    let folders = session_folders_from_ui_state(ui_state);
    let mut covered_roots = project_roots.clone();
    let mut candidates = Vec::new();

    for folder in folders {
        let name = folder
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if name.is_empty() {
            continue;
        }
        let mut related = sessions
            .iter()
            .filter(|session| session_tags(session).contains(&name))
            .cloned()
            .collect::<Vec<_>>();
        related.sort_by_key(|session| {
            session
                .get("updatedAt")
                .and_then(Value::as_i64)
                .unwrap_or(0)
        });
        related.reverse();
        let inferred_roots = related
            .iter()
            .filter_map(|session| session.get("cwd").and_then(Value::as_str))
            .filter(|value| !value.trim().is_empty())
            .map(str::to_string)
            .collect::<HashSet<_>>();
        let root_path = folder
            .get("rootPath")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or_else(|| {
                (inferred_roots.len() == 1)
                    .then(|| inferred_roots.iter().next().cloned())
                    .flatten()
            });
        let existing = projects.iter().find(|project| {
            project.get("legacyName").and_then(Value::as_str) == Some(name)
                || project
                    .get("name")
                    .and_then(Value::as_str)
                    .is_some_and(|value| value.eq_ignore_ascii_case(name))
                || root_path.as_deref().is_some_and(|root| {
                    project
                        .get("rootPath")
                        .and_then(Value::as_str)
                        .is_some_and(|value| {
                            normalized_path_key(value) == normalized_path_key(root)
                        })
                })
        });
        if let Some(root_path) = root_path.as_deref() {
            covered_roots.insert(normalized_path_key(root_path));
        }
        let status = if existing.is_some() {
            "alreadyImported"
        } else if root_path.is_some() {
            "ready"
        } else {
            "needsRoot"
        };
        let candidate_key = format!("folder:{}", normalized_path_key(name));
        candidates.push(json!({
            "candidateKey": candidate_key,
            "source": "sessionFolder",
            "name": name,
            "rootPath": root_path,
            "repositoryRoot": folder.get("repoPath").cloned().unwrap_or(Value::Null),
            "conversationIds": related.iter().filter_map(|session| session.get("id").and_then(Value::as_str)).collect::<Vec<_>>(),
            "status": status,
            "existingProjectId": existing.and_then(|project| project.get("projectId")).cloned().unwrap_or(Value::Null),
            "warnings": if inferred_roots.len() > 1 { json!(["Tagged conversations use multiple working directories."]) } else { json!([]) }
        }));
    }

    let mut sessions_by_root: HashMap<String, Vec<&Value>> = HashMap::new();
    for session in sessions {
        let Some(root_path) = session
            .get("cwd")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
        else {
            continue;
        };
        let root_key = normalized_path_key(root_path);
        if covered_roots.contains(&root_key) {
            continue;
        }
        sessions_by_root.entry(root_key).or_default().push(session);
    }
    for (root_key, related) in sessions_by_root {
        let root_path = related
            .first()
            .and_then(|session| session.get("cwd"))
            .and_then(Value::as_str)
            .unwrap_or_default();
        let root_path_buf = PathBuf::from(root_path);
        let name = root_path_buf
            .file_name()
            .and_then(|value| value.to_str())
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("Imported project")
            .to_string();
        let digest = Sha256::digest(root_key.as_bytes());
        let key_suffix = digest
            .iter()
            .take(12)
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        candidates.push(json!({
            "candidateKey": format!("cwd:{key_suffix}"),
            "source": "conversationCwd",
            "name": name,
            "rootPath": root_path,
            "repositoryRoot": related.iter().find_map(|session| session.get("preferences").and_then(|preferences| preferences.get("gitRepoPath")).and_then(Value::as_str)),
            "conversationIds": related.iter().filter_map(|session| session.get("id").and_then(Value::as_str)).collect::<Vec<_>>(),
            "status": "ready",
            "existingProjectId": Value::Null,
            "warnings": []
        }));
    }
    candidates.sort_by(|left, right| {
        left.get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_lowercase()
            .cmp(
                &right
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_lowercase(),
            )
    });
    candidates
}

async fn migration_sessions(state: &AppState, profile_id: &str) -> (Vec<Value>, Vec<String>) {
    let mut sessions = Vec::new();
    let mut warnings = Vec::new();
    for archived in [false, true] {
        let mut cursor = None;
        loop {
            match list_sessions_payload(
                state,
                profile_id,
                archived,
                cursor.as_deref(),
                200,
                &SessionFilterCriteria::default(),
            )
            .await
            {
                Ok(payload) => {
                    sessions.extend(
                        payload
                            .get("sessions")
                            .and_then(Value::as_array)
                            .cloned()
                            .unwrap_or_default(),
                    );
                    cursor = payload
                        .get("nextCursor")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    if cursor.is_none() || sessions.len() >= PROJECT_IMPORT_SESSION_LIMIT {
                        if sessions.len() >= PROJECT_IMPORT_SESSION_LIMIT {
                            warnings.push(format!("Conversation discovery was capped at {PROJECT_IMPORT_SESSION_LIMIT} records."));
                        }
                        break;
                    }
                }
                Err(error) => {
                    warnings.push(format!(
                        "Codex conversation discovery was unavailable: {}",
                        error.message
                    ));
                    break;
                }
            }
        }
    }
    sessions.sort_by(|left, right| {
        left.get("id")
            .and_then(Value::as_str)
            .cmp(&right.get("id").and_then(Value::as_str))
    });
    sessions.dedup_by(|left, right| {
        left.get("id").and_then(Value::as_str) == right.get("id").and_then(Value::as_str)
    });
    (sessions, warnings)
}

pub(crate) async fn preview_project_import_v2_payload(
    state: &AppState,
    profile_id: &str,
) -> ApiResult<Value> {
    let (sessions, warnings) = migration_sessions(state, profile_id).await;
    with_ui_state_read(state, profile_id, |ui_state| {
        let mut candidates = migration_candidates(ui_state, &sessions);
        for candidate in &mut candidates {
            if let Some(candidate_key) = candidate.get("candidateKey").and_then(Value::as_str) {
                let proposed_project_id = stable_project_id(profile_id, candidate_key);
                candidate
                    .as_object_mut()
                    .expect("migration candidates are objects")
                    .insert(
                        "proposedProjectId".to_string(),
                        Value::String(proposed_project_id),
                    );
            }
        }
        Ok(json!({
            "schemaVersion": PROJECT_REGISTRY_SCHEMA_VERSION,
            "writePerformed": false,
            "candidates": candidates,
            "warnings": warnings
        }))
    })
    .await
}

pub(crate) async fn commit_project_import_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let requested_keys = params
        .get("candidateKeys")
        .and_then(Value::as_array)
        .map(|keys| {
            keys.iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect::<HashSet<_>>()
        })
        .filter(|keys| !keys.is_empty())
        .ok_or_else(|| api_error(StatusCode::BAD_REQUEST, "candidateKeys is required."))?;
    let preview = preview_project_import_v2_payload(state, profile_id).await?;
    let selected = preview
        .get("candidates")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|candidate| {
            candidate
                .get("candidateKey")
                .and_then(Value::as_str)
                .is_some_and(|key| requested_keys.contains(key))
        })
        .cloned()
        .collect::<Vec<_>>();
    if selected.len() != requested_keys.len() {
        return Err(api_error(
            StatusCode::CONFLICT,
            "One or more migration candidates changed. Refresh the preview.",
        ));
    }

    let mut prepared = Vec::new();
    for candidate in selected {
        if candidate.get("status").and_then(Value::as_str) == Some("alreadyImported") {
            continue;
        }
        if candidate.get("status").and_then(Value::as_str) != Some("ready") {
            return Err(api_error(
                StatusCode::CONFLICT,
                "A selected migration candidate is not ready.",
            ));
        }
        let candidate_key = candidate
            .get("candidateKey")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let name = require_project_name(candidate.get("name"))?;
        let root_path = resolve_allowed_directory(
            state,
            candidate
                .get("rootPath")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .await?;
        let repository_root = match candidate.get("repositoryRoot").and_then(Value::as_str) {
            Some(repository_root) if !repository_root.trim().is_empty() => {
                resolve_git_repo_root(state, repository_root).await.ok()
            }
            _ => resolve_git_repo_root(state, &root_path).await.ok(),
        };
        let mut conversation_ids = candidate
            .get("conversationIds")
            .and_then(Value::as_array)
            .map(|ids| {
                ids.iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        conversation_ids.sort();
        conversation_ids.dedup();
        prepared.push(PreparedProjectImport {
            project_id: stable_project_id(profile_id, &candidate_key),
            candidate_key,
            name,
            root_path,
            repository_root,
            conversation_ids,
            source: candidate
                .get("source")
                .and_then(Value::as_str)
                .unwrap_or("legacy")
                .to_string(),
        });
    }

    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        let now = now_unix_ms();
        let mut imported = Vec::new();
        for prepared in &prepared {
            let project =
                find_project_by_name_or_root(ui_state, &prepared.name, &prepared.root_path)
                    .unwrap_or_else(|| {
                        project_record_value(
                            &prepared.project_id,
                            &prepared.name,
                            &prepared.root_path,
                            prepared.repository_root.as_deref(),
                            "migrated",
                            (prepared.source == "sessionFolder").then_some(prepared.name.as_str()),
                            now,
                        )
                    });
            let project_id = project
                .get("projectId")
                .and_then(Value::as_str)
                .unwrap_or(&prepared.project_id)
                .to_string();
            projects_by_id_mut(ui_state)?.insert(project_id.clone(), project.clone());
            sync_legacy_folder(ui_state, &project)?;
            let bindings = project_registry_mut(ui_state)?
                .get_mut("projectIdByThreadId")
                .and_then(Value::as_object_mut)
                .expect("project conversation bindings are ensured");
            for conversation_id in &prepared.conversation_ids {
                bindings.insert(conversation_id.clone(), Value::String(project_id.clone()));
            }
            project_registry_mut(ui_state)?
                .get_mut("migrationCommitsByKey")
                .and_then(Value::as_object_mut)
                .expect("project migration commits are ensured")
                .insert(
                    prepared.candidate_key.clone(),
                    json!({ "projectId": project_id, "committedAt": now }),
                );
            imported
                .push(json!({ "candidateKey": prepared.candidate_key, "projectId": project_id }));
        }
        Ok(json!({
            "imported": imported,
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

pub(crate) async fn list_project_conversations_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    with_ui_state_read(state, profile_id, |ui_state| {
        if project_record(ui_state, &project_id).is_none() {
            return Err(api_error(StatusCode::NOT_FOUND, "Project was not found."));
        }
        Ok(json!({
            "projectId": project_id,
            "conversationIds": project_conversation_ids(ui_state, &project_id)
        }))
    })
    .await
}

pub(crate) async fn attach_project_conversation_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    let conversation_id = require_conversation_id(&params)?;
    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        let mut project = project_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
        if project.get("status").and_then(Value::as_str) == Some("archived") {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Archived projects cannot accept conversations.",
            ));
        }
        project_registry_mut(ui_state)?
            .get_mut("projectIdByThreadId")
            .and_then(Value::as_object_mut)
            .expect("project conversation bindings are ensured")
            .insert(conversation_id.clone(), Value::String(project_id.clone()));
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let meta = ui_state
            .get_mut("sessionMetaByThreadId")
            .and_then(Value::as_object_mut)
            .expect("session metadata state is ensured")
            .entry(conversation_id.clone())
            .or_insert_with(|| json!({ "pinned": false, "tags": [] }));
        let tags = meta
            .as_object_mut()
            .expect("session metadata records are objects")
            .entry("tags".to_string())
            .or_insert_with(|| json!([]));
        let tags = tags.as_array_mut().expect("session tags are arrays");
        if !tags
            .iter()
            .any(|tag| tag.as_str() == Some(project_name.as_str()))
        {
            tags.push(Value::String(project_name));
        }
        let now = now_unix_ms();
        let object = project
            .as_object_mut()
            .expect("project records are objects");
        object.insert(
            "lastConversationId".to_string(),
            Value::String(conversation_id.clone()),
        );
        object.insert("lastOpenedAt".to_string(), json!(now));
        object.insert("updatedAt".to_string(), json!(now));
        let revision = object.get("revision").and_then(Value::as_u64).unwrap_or(1) + 1;
        object.insert("revision".to_string(), json!(revision));
        projects_by_id_mut(ui_state)?.insert(project_id.clone(), project.clone());
        sync_legacy_folder(ui_state, &project)?;
        Ok(json!({
            "project": project_payload(ui_state, &project),
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

pub(crate) async fn detach_project_conversation_v2_payload(
    state: &AppState,
    profile_id: &str,
    params: Value,
) -> ApiResult<Value> {
    let project_id = require_project_id(&params)?;
    let conversation_id = require_conversation_id(&params)?;
    let payload = with_ui_state_write(state, profile_id, |ui_state| {
        let project = project_record(ui_state, &project_id)
            .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
        let project_name = project
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let bindings = project_registry_mut(ui_state)?
            .get_mut("projectIdByThreadId")
            .and_then(Value::as_object_mut)
            .expect("project conversation bindings are ensured");
        if bindings.get(&conversation_id).and_then(Value::as_str) == Some(project_id.as_str()) {
            bindings.remove(&conversation_id);
        }
        if let Some(tags) = ui_state
            .get_mut("sessionMetaByThreadId")
            .and_then(Value::as_object_mut)
            .and_then(|entries| entries.get_mut(&conversation_id))
            .and_then(Value::as_object_mut)
            .and_then(|meta| meta.get_mut("tags"))
            .and_then(Value::as_array_mut)
        {
            tags.retain(|tag| tag.as_str() != Some(project_name.as_str()));
        }
        Ok(json!({
            "detached": true,
            "projectId": project_id,
            "conversationId": conversation_id,
            "projectRegistry": project_registry_payload_from_ui_state(ui_state),
            "knownTags": known_tags_from_ui_state(ui_state),
            "sessionFolders": session_folders_from_ui_state(ui_state)
        }))
    })
    .await?;
    emit_project_registry_updated(state, profile_id, &payload).await;
    Ok(payload)
}

#[cfg(test)]
#[path = "project_registry_support_tests.rs"]
mod tests;
