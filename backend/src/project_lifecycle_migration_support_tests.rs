use super::*;

fn project() -> Value {
    json!({
        "projectId": "prj_forgeos",
        "name": "ForgeOS Next",
        "legacyName": "ForgeOS",
        "aliases": ["ForgeOS Legacy"]
    })
}

fn ui_state() -> Value {
    json!({
        "projectRegistry": {
            "projectsById": { "prj_forgeos": project() }
        },
        "projectLifecycleByName": {},
        "projectLifecycleById": {},
        "projectLifecycleMigration": {
            "schemaVersion": 1,
            "commitsByProjectId": {}
        }
    })
}

fn persisted_test_root(label: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!(
        "codex-webui-lifecycle-migration-{label}-{}",
        Uuid::new_v4()
    ));
    std::fs::create_dir_all(&root).expect("create migration test root");
    root
}

fn persisted_test_state(root: &Path) -> AppState {
    crate::main_tests::test_state(
        root.to_path_buf(),
        vec![root.to_path_buf()],
        root.join(".codex"),
    )
}

fn persisted_project(root: &Path) -> Value {
    json!({
        "schemaVersion": 2,
        "projectId": "prj_forgeos",
        "name": "ForgeOS Next",
        "rootPath": root.display().to_string(),
        "repositoryRoot": Value::Null,
        "status": "active",
        "pinned": false,
        "settings": { "model": Value::Null },
        "aliases": ["ForgeOS Legacy"],
        "source": "migrated",
        "legacyName": "ForgeOS",
        "lastConversationId": Value::Null,
        "lastOpenedAt": Value::Null,
        "createdAt": 1,
        "updatedAt": 1,
        "revision": 1
    })
}

async fn seed_persisted_migration_state(
    state: &AppState,
    root: &Path,
    legacy: Value,
    current: Option<Value>,
) {
    let project = persisted_project(root);
    with_ui_state_write(state, "default", move |ui_state| {
        ui_state["projectRegistry"]["projectsById"]["prj_forgeos"] = project;
        ui_state["projectLifecycleByName"]["ForgeOS"] = legacy;
        if let Some(current) = current {
            ui_state["projectLifecycleById"]["prj_forgeos"] = current;
        }
        Ok(())
    })
    .await
    .expect("persist migration fixture");
}

async fn read_persisted_ui_state(state: &AppState) -> Value {
    let raw = tokio_fs::read_to_string(profile_ui_state_path(&state.config, "default"))
        .await
        .expect("read persisted ui state");
    serde_json::from_str(&raw).expect("parse persisted ui state")
}

#[test]
fn preview_finds_legacy_state_through_project_aliases() {
    let mut state = ui_state();
    state["projectLifecycleByName"]["ForgeOS"] = lifecycle_default("legacy-name-key", "ForgeOS");

    let preview = lifecycle_migration_payload(&state, "prj_forgeos").unwrap();

    assert_eq!(preview.get("status"), Some(&json!("ready")));
    assert_eq!(
        preview.pointer("/legacySources/0/projectName"),
        Some(&json!("ForgeOS"))
    );
    assert_eq!(preview.get("canMigrate"), Some(&json!(true)));
}

#[test]
fn preview_reports_conflict_when_id_and_name_records_diverge() {
    let mut state = ui_state();
    let mut legacy = lifecycle_default("legacy-name-key", "ForgeOS");
    legacy["validation"]["checks"] = json!([{ "id": "test" }]);
    state["projectLifecycleByName"]["ForgeOS"] = legacy;
    state["projectLifecycleById"]["prj_forgeos"] = lifecycle_default("prj_forgeos", "ForgeOS Next");

    let preview = lifecycle_migration_payload(&state, "prj_forgeos").unwrap();

    assert_eq!(preview.get("status"), Some(&json!("conflict")));
    assert_eq!(preview.get("canRollback"), Some(&json!(false)));
}

#[test]
fn interrupted_and_rolled_back_journals_are_visible_as_recovery_states() {
    let mut state = ui_state();
    state["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"] = json!({
        "status": "copying",
        "sourceProjectName": "ForgeOS"
    });
    let interrupted = lifecycle_migration_payload(&state, "prj_forgeos").unwrap();
    assert_eq!(interrupted.get("status"), Some(&json!("recoveryRequired")));
    assert_eq!(interrupted.get("canRecover"), Some(&json!(true)));

    state["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"]["status"] =
        json!("rolledBack");
    let rolled_back = lifecycle_migration_payload(&state, "prj_forgeos").unwrap();
    assert_eq!(rolled_back.get("status"), Some(&json!("rolledBack")));
    assert_eq!(rolled_back.get("canMigrate"), Some(&json!(true)));
}

#[test]
fn lifecycle_digest_ignores_identity_and_display_name_changes() {
    let first = lifecycle_default("prj_first", "ForgeOS");
    let mut second = first.clone();
    second["projectId"] = json!("prj_second");
    second["projectName"] = json!("ForgeOS Renamed");
    second["revision"] = json!(99);

    assert_eq!(
        lifecycle_content_digest(&first),
        lifecycle_content_digest(&second)
    );
}

#[tokio::test]
async fn prefer_legacy_commit_is_idempotent_and_survives_rollback_and_recovery() {
    let root = persisted_test_root("prefer-legacy");
    let state = persisted_test_state(&root);
    let mut legacy = lifecycle_default("legacy-name-key", "ForgeOS");
    legacy["revision"] = json!(4);
    legacy["validation"]["checks"] = json!([{
        "id": "legacy-check",
        "label": "Legacy check",
        "command": "legacy-command",
        "required": true
    }]);
    seed_persisted_migration_state(&state, &root, legacy, None).await;

    let committed = commit_project_lifecycle_migration_payload(
        &state,
        "default",
        json!({
            "projectId": "prj_forgeos",
            "sourceProjectName": "ForgeOS",
            "strategy": "preferLegacy"
        }),
    )
    .await
    .expect("commit preferLegacy migration");
    assert_eq!(committed["status"], json!("migrated"));
    assert_eq!(committed["current"]["revision"], json!(5));
    let migration_id = committed["commit"]["migrationId"].clone();
    let persisted = read_persisted_ui_state(&state).await;
    assert_eq!(
        persisted["projectLifecycleById"]["prj_forgeos"]["validation"]["checks"][0]["id"],
        json!("legacy-check")
    );
    assert_eq!(
        persisted["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"]["status"],
        json!("applied")
    );

    drop(state);
    let restarted = persisted_test_state(&root);
    let retried = commit_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({
            "projectId": "prj_forgeos",
            "sourceProjectName": "ForgeOS",
            "strategy": "preferLegacy"
        }),
    )
    .await
    .expect("retry committed migration after restart");
    assert_eq!(retried["current"]["revision"], json!(5));
    assert_eq!(retried["commit"]["migrationId"], migration_id);
    let persisted = read_persisted_ui_state(&restarted).await;
    assert_eq!(
        persisted["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"]["appliedRevision"],
        json!(5)
    );

    let rolled_back = rollback_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({ "projectId": "prj_forgeos" }),
    )
    .await
    .expect("roll back migration after restart");
    assert_eq!(rolled_back["status"], json!("rolledBack"));
    assert_eq!(rolled_back["current"], Value::Null);
    let persisted = read_persisted_ui_state(&restarted).await;
    assert!(
        persisted["projectLifecycleById"]
            .get("prj_forgeos")
            .is_none()
    );

    drop(restarted);
    let restarted = persisted_test_state(&root);
    let recovered = recover_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({ "projectId": "prj_forgeos" }),
    )
    .await
    .expect("recover rolled-back migration after restart");
    assert_eq!(recovered["status"], json!("migrated"));
    assert_eq!(recovered["current"]["revision"], json!(5));
    let persisted = read_persisted_ui_state(&restarted).await;
    assert_eq!(
        persisted["projectLifecycleById"]["prj_forgeos"]["validation"]["checks"][0]["id"],
        json!("legacy-check")
    );
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[tokio::test]
async fn keep_current_commit_preserves_state_and_rejects_stale_rollback_after_restart() {
    let root = persisted_test_root("keep-current");
    let state = persisted_test_state(&root);
    let mut legacy = lifecycle_default("legacy-name-key", "ForgeOS");
    legacy["revision"] = json!(3);
    legacy["validation"]["checks"] = json!([{
        "id": "legacy-check",
        "label": "Legacy check",
        "command": "legacy-command",
        "required": true
    }]);
    let mut current = lifecycle_default("prj_forgeos", "ForgeOS Next");
    current["revision"] = json!(9);
    current["validation"]["checks"] = json!([{
        "id": "current-check",
        "label": "Current check",
        "command": "current-command",
        "required": true
    }]);
    seed_persisted_migration_state(&state, &root, legacy, Some(current)).await;

    let committed = commit_project_lifecycle_migration_payload(
        &state,
        "default",
        json!({
            "projectId": "prj_forgeos",
            "sourceProjectName": "ForgeOS",
            "strategy": "keepCurrent"
        }),
    )
    .await
    .expect("commit keepCurrent migration");
    assert_eq!(committed["current"]["revision"], json!(10));
    let persisted = read_persisted_ui_state(&state).await;
    assert_eq!(
        persisted["projectLifecycleById"]["prj_forgeos"]["validation"]["checks"][0]["id"],
        json!("current-check")
    );

    update_project_lifecycle(
        &state,
        "default",
        json!({ "projectId": "prj_forgeos", "expectedRevision": 10 }),
        |lifecycle, _params, _project| {
            lifecycle["governance"]["notificationRoutes"]["deploymentFailed"] = json!(false);
            Ok(())
        },
    )
    .await
    .expect("write lifecycle data after migration");

    drop(state);
    let restarted = persisted_test_state(&root);
    let rollback = rollback_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({ "projectId": "prj_forgeos" }),
    )
    .await
    .expect_err("rollback must not discard a newer lifecycle revision");
    assert_eq!(rollback.status, StatusCode::CONFLICT);
    assert!(rollback.message.contains("discard newer data"));
    let persisted = read_persisted_ui_state(&restarted).await;
    assert_eq!(
        persisted["projectLifecycleById"]["prj_forgeos"]["revision"],
        json!(11)
    );
    assert_eq!(
        persisted["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"]["status"],
        json!("applied")
    );
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[tokio::test]
async fn persisted_copying_journal_recovers_after_restart() {
    let root = persisted_test_root("copying-recovery");
    let state = persisted_test_state(&root);
    let mut legacy = lifecycle_default("legacy-name-key", "ForgeOS");
    legacy["revision"] = json!(6);
    legacy["validation"]["checks"] = json!([{
        "id": "recovered-check",
        "label": "Recovered check",
        "command": "recovered-command",
        "required": true
    }]);
    seed_persisted_migration_state(&state, &root, legacy.clone(), None).await;
    with_ui_state_write(&state, "default", move |ui_state| {
        ui_state["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"] = json!({
            "migrationId": "migration_interrupted",
            "projectId": "prj_forgeos",
            "sourceProjectName": "ForgeOS",
            "strategy": "preferLegacy",
            "status": "copying",
            "startedAt": 10,
            "appliedAt": Value::Null,
            "rolledBackAt": Value::Null,
            "beforeSnapshot": Value::Null,
            "sourceSnapshot": legacy
        });
        Ok(())
    })
    .await
    .expect("persist interrupted migration journal");
    drop(state);

    let restarted = persisted_test_state(&root);
    let before = get_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({ "projectId": "prj_forgeos" }),
    )
    .await
    .expect("read interrupted migration after restart");
    assert_eq!(before["status"], json!("recoveryRequired"));
    let recovered = recover_project_lifecycle_migration_payload(
        &restarted,
        "default",
        json!({ "projectId": "prj_forgeos" }),
    )
    .await
    .expect("recover interrupted migration after restart");
    assert_eq!(recovered["status"], json!("migrated"));
    assert_eq!(recovered["current"]["revision"], json!(7));
    let persisted = read_persisted_ui_state(&restarted).await;
    assert_eq!(
        persisted["projectLifecycleMigration"]["commitsByProjectId"]["prj_forgeos"]["status"],
        json!("applied")
    );
    assert_eq!(
        persisted["projectLifecycleById"]["prj_forgeos"]["validation"]["checks"][0]["id"],
        json!("recovered-check")
    );
    let _ = tokio_fs::remove_dir_all(root).await;
}
