use super::*;

fn binding_registry_mut(ui_state: &mut Value) -> ApiResult<&mut serde_json::Map<String, Value>> {
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

fn binding_projects_mut(ui_state: &mut Value) -> ApiResult<&mut serde_json::Map<String, Value>> {
    binding_registry_mut(ui_state)?
        .get_mut("projectsById")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project registry records are missing.",
            )
        })
}

fn binding_project(ui_state: &Value, project_id: &str) -> Option<Value> {
    ui_state
        .get("projectRegistry")?
        .get("projectsById")?
        .as_object()?
        .get(project_id)
        .cloned()
}

fn project_compatibility_names(ui_state: &Value, project_id: &str, project: &Value) -> Vec<String> {
    let mut names = project
        .get("name")
        .and_then(Value::as_str)
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
    names.extend(
        ui_state
            .get("sessionFoldersByName")
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
            .filter(|(_, folder)| {
                folder.get("projectId").and_then(Value::as_str) == Some(project_id)
            })
            .map(|(name, _)| name.clone()),
    );
    names.sort();
    names.dedup();
    names
}

fn remove_compatibility_tags(meta: &mut Value, names: &[String]) {
    if let Some(tags) = meta
        .as_object_mut()
        .and_then(|meta| meta.get_mut("tags"))
        .and_then(Value::as_array_mut)
    {
        tags.retain(|tag| {
            tag.as_str()
                .is_none_or(|tag| !names.iter().any(|name| name == tag))
        });
    }
}

fn remove_conversation_compatibility_tags(
    ui_state: &mut Value,
    conversation_id: &str,
    project: &Value,
) {
    let project_id = project
        .get("projectId")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let names = project_compatibility_names(ui_state, project_id, project);
    if let Some(meta) = ui_state
        .get_mut("sessionMetaByThreadId")
        .and_then(Value::as_object_mut)
        .and_then(|entries| entries.get_mut(conversation_id))
    {
        remove_compatibility_tags(meta, &names);
    }
}

fn add_conversation_compatibility_tag(
    ui_state: &mut Value,
    conversation_id: &str,
    project_name: &str,
) {
    let meta = ui_state
        .get_mut("sessionMetaByThreadId")
        .and_then(Value::as_object_mut)
        .expect("session metadata state is ensured")
        .entry(conversation_id.to_string())
        .or_insert_with(|| json!({ "pinned": false, "tags": [] }));
    let tags = meta
        .as_object_mut()
        .expect("session metadata records are objects")
        .entry("tags".to_string())
        .or_insert_with(|| json!([]));
    let tags = tags.as_array_mut().expect("session tags are arrays");
    if !tags.iter().any(|tag| tag.as_str() == Some(project_name)) {
        tags.push(Value::String(project_name.to_string()));
    }
}

fn touch_project(project: &mut Value, now: u64) {
    let object = project
        .as_object_mut()
        .expect("project records are objects");
    object.insert("updatedAt".to_string(), json!(now));
    let revision = object.get("revision").and_then(Value::as_u64).unwrap_or(1) + 1;
    object.insert("revision".to_string(), json!(revision));
}

fn clear_last_conversation(project: &mut Value, conversation_id: &str) {
    if project.get("lastConversationId").and_then(Value::as_str) == Some(conversation_id) {
        project
            .as_object_mut()
            .expect("project records are objects")
            .insert("lastConversationId".to_string(), Value::Null);
    }
}

pub(crate) fn sync_project_compatibility_folder(
    ui_state: &mut Value,
    project: &Value,
) -> ApiResult<()> {
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

pub(crate) fn validate_project_last_conversation_binding(
    ui_state: &Value,
    project_id: &str,
    conversation_id: &str,
) -> ApiResult<()> {
    let bound_project_id = ui_state
        .get("projectRegistry")
        .and_then(|registry| registry.get("projectIdByThreadId"))
        .and_then(Value::as_object)
        .and_then(|bindings| bindings.get(conversation_id))
        .and_then(Value::as_str);
    if bound_project_id != Some(project_id) {
        return Err(api_error(
            StatusCode::CONFLICT,
            "lastConversationId must reference a conversation bound to this project.",
        ));
    }
    Ok(())
}

pub(crate) fn attach_project_conversation_state(
    ui_state: &mut Value,
    project_id: &str,
    conversation_id: &str,
    now: u64,
) -> ApiResult<Value> {
    let mut project = binding_project(ui_state, project_id)
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
    if project.get("status").and_then(Value::as_str) == Some("archived") {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Archived projects cannot accept conversations.",
        ));
    }

    let previous_project_id = ui_state
        .get("projectRegistry")
        .and_then(|registry| registry.get("projectIdByThreadId"))
        .and_then(Value::as_object)
        .and_then(|bindings| bindings.get(conversation_id))
        .and_then(Value::as_str)
        .map(str::to_string);
    if let Some(previous_project_id) = previous_project_id
        && previous_project_id != project_id
        && let Some(mut previous_project) = binding_project(ui_state, &previous_project_id)
    {
        remove_conversation_compatibility_tags(ui_state, conversation_id, &previous_project);
        clear_last_conversation(&mut previous_project, conversation_id);
        touch_project(&mut previous_project, now);
        binding_projects_mut(ui_state)?.insert(previous_project_id, previous_project.clone());
        sync_project_compatibility_folder(ui_state, &previous_project)?;
    }

    binding_registry_mut(ui_state)?
        .get_mut("projectIdByThreadId")
        .and_then(Value::as_object_mut)
        .expect("project conversation bindings are ensured")
        .insert(
            conversation_id.to_string(),
            Value::String(project_id.to_string()),
        );
    let project_name = project
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    add_conversation_compatibility_tag(ui_state, conversation_id, &project_name);
    let object = project
        .as_object_mut()
        .expect("project records are objects");
    object.insert(
        "lastConversationId".to_string(),
        Value::String(conversation_id.to_string()),
    );
    object.insert("lastOpenedAt".to_string(), json!(now));
    touch_project(&mut project, now);
    binding_projects_mut(ui_state)?.insert(project_id.to_string(), project.clone());
    sync_project_compatibility_folder(ui_state, &project)?;
    Ok(project)
}

pub(crate) fn detach_project_conversation_state(
    ui_state: &mut Value,
    project_id: &str,
    conversation_id: &str,
    now: u64,
) -> ApiResult<Value> {
    let mut project = binding_project(ui_state, project_id)
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
    let binding_removed = {
        let bindings = binding_registry_mut(ui_state)?
            .get_mut("projectIdByThreadId")
            .and_then(Value::as_object_mut)
            .expect("project conversation bindings are ensured");
        if bindings.get(conversation_id).and_then(Value::as_str) == Some(project_id) {
            bindings.remove(conversation_id);
            true
        } else {
            false
        }
    };
    remove_conversation_compatibility_tags(ui_state, conversation_id, &project);
    let cleared_last =
        project.get("lastConversationId").and_then(Value::as_str) == Some(conversation_id);
    clear_last_conversation(&mut project, conversation_id);
    if binding_removed || cleared_last {
        touch_project(&mut project, now);
        binding_projects_mut(ui_state)?.insert(project_id.to_string(), project.clone());
        sync_project_compatibility_folder(ui_state, &project)?;
    }
    Ok(project)
}

pub(crate) fn archive_project_conversation_state(
    ui_state: &mut Value,
    project_id: &str,
    now: u64,
) -> ApiResult<Value> {
    let mut project = binding_project(ui_state, project_id)
        .ok_or_else(|| api_error(StatusCode::NOT_FOUND, "Project was not found."))?;
    binding_registry_mut(ui_state)?
        .get_mut("projectIdByThreadId")
        .and_then(Value::as_object_mut)
        .expect("project conversation bindings are ensured")
        .retain(|_, bound_project_id| bound_project_id.as_str() != Some(project_id));

    let compatibility_names = project_compatibility_names(ui_state, project_id, &project);
    if let Some(entries) = ui_state
        .get_mut("sessionMetaByThreadId")
        .and_then(Value::as_object_mut)
    {
        for meta in entries.values_mut() {
            remove_compatibility_tags(meta, &compatibility_names);
        }
    }
    if let Some(folders) = ui_state
        .get_mut("sessionFoldersByName")
        .and_then(Value::as_object_mut)
    {
        for name in &compatibility_names {
            folders.remove(name);
        }
    }

    let object = project
        .as_object_mut()
        .expect("project records are objects");
    object.insert("status".to_string(), Value::String("archived".to_string()));
    object.insert("lastConversationId".to_string(), Value::Null);
    touch_project(&mut project, now);
    binding_projects_mut(ui_state)?.insert(project_id.to_string(), project.clone());
    Ok(project)
}
