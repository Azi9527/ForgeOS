use super::*;

fn test_ui_state() -> Value {
    json!({
        "projectRegistry": {
            "schemaVersion": 2,
            "projectsById": {},
            "projectIdByThreadId": {},
            "migrationCommitsByKey": {}
        },
        "sessionFoldersByName": {},
        "sessionMetaByThreadId": {}
    })
}

#[test]
fn registry_payload_uses_stable_identity_and_explicit_conversation_bindings() {
    let mut ui_state = test_ui_state();
    let project = project_record_value(
        "prj_aps",
        "APS",
        "D:\\codex\\APS",
        Some("D:\\codex\\APS"),
        "created",
        None,
        100,
    );
    projects_by_id_mut(&mut ui_state)
        .expect("project registry")
        .insert("prj_aps".to_string(), project);
    project_registry_mut(&mut ui_state)
        .expect("project registry")
        .get_mut("projectIdByThreadId")
        .and_then(Value::as_object_mut)
        .expect("conversation bindings")
        .insert("thread-1".to_string(), json!("prj_aps"));

    let payload = project_registry_payload_from_ui_state(&ui_state);

    assert_eq!(
        payload,
        json!({
            "schemaVersion": 2,
            "projects": [{
                "schemaVersion": 2,
                "projectId": "prj_aps",
                "name": "APS",
                "rootPath": "D:\\codex\\APS",
                "repositoryRoot": "D:\\codex\\APS",
                "status": "active",
                "pinned": false,
                "settings": { "model": Value::Null },
                "aliases": [],
                "source": "created",
                "legacyName": Value::Null,
                "lastConversationId": Value::Null,
                "lastOpenedAt": Value::Null,
                "createdAt": 100,
                "updatedAt": 100,
                "revision": 1,
                "conversationIds": ["thread-1"],
                "conversationCount": 1
            }]
        })
    );
}

#[test]
fn migration_preview_is_read_only_and_keeps_legacy_folder_identity() {
    let mut ui_state = test_ui_state();
    ui_state["sessionFoldersByName"]["APS"] = json!({
        "name": "APS",
        "rootPath": "D:\\codex\\APS",
        "repoPath": "D:\\codex\\APS"
    });
    ui_state["sessionMetaByThreadId"]["thread-1"] = json!({
        "pinned": false,
        "tags": ["APS"]
    });
    let before = ui_state.clone();
    let sessions = vec![json!({
        "id": "thread-1",
        "tags": ["APS"],
        "cwd": "D:\\codex\\APS",
        "updatedAt": 200
    })];

    let candidates = migration_candidates(&ui_state, &sessions);

    assert_eq!(ui_state, before);
    assert_eq!(
        candidates,
        vec![json!({
            "candidateKey": "folder:aps",
            "source": "sessionFolder",
            "name": "APS",
            "rootPath": "D:\\codex\\APS",
            "repositoryRoot": "D:\\codex\\APS",
            "conversationIds": ["thread-1"],
            "status": "ready",
            "existingProjectId": Value::Null,
            "warnings": []
        })]
    );
}

#[test]
fn deterministic_import_id_survives_retries() {
    assert_eq!(
        stable_project_id("default", "folder:aps"),
        stable_project_id("default", "folder:aps")
    );
    assert_ne!(
        stable_project_id("default", "folder:aps"),
        stable_project_id("default", "folder:other")
    );
}

#[test]
fn registered_project_root_cannot_move_and_leave_a_stale_manifest() {
    assert!(validate_project_root_update("D:\\codex\\APS", "D:\\codex\\APS\\").is_ok());
    let error = validate_project_root_update("D:\\codex\\APS", "D:\\codex\\APS-copy")
        .expect_err("cross-root update must be rejected");

    assert_eq!(error.status, StatusCode::CONFLICT);
    assert_eq!(
        error.message,
        "Changing a registered project root is not supported. Import the other directory as a new project."
    );
}

#[cfg(windows)]
#[test]
fn normalized_project_roots_ignore_windows_extended_path_prefixes() {
    assert_eq!(
        normalized_path_key(r"\\?\D:\codex\APS"),
        normalized_path_key(r"D:\codex\APS")
    );
    assert_eq!(
        normalized_path_key(r"\\?\UNC\server\share\APS"),
        normalized_path_key(r"\\server\share\APS")
    );
}

fn insert_test_project(
    ui_state: &mut Value,
    project_id: &str,
    name: &str,
    last_conversation_id: Option<&str>,
) {
    let mut project = project_record_value(
        project_id,
        name,
        &format!("D:\\codex\\{name}"),
        None,
        "created",
        None,
        100,
    );
    project["lastConversationId"] = last_conversation_id.map_or(Value::Null, |id| json!(id));
    projects_by_id_mut(ui_state)
        .expect("project registry")
        .insert(project_id.to_string(), project.clone());
    sync_project_compatibility_folder(ui_state, &project).expect("compatibility folder");
}

#[test]
fn moving_a_conversation_cleans_the_previous_project_state_atomically() {
    let mut ui_state = test_ui_state();
    insert_test_project(&mut ui_state, "prj_first", "First", Some("thread-1"));
    insert_test_project(&mut ui_state, "prj_second", "Second", None);
    ui_state["projectRegistry"]["projectIdByThreadId"]["thread-1"] = json!("prj_first");
    ui_state["sessionMetaByThreadId"]["thread-1"] = json!({
        "pinned": false,
        "tags": ["First", "keep"]
    });

    let project = attach_project_conversation_state(&mut ui_state, "prj_second", "thread-1", 200)
        .expect("conversation should move");

    assert_eq!(
        ui_state["projectRegistry"]["projectIdByThreadId"]["thread-1"],
        json!("prj_second")
    );
    assert_eq!(
        ui_state["sessionMetaByThreadId"]["thread-1"]["tags"],
        json!(["keep", "Second"])
    );
    assert_eq!(
        ui_state["projectRegistry"]["projectsById"]["prj_first"]["lastConversationId"],
        Value::Null
    );
    assert_eq!(
        ui_state["sessionFoldersByName"]["First"]["lastSessionId"],
        Value::Null
    );
    assert_eq!(project["lastConversationId"], json!("thread-1"));
}

#[test]
fn last_conversation_must_be_bound_to_the_same_project() {
    let mut ui_state = test_ui_state();
    insert_test_project(&mut ui_state, "prj_first", "First", None);
    insert_test_project(&mut ui_state, "prj_second", "Second", None);
    ui_state["projectRegistry"]["projectIdByThreadId"]["thread-1"] = json!("prj_first");

    assert!(validate_project_last_conversation_binding(&ui_state, "prj_first", "thread-1").is_ok());
    assert!(
        validate_project_last_conversation_binding(&ui_state, "prj_second", "thread-1").is_err()
    );
    assert!(validate_project_last_conversation_binding(&ui_state, "prj_first", "missing").is_err());
}

#[test]
fn detaching_the_last_conversation_clears_the_project_preference() {
    let mut ui_state = test_ui_state();
    insert_test_project(&mut ui_state, "prj_first", "First", Some("thread-1"));
    ui_state["projectRegistry"]["projectIdByThreadId"]["thread-1"] = json!("prj_first");
    ui_state["sessionMetaByThreadId"]["thread-1"] = json!({
        "pinned": false,
        "tags": ["First", "keep"]
    });

    detach_project_conversation_state(&mut ui_state, "prj_first", "thread-1", 200)
        .expect("conversation should detach");

    assert_eq!(
        ui_state["projectRegistry"]["projectIdByThreadId"].get("thread-1"),
        None
    );
    assert_eq!(
        ui_state["projectRegistry"]["projectsById"]["prj_first"]["lastConversationId"],
        Value::Null
    );
    assert_eq!(
        ui_state["sessionMetaByThreadId"]["thread-1"]["tags"],
        json!(["keep"])
    );
    assert_eq!(
        ui_state["sessionFoldersByName"]["First"]["lastSessionId"],
        Value::Null
    );
}

#[test]
fn archiving_a_project_unfiles_its_conversations_and_removes_compatibility_state() {
    let mut ui_state = test_ui_state();
    insert_test_project(&mut ui_state, "prj_first", "First", Some("thread-1"));
    insert_test_project(&mut ui_state, "prj_second", "Second", Some("thread-3"));
    ui_state["projectRegistry"]["projectsById"]["prj_first"]["aliases"] = json!(["First Legacy"]);
    ui_state["projectRegistry"]["projectIdByThreadId"] = json!({
        "thread-1": "prj_first",
        "thread-2": "prj_first",
        "thread-3": "prj_second"
    });
    ui_state["sessionMetaByThreadId"] = json!({
        "thread-1": { "pinned": false, "tags": ["First", "keep"] },
        "thread-2": { "pinned": false, "tags": ["First Legacy"] },
        "thread-3": { "pinned": false, "tags": ["Second"] }
    });
    ui_state["sessionFoldersByName"]["First Legacy"] = json!({
        "projectId": "prj_first",
        "name": "First Legacy"
    });

    let project = archive_project_conversation_state(&mut ui_state, "prj_first", 200)
        .expect("project should archive");

    assert_eq!(project["status"], json!("archived"));
    assert_eq!(project["lastConversationId"], Value::Null);
    assert_eq!(
        ui_state["projectRegistry"]["projectIdByThreadId"],
        json!({ "thread-3": "prj_second" })
    );
    assert_eq!(
        ui_state["sessionMetaByThreadId"]["thread-1"]["tags"],
        json!(["keep"])
    );
    assert_eq!(
        ui_state["sessionMetaByThreadId"]["thread-2"]["tags"],
        json!([])
    );
    assert!(ui_state["sessionFoldersByName"].get("First").is_none());
    assert!(
        ui_state["sessionFoldersByName"]
            .get("First Legacy")
            .is_none()
    );
    assert!(ui_state["sessionFoldersByName"].get("Second").is_some());
}
