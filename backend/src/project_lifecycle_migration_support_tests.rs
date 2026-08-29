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
