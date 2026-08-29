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
