use super::*;

fn lifecycle_with_environment(environment: Value, release: Value) -> Value {
    json!({
        "operations": { "environments": [environment], "deployments": [] },
        "release": { "releases": [release] }
    })
}

#[test]
fn operation_params_reject_client_commands_and_results() {
    let params = json!({
        "projectId": "prj_test",
        "releaseId": "release-1",
        "environmentId": "staging",
        "expectedRevision": 4,
        "command": "untrusted",
        "exitCode": 0
    });
    let error = require_operation_params(
        &params,
        &["releaseId", "environmentId"],
        &[
            "projectId",
            "releaseId",
            "environmentId",
            "expectedRevision",
        ],
    )
    .unwrap_err();
    assert_eq!(error.status, StatusCode::BAD_REQUEST);

    let accepted = require_operation_params(
        &json!({
            "projectId": "prj_test",
            "environmentId": "staging",
            "expectedRevision": 4,
            "requestProfileId": "default"
        }),
        &["environmentId"],
        &["projectId", "environmentId", "expectedRevision"],
    )
    .unwrap();
    assert_eq!(
        accepted,
        ("prj_test".to_string(), 4, vec!["staging".to_string()])
    );
}

#[test]
fn deployment_plan_comes_only_from_a_matching_released_target() {
    let lifecycle = lifecycle_with_environment(
        json!({
            "id": "staging",
            "adapter": "githubActions",
            "githubRepository": "openai/forgeos",
            "githubWorkflow": "deploy.yml",
            "githubRef": "main"
        }),
        json!({
            "id": "release-1",
            "version": "1.2.3",
            "status": "released",
            "targetEnvironmentId": "staging"
        }),
    );
    assert_eq!(
        deployment_command(&lifecycle, "release-1", "staging").unwrap(),
        OperationCommand::GitHubActions {
            repository: "openai/forgeos".to_string(),
            workflow: "deploy.yml".to_string(),
            reference: "main".to_string(),
            version: "1.2.3".to_string()
        }
    );
    assert!(deployment_command(&lifecycle, "release-1", "production").is_err());

    let unsafe_adapter = lifecycle_with_environment(
        json!({
            "id": "staging",
            "adapter": "githubActions",
            "githubRepository": "openai/forgeos",
            "githubWorkflow": "--help",
            "githubRef": "main"
        }),
        json!({
            "id": "release-1",
            "version": "1.2.3",
            "status": "released",
            "targetEnvironmentId": "staging"
        }),
    );
    assert!(deployment_command(&unsafe_adapter, "release-1", "staging").is_err());
}

#[test]
fn operation_evidence_digest_is_server_derived() {
    let evidence = finalize_evidence(json!({
        "id": "deployment-1",
        "status": "succeeded",
        "exitCode": 0,
        "logs": "gateway output"
    }))
    .unwrap();
    assert_eq!(
        evidence
            .get("evidenceDigest")
            .and_then(Value::as_str)
            .map(str::len),
        Some(64)
    );
    let changed = finalize_evidence(json!({
        "id": "deployment-1",
        "status": "succeeded",
        "exitCode": 0,
        "logs": "different output"
    }))
    .unwrap();
    assert_ne!(evidence["evidenceDigest"], changed["evidenceDigest"]);
}

#[test]
fn only_process_local_operations_escape_interrupted_recovery() {
    let lifecycle = json!({
        "operations": {
            "deployments": [{ "id": "deployment-1", "status": "running" }],
            "environments": []
        }
    });
    assert!(has_interrupted_operations(&lifecycle));
    let active = ActiveOperation::begin("deployment-1");
    assert!(!has_interrupted_operations(&lifecycle));
    drop(active);
    assert!(has_interrupted_operations(&lifecycle));
}

#[tokio::test]
async fn local_operation_runs_in_the_gateway_working_directory() {
    let root =
        std::env::temp_dir().join(format!("codex-webui-project-operation-{}", Uuid::new_v4()));
    fs::create_dir_all(&root).unwrap();
    let script = if cfg!(windows) {
        "Write-Output gateway-operation"
    } else {
        "printf 'gateway-operation\\n'"
    };
    let result = run_operation_command(
        &root,
        &OperationCommand::Local(script.to_string()),
        Duration::from_secs(10),
    )
    .await;
    assert_eq!(result.exit_code, 0);
    assert_eq!(result.logs, "gateway-operation");
    fs::remove_dir_all(root).unwrap();
}
