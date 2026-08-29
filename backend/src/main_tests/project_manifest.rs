use super::*;

#[tokio::test]
async fn registry_create_and_rename_atomically_own_the_project_manifest() {
    let sandbox = unique_test_dir("project-manifest-registry");
    let workspace = sandbox.join("workspace");
    let codex_home = sandbox.join("codex-home");
    fs::create_dir_all(&workspace).expect("create workspace");
    fs::create_dir_all(&codex_home).expect("create codex home");
    let state = test_state(workspace.clone(), vec![workspace.clone()], codex_home);
    let requested_root = workspace.join("Created");

    let created = create_project_v2_payload(
        &state,
        "default",
        json!({
            "name": "Created",
            "rootPath": requested_root,
            "repositoryRoot": Value::Null
        }),
    )
    .await
    .expect("create project");
    let created_project = created.get("project").expect("created project payload");
    let project_id = created_project
        .get("projectId")
        .and_then(Value::as_str)
        .expect("project id")
        .to_string();
    let root_path = created_project
        .get("rootPath")
        .and_then(Value::as_str)
        .expect("project root")
        .to_string();
    let manifest_path = Path::new(&root_path).join(".forgeos").join("project.json");
    let created_manifest: Value = serde_json::from_slice(
        &tokio_fs::read(&manifest_path)
            .await
            .expect("read created manifest"),
    )
    .expect("parse created manifest");
    assert_eq!(
        created_manifest,
        json!({
            "schemaVersion": 2,
            "projectId": project_id.clone(),
            "name": "Created",
            "rootPath": root_path.clone(),
            "repositoryRoot": Value::Null
        })
    );

    let updated = update_project_v2_payload(
        &state,
        "default",
        json!({
            "projectId": project_id.clone(),
            "name": "Renamed",
            "revision": created_project.get("revision").and_then(Value::as_u64)
        }),
    )
    .await
    .expect("rename project");
    assert_eq!(updated["project"]["projectId"], json!(project_id.clone()));
    let renamed_manifest: Value = serde_json::from_slice(
        &tokio_fs::read(&manifest_path)
            .await
            .expect("read renamed manifest"),
    )
    .expect("parse renamed manifest");
    assert_eq!(
        renamed_manifest,
        json!({
            "schemaVersion": 2,
            "projectId": project_id,
            "name": "Renamed",
            "rootPath": root_path,
            "repositoryRoot": Value::Null
        })
    );

    let error = write_editable_file_payload(
        &state,
        "default",
        &manifest_path.display().to_string(),
        "{}",
    )
    .await
    .expect_err("ordinary editor must not overwrite a project manifest");
    assert_eq!(error.status, StatusCode::FORBIDDEN);
    let after_rejected_edit: Value = serde_json::from_slice(
        &tokio_fs::read(&manifest_path)
            .await
            .expect("read protected manifest"),
    )
    .expect("parse protected manifest");
    assert_eq!(after_rejected_edit, renamed_manifest);

    fs::remove_dir_all(sandbox).expect("remove test sandbox");
}
