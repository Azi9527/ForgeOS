use super::*;

fn owner_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Owner,
        profile_id: "default".to_string(),
    }
}

fn admin_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Admin,
        profile_id: "default".to_string(),
    }
}

fn viewer_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Viewer,
        profile_id: "default".to_string(),
    }
}

fn successful_command() -> &'static str {
    if cfg!(windows) {
        "Write-Output 'validation-ok'"
    } else {
        "printf 'validation-ok\\n'"
    }
}

fn failing_command() -> &'static str {
    if cfg!(windows) {
        "Write-Output 'validation-failed'; exit 7"
    } else {
        "printf 'validation-failed\\n'; exit 7"
    }
}

fn long_running_command() -> &'static str {
    if cfg!(windows) {
        "Start-Sleep -Seconds 30"
    } else {
        "sleep 30"
    }
}

fn check(id: &str, command: &str, required: bool) -> ValidationCheckConfig {
    ValidationCheckConfig {
        id: id.to_string(),
        label: id.to_string(),
        command: command.to_string(),
        required,
    }
}

async fn state_with_project(label: &str, initialize_git: bool) -> (AppState, PathBuf, String) {
    let root =
        std::env::temp_dir().join(format!("codex-webui-validation-{label}-{}", Uuid::new_v4()));
    tokio_fs::create_dir_all(&root).await.unwrap();
    if initialize_git {
        crate::main_tests::init_test_git_repo(&root);
    }
    let state =
        crate::main_tests::test_state(root.clone(), vec![root.clone()], root.join(".codex"));
    let project_id = format!("prj_{}", Uuid::new_v4().simple());
    let project_id_for_state = project_id.clone();
    let root_path = root.display().to_string();
    with_ui_state_write(&state, "default", move |ui_state| {
        ui_state["projectRegistry"]["projectsById"]
            .as_object_mut()
            .unwrap()
            .insert(
                project_id_for_state.clone(),
                json!({
                    "schemaVersion": 2,
                    "projectId": project_id_for_state,
                    "name": "Validation Authority Test",
                    "rootPath": root_path,
                    "repositoryRoot": if initialize_git { json!(root_path) } else { Value::Null },
                    "status": "active",
                    "pinned": false,
                    "settings": { "model": Value::Null },
                    "aliases": [],
                    "source": "created",
                    "legacyName": Value::Null,
                    "lastConversationId": Value::Null,
                    "lastOpenedAt": Value::Null,
                    "createdAt": now_unix_ms(),
                    "updatedAt": now_unix_ms(),
                    "revision": 1
                }),
            );
        Ok(())
    })
    .await
    .unwrap();
    (state, root, project_id)
}

async fn save_checks(state: &AppState, project_id: &str, checks: Value) -> Value {
    save_project_validation_payload(
        state,
        &owner_auth(),
        json!({
            "projectId": project_id,
            "checks": checks,
            "expectedRevision": 0
        }),
    )
    .await
    .unwrap()
}

#[test]
fn validation_run_accepts_only_authoritative_inputs() {
    assert_eq!(
        require_validation_run_params(&json!({
            "projectId": "prj_test",
            "expectedRevision": 4
        }))
        .unwrap(),
        ("prj_test".to_string(), 4)
    );
    let error = require_validation_run_params(&json!({
        "projectId": "prj_test",
        "expectedRevision": 4,
        "checks": []
    }))
    .unwrap_err();
    assert_eq!(error.status, StatusCode::BAD_REQUEST);
    assert!(error.message.contains("checks"));
}

#[tokio::test]
async fn dedicated_owner_mode_blocks_admin_validation_and_allows_owner() {
    let (mut state, root, project_id) = state_with_project("dedicated-owner", false).await;
    assert!(require_validation_role(&state, &admin_auth()).is_ok());
    for method in [
        "projectLifecycle/validation/save",
        "projectLifecycle/validation/run",
        "projectLifecycle/validation/cancel",
    ] {
        assert!(authorize_ws_method(&state.config, UserRole::Admin, method, &json!({})).is_ok());
    }
    let mut config = (*state.config).clone();
    config.require_owner_role = true;
    state.config = Arc::new(config);
    let save_params = json!({
        "projectId": project_id,
        "expectedRevision": 0,
        "checks": [{
            "id": "build",
            "label": "Build",
            "command": successful_command(),
            "required": true
        }]
    });

    for method in [
        "projectLifecycle/validation/save",
        "projectLifecycle/validation/run",
        "projectLifecycle/validation/cancel",
    ] {
        assert!(
            authorize_ws_method(&state.config, UserRole::Admin, method, &json!({}))
                .unwrap_err()
                .to_string()
                .contains("OWNER_REQUIRED")
        );
        assert!(authorize_ws_method(&state.config, UserRole::Owner, method, &json!({})).is_ok());
    }
    assert_eq!(
        save_project_validation_payload(&state, &admin_auth(), save_params.clone())
            .await
            .unwrap_err()
            .status,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        run_project_validation_payload(
            &state,
            &admin_auth(),
            json!({ "projectId": project_id, "expectedRevision": 0 }),
        )
        .await
        .unwrap_err()
        .status,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        cancel_project_validation_payload(
            &state,
            &admin_auth(),
            json!({ "projectId": project_id }),
        )
        .await
        .unwrap_err()
        .status,
        StatusCode::FORBIDDEN
    );

    let saved = save_project_validation_payload(&state, &owner_auth(), save_params)
        .await
        .unwrap();
    let completed = run_project_validation_payload(
        &state,
        &owner_auth(),
        json!({
            "projectId": project_id,
            "expectedRevision": saved["revision"]
        }),
    )
    .await
    .unwrap();
    assert_eq!(
        completed["validation"]["runs"][0]["status"],
        json!("passed")
    );
    assert_eq!(
        cancel_project_validation_payload(
            &state,
            &owner_auth(),
            json!({ "projectId": project_id }),
        )
        .await
        .unwrap_err()
        .status,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        require_validation_role(&state, &viewer_auth())
            .unwrap_err()
            .status,
        StatusCode::FORBIDDEN
    );
    assert!(require_validation_role(&state, &owner_auth()).is_ok());
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[test]
fn validation_output_is_utf8_safe_and_strictly_bounded() {
    let output = bounded_output_tail(&"界".repeat(MAX_EVIDENCE_OUTPUT_BYTES));
    assert!(output.len() <= MAX_EVIDENCE_OUTPUT_BYTES);
    assert!(output.starts_with("… earlier output truncated …"));
    assert!(std::str::from_utf8(output.as_bytes()).is_ok());
}

#[test]
fn validation_output_redacts_credentials_before_digesting_evidence() {
    let mut evidence = pending_validation_evidence(&check("secret", "ignored", true));
    apply_command_result(
        &mut evidence,
        ValidationCommandResult {
            status: ValidationCommandStatus::Failed,
            exit_code: Some(1),
            duration_ms: 10,
            output: "Bearer top-secret sk-example password=hunter2 api_key=private".to_string(),
        },
    );
    let output = evidence["output"].as_str().unwrap();
    assert!(!output.contains("top-secret"));
    assert!(!output.contains("sk-example"));
    assert!(!output.contains("hunter2"));
    assert!(!output.contains("private"));
    assert!(output.contains("[redacted]"));

    let run = finalize_validation_run(json!({ "checks": [evidence] })).unwrap();
    assert_eq!(run["evidenceDigest"].as_str().map(str::len), Some(64));
}

#[tokio::test]
async fn required_check_failure_stops_later_commands() {
    let root = std::env::temp_dir().join(format!(
        "codex-webui-validation-sequence-{}",
        Uuid::new_v4()
    ));
    tokio_fs::create_dir_all(&root).await.unwrap();
    let evidence = execute_validation_checks(
        &root,
        &[
            check("required", failing_command(), true),
            check("not-run", successful_command(), true),
        ],
        &CancellationToken::new(),
    )
    .await;
    assert_eq!(
        evidence
            .iter()
            .map(|entry| entry.get("status").and_then(Value::as_str))
            .collect::<Vec<_>>(),
        vec![Some("failed"), Some("pending")]
    );
    assert_eq!(evidence[0]["exitCode"], json!(7));
    assert!(
        evidence[0]["output"]
            .as_str()
            .unwrap()
            .contains("validation-failed")
    );
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[tokio::test]
async fn gateway_executes_saved_checks_and_atomically_records_server_evidence() {
    let (state, root, project_id) = state_with_project("authority", true).await;
    let saved = save_checks(
        &state,
        &project_id,
        json!([{
            "id": "build",
            "label": "Build",
            "command": successful_command(),
            "required": true
        }]),
    )
    .await;
    let result = run_project_validation_payload(
        &state,
        &owner_auth(),
        json!({
            "projectId": project_id,
            "expectedRevision": saved["revision"]
        }),
    )
    .await
    .unwrap();

    assert_eq!(result["revision"], json!(3));
    let run = &result["validation"]["runs"][0];
    assert_eq!(run["status"], json!("passed"));
    assert_eq!(
        run["operator"],
        json!({ "profileId": "default", "role": "owner" })
    );
    assert_eq!(run["checks"][0]["exitCode"], json!(0));
    assert!(
        run["checks"][0]["output"]
            .as_str()
            .unwrap()
            .contains("validation-ok")
    );
    assert!(
        run["branch"]
            .as_str()
            .is_some_and(|branch| !branch.is_empty())
    );
    assert_eq!(run["commit"].as_str().map(str::len), Some(40));
    assert_eq!(run["configurationDigest"].as_str().map(str::len), Some(64));
    assert_eq!(run["evidenceDigest"].as_str().map(str::len), Some(64));
    assert!(run["finishedAt"].as_u64().unwrap() >= run["startedAt"].as_u64().unwrap());
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[tokio::test]
async fn lifecycle_read_recovers_gateway_restart_running_evidence_as_interrupted() {
    let (state, root, project_id) = state_with_project("interrupted", false).await;
    let saved = save_checks(
        &state,
        &project_id,
        json!([{
            "id": "build",
            "label": "Build",
            "command": successful_command(),
            "required": true
        }]),
    )
    .await;
    let running = finalize_validation_run(json!({
        "id": "validation_interrupted",
        "startedAt": 10,
        "finishedAt": Value::Null,
        "status": "running",
        "rootPath": root.display().to_string(),
        "branch": Value::Null,
        "commit": Value::Null,
        "configurationDigest": "a".repeat(64),
        "checks": [{
            "id": "build",
            "label": "build",
            "command": successful_command(),
            "required": true,
            "status": "running",
            "exitCode": Value::Null,
            "durationMs": Value::Null,
            "output": "Bearer recovery-secret-token"
        }],
        "operator": auth_operator(&owner_auth())
    }))
    .unwrap();
    update_project_lifecycle(
        &state,
        "default",
        json!({
            "projectId": project_id,
            "expectedRevision": saved["revision"]
        }),
        move |lifecycle, _params, _project| {
            lifecycle["validation"]["runs"] = json!([running]);
            Ok(())
        },
    )
    .await
    .unwrap();

    let recovered =
        get_project_lifecycle_payload(&state, "default", json!({ "projectId": project_id }))
            .await
            .unwrap();
    let run = &recovered["validation"]["runs"][0];
    assert_eq!(run["status"], json!("interrupted"));
    assert_eq!(run["checks"][0]["status"], json!("cancelled"));
    assert!(
        run["checks"][0]["output"]
            .as_str()
            .unwrap()
            .contains("Gateway execution was interrupted")
    );
    assert!(!run.to_string().contains("recovery-secret-token"));
    assert_eq!(run["evidenceDigest"].as_str().map(str::len), Some(64));
    let audit = list_audit_log(&state.config, 20).await.unwrap();
    assert!(audit["entries"].as_array().unwrap().iter().any(|entry| {
        entry["role"] == json!("system")
            && entry["method"] == json!("projectLifecycle/validation/recover")
            && entry["target"] == json!(project_id)
            && entry["ok"] == json!(true)
    }));
    let _ = tokio_fs::remove_dir_all(root).await;
}

#[tokio::test]
async fn active_gateway_validation_can_be_cancelled_and_is_recorded_as_cancelled() {
    let (state, root, project_id) = state_with_project("cancel", false).await;
    let saved = save_checks(
        &state,
        &project_id,
        json!([{
            "id": "slow",
            "label": "Slow",
            "command": long_running_command(),
            "required": true
        }]),
    )
    .await;
    let run_state = state.clone();
    let run_project_id = project_id.clone();
    let expected_revision = saved["revision"].as_u64().unwrap();
    let run = tokio::spawn(async move {
        run_project_validation_payload(
            &run_state,
            &owner_auth(),
            json!({
                "projectId": run_project_id,
                "expectedRevision": expected_revision
            }),
        )
        .await
    });

    let key = active_validation_key("default", &project_id);
    for _ in 0..100 {
        if active_validations().lock().unwrap().contains_key(&key) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(active_validations().lock().unwrap().contains_key(&key));
    let running = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let payload = get_project_lifecycle_payload(
                &state,
                "default",
                json!({ "projectId": project_id }),
            )
            .await
            .unwrap();
            if payload["validation"]["runs"][0]["status"] == json!("running") {
                break payload;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("running validation evidence should become visible");
    assert_eq!(running["validation"]["runs"][0]["status"], json!("running"));
    assert_eq!(
        running["validation"]["runs"][0]["configurationDigest"]
            .as_str()
            .map(str::len),
        Some(64)
    );
    save_project_validation_payload(
        &state,
        &owner_auth(),
        json!({
            "projectId": project_id,
            "expectedRevision": running["revision"],
            "checks": [{
                "id": "replacement",
                "label": "Replacement",
                "command": successful_command(),
                "required": true
            }]
        }),
    )
    .await
    .unwrap();
    let cancelled = cancel_project_validation_payload(
        &state,
        &owner_auth(),
        json!({ "projectId": project_id }),
    )
    .await
    .unwrap();
    assert_eq!(cancelled["ok"], json!(true));

    let result = tokio::time::timeout(Duration::from_secs(10), run)
        .await
        .expect("cancelled validation should stop promptly")
        .unwrap()
        .unwrap();
    let evidence = &result["validation"]["runs"][0];
    assert_eq!(evidence["status"], json!("cancelled"));
    assert_eq!(evidence["checks"][0]["status"], json!("cancelled"));
    assert_eq!(evidence["checks"][0]["exitCode"], Value::Null);
    assert_eq!(
        evidence["checks"][0]["command"],
        json!(long_running_command())
    );
    assert_eq!(
        result["validation"]["checks"][0]["id"],
        json!("replacement")
    );
    assert_eq!(evidence["evidenceDigest"].as_str().map(str::len), Some(64));
    let _ = tokio_fs::remove_dir_all(root).await;
}
