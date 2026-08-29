use super::*;

fn test_root(label: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!("codex-webui-{label}-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create test project root");
    std::fs::canonicalize(root).expect("canonical test project root")
}

fn allowed_roots(root: &Path) -> Vec<PathBuf> {
    vec![std::fs::canonicalize(root).expect("canonical test root")]
}

fn project(root: &Path, project_id: &str, name: &str) -> Value {
    let root = root.display().to_string();
    json!({
        "projectId": project_id,
        "name": name,
        "rootPath": root,
        "repositoryRoot": root
    })
}

async fn write_manifest(project: &Value, roots: &[PathBuf]) {
    let update = project_manifest_file_update(project, roots).expect("manifest update");
    write_text_file_safely(&update.path, &update.content, &update.allowed_roots)
        .await
        .expect("write manifest");
}

fn candidate(root: &Path, name: &str) -> Value {
    json!({
        "candidateKey": format!("folder:{}", name.to_lowercase()),
        "source": "sessionFolder",
        "name": name,
        "rootPath": root.display().to_string(),
        "repositoryRoot": Value::Null,
        "conversationIds": [],
        "status": "ready",
        "existingProjectId": Value::Null,
        "warnings": []
    })
}

#[tokio::test]
async fn create_writes_the_complete_authoritative_manifest() {
    let root = test_root("manifest-create");
    let roots = allowed_roots(&root);
    let project = project(&root, "prj_create", "Created");

    write_manifest(&project, &roots).await;

    assert_eq!(
        read_project_manifest(&root.display().to_string(), &roots).await,
        ProjectManifestRead::Valid(ProjectManifest {
            schema_version: 2,
            project_id: "prj_create".to_string(),
            name: "Created".to_string(),
            root_path: root.display().to_string(),
            repository_root: Some(root.display().to_string()),
        })
    );
    std::fs::remove_dir_all(root).expect("remove test project root");
}

#[tokio::test]
async fn rename_rewrites_the_manifest_without_changing_identity() {
    let root = test_root("manifest-rename");
    let roots = allowed_roots(&root);
    write_manifest(&project(&root, "prj_rename", "Before"), &roots).await;

    write_manifest(&project(&root, "prj_rename", "After"), &roots).await;

    assert_eq!(
        read_project_manifest(&root.display().to_string(), &roots).await,
        ProjectManifestRead::Valid(ProjectManifest {
            schema_version: 2,
            project_id: "prj_rename".to_string(),
            name: "After".to_string(),
            root_path: root.display().to_string(),
            repository_root: Some(root.display().to_string()),
        })
    );
    std::fs::remove_dir_all(root).expect("remove test project root");
}

#[tokio::test]
async fn preview_recovers_manifest_identity_and_recognizes_a_rename() {
    let root = test_root("manifest-recovery");
    let roots = allowed_roots(&root);
    write_manifest(&project(&root, "prj_recovered", "Renamed"), &roots).await;
    let mut recovered = vec![candidate(&root, "Legacy")];

    enrich_project_candidates_with_manifests(&mut recovered, &[], &roots).await;

    assert_eq!(recovered[0]["status"], json!("ready"));
    assert_eq!(recovered[0]["proposedProjectId"], json!("prj_recovered"));
    assert_eq!(recovered[0]["name"], json!("Renamed"));

    let mut renamed = vec![candidate(&root, "Legacy")];
    let registered = vec![project(&root, "prj_recovered", "Old name")];
    enrich_project_candidates_with_manifests(&mut renamed, &registered, &roots).await;

    assert_eq!(renamed[0]["status"], json!("alreadyImported"));
    assert_eq!(renamed[0]["existingProjectId"], json!("prj_recovered"));
    assert_eq!(
        renamed[0]["warnings"],
        json!(["The manifest projectId matches a renamed registered project."])
    );
    std::fs::remove_dir_all(root).expect("remove test project root");
}

#[tokio::test]
async fn preview_blocks_identity_directory_conflicts_and_damaged_manifests() {
    let parent = test_root("manifest-conflicts");
    let first = parent.join("first");
    let second = parent.join("second");
    let damaged = parent.join("damaged");
    std::fs::create_dir_all(&first).expect("create first project");
    std::fs::create_dir_all(&second).expect("create second project");
    std::fs::create_dir_all(damaged.join(".forgeos")).expect("create damaged metadata");
    let roots = allowed_roots(&parent);
    write_manifest(&project(&first, "prj_duplicate", "First"), &roots).await;
    write_manifest(&project(&second, "prj_duplicate", "Second"), &roots).await;
    std::fs::write(damaged.join(".forgeos").join("project.json"), b"{broken")
        .expect("write damaged manifest");
    let mut candidates = vec![
        candidate(&first, "First"),
        candidate(&second, "Second"),
        candidate(&damaged, "Damaged"),
    ];

    enrich_project_candidates_with_manifests(&mut candidates, &[], &roots).await;

    assert_eq!(candidates[0]["status"], json!("conflict"));
    assert_eq!(
        candidates[0]["conflicts"][0]["kind"],
        json!("projectIdRootMismatch")
    );
    assert_eq!(candidates[1]["status"], json!("conflict"));
    assert_eq!(candidates[2]["manifestStatus"], json!("corrupt"));
    assert_eq!(
        candidates[2]["conflicts"][0]["kind"],
        json!("corruptManifest")
    );

    let mut root_conflict = vec![candidate(&first, "First")];
    let registered = vec![project(&first, "prj_other", "Other")];
    enrich_project_candidates_with_manifests(&mut root_conflict, &registered, &roots).await;
    assert_eq!(
        root_conflict[0]["conflicts"][0]["kind"],
        json!("rootProjectIdMismatch")
    );
    std::fs::remove_dir_all(parent).expect("remove test project root");
}

#[tokio::test]
async fn manifest_reader_rejects_oversized_and_non_regular_files() {
    let parent = test_root("manifest-bounds");
    let oversized = parent.join("oversized");
    let non_regular = parent.join("non-regular");
    std::fs::create_dir_all(oversized.join(".forgeos")).expect("create oversized metadata");
    std::fs::create_dir_all(non_regular.join(".forgeos").join("project.json"))
        .expect("create non-regular manifest");
    std::fs::write(
        oversized.join(".forgeos").join("project.json"),
        vec![b' '; PROJECT_MANIFEST_MAX_BYTES as usize + 1],
    )
    .expect("write oversized manifest");
    let roots = allowed_roots(&parent);

    assert_eq!(
        read_project_manifest(&oversized.display().to_string(), &roots).await,
        ProjectManifestRead::Corrupt
    );
    assert_eq!(
        read_project_manifest(&non_regular.display().to_string(), &roots).await,
        ProjectManifestRead::Corrupt
    );
    std::fs::remove_dir_all(parent).expect("remove test project root");
}

#[tokio::test]
async fn manifest_write_failure_does_not_pollute_the_registry_value() {
    let root = test_root("manifest-failure");
    let roots = allowed_roots(&root);
    std::fs::write(root.join(".forgeos"), b"not a directory")
        .expect("create blocking metadata file");
    let original = json!({ "projectRegistry": { "projectsById": {} } });
    let mut current = original.clone();
    let next = json!({
        "projectRegistry": {
            "projectsById": { "prj_failed": project(&root, "prj_failed", "Failed") }
        }
    });
    let update = project_manifest_file_update(&project(&root, "prj_failed", "Failed"), &roots)
        .expect("manifest update");

    let result =
        commit_value_and_text_file_updates(&mut current, next, vec![update], |_| async { Ok(()) })
            .await;

    assert!(result.is_err());
    assert_eq!(current, original);
    std::fs::remove_dir_all(root).expect("remove test project root");
}

#[tokio::test]
async fn ui_state_persistence_failure_rolls_back_every_project_manifest() {
    let parent = test_root("manifest-multi-project-rollback");
    let first = parent.join("first");
    let second = parent.join("second");
    std::fs::create_dir_all(first.join(".forgeos")).expect("create first metadata directory");
    std::fs::create_dir_all(second.join(".forgeos")).expect("create second metadata directory");
    let first_manifest = first.join(".forgeos").join("project.json");
    let second_manifest = second.join(".forgeos").join("project.json");
    let first_before = "{\"projectId\":\"prj_first_before\"}\n";
    let second_before = "{\"projectId\":\"prj_second_before\"}\n";
    std::fs::write(&first_manifest, first_before).expect("write first original manifest");
    std::fs::write(&second_manifest, second_before).expect("write second original manifest");
    let roots = allowed_roots(&parent);
    let updates = vec![
        project_manifest_file_update(&project(&first, "prj_first", "First"), &roots)
            .expect("first manifest update"),
        project_manifest_file_update(&project(&second, "prj_second", "Second"), &roots)
            .expect("second manifest update"),
    ];
    let original = json!({ "projectRegistry": { "projectsById": {} } });
    let mut current = original.clone();
    let next = json!({
        "projectRegistry": {
            "projectsById": {
                "prj_first": project(&first, "prj_first", "First"),
                "prj_second": project(&second, "prj_second", "Second")
            }
        }
    });

    let result = commit_value_and_text_file_updates(&mut current, next, updates, |_| async {
        Err(anyhow!("injected UI-state persistence failure"))
    })
    .await;

    assert!(
        result
            .unwrap_err()
            .to_string()
            .contains("injected UI-state persistence failure")
    );
    assert_eq!(current, original);
    assert_eq!(
        std::fs::read_to_string(first_manifest).expect("read rolled-back first manifest"),
        first_before
    );
    assert_eq!(
        std::fs::read_to_string(second_manifest).expect("read rolled-back second manifest"),
        second_before
    );
    std::fs::remove_dir_all(parent).expect("remove test project root");
}

#[test]
fn ordinary_editor_detection_covers_missing_legacy_and_corrupt_manifests() {
    assert!(is_project_manifest_path(Path::new(
        "project/.forgeos/project.json"
    )));
    assert!(!is_project_manifest_path(Path::new("project/project.json")));
}
