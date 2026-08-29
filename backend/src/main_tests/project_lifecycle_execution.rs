use super::*;

fn local_script(output: &str) -> String {
    if cfg!(windows) {
        format!("Write-Output '{output}'")
    } else {
        format!("printf '{output}\\n'")
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn gateway_executes_deployments_and_health_checks_with_server_evidence() {
    let sandbox = unique_test_dir("project-lifecycle-execution");
    let workspace = sandbox.join("workspace");
    let codex_home = sandbox.join("codex-home");
    fs::create_dir_all(&workspace).unwrap();
    fs::create_dir_all(&codex_home).unwrap();
    let mut state = test_state(workspace.clone(), vec![workspace.clone()], codex_home);
    let project_id = "prj_execution";
    with_ui_state_write(&state, "default", |ui_state| {
        ui_state["projectRegistry"]["projectsById"][project_id] = json!({
            "projectId": project_id,
            "name": "Execution Project",
            "rootPath": workspace.display().to_string(),
            "status": "active"
        });
        ui_state["projectLifecycleById"][project_id] = json!({
            "projectId": project_id,
            "projectName": "Execution Project",
            "revision": 7,
            "updatedAt": 1,
            "validation": { "checks": [], "runs": [] },
            "release": {
                "artifacts": [],
                "releases": [{
                    "id": "release-1",
                    "version": "1.0.0",
                    "status": "released",
                    "targetEnvironmentId": "staging"
                }]
            },
            "operations": {
                "environments": [{
                    "id": "staging",
                    "name": "Staging",
                    "kind": "staging",
                    "adapter": "localCommand",
                    "deployCommand": local_script("deployment-from-gateway"),
                    "healthCommand": local_script("health-from-gateway"),
                    "health": "unknown",
                    "lastCheckedAt": Value::Null,
                    "lastHealthOutput": Value::Null,
                    "lastHealthCheck": Value::Null
                }],
                "deployments": []
            },
            "governance": {
                "approvalPolicy": {
                    "standardApprovals": 1,
                    "productionApprovals": 2
                },
                "artifactRetention": {
                    "maxArtifacts": 50,
                    "maxAgeDays": 180
                },
                "notificationRoutes": {
                    "approvalRequested": true,
                    "releaseCompleted": true,
                    "rollbackCompleted": true,
                    "deploymentFailed": true
                }
            }
        });
        Ok(())
    })
    .await
    .unwrap();

    let auth = AuthContext {
        role: UserRole::Admin,
        profile_id: "default".to_string(),
    };
    let deployed = run_project_deployment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "releaseId": "release-1",
            "environmentId": "staging",
            "expectedRevision": 7
        }),
    )
    .await
    .unwrap();
    let deployment = &deployed["operations"]["deployments"][0];
    assert_eq!(deployment["status"], json!("succeeded"));
    assert_eq!(deployment["exitCode"], json!(0));
    assert_eq!(deployment["logs"], json!("deployment-from-gateway"));
    assert_eq!(
        deployment["operator"],
        json!({ "profileId": "default", "role": "admin" })
    );
    assert_eq!(
        deployment["evidenceDigest"].as_str().map(str::len),
        Some(64)
    );

    let checked = check_project_environment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "environmentId": "staging",
            "expectedRevision": deployed["revision"]
        }),
    )
    .await
    .unwrap();
    let environment = &checked["operations"]["environments"][0];
    assert_eq!(environment["health"], json!("healthy"));
    assert_eq!(
        environment["lastHealthOutput"],
        json!("health-from-gateway")
    );
    assert_eq!(environment["lastHealthCheck"]["exitCode"], json!(0));
    assert_eq!(
        environment["lastHealthCheck"]["evidenceDigest"]
            .as_str()
            .map(str::len),
        Some(64)
    );

    let forged = save_project_operations_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": checked["revision"],
            "environments": checked["operations"]["environments"],
            "deployments": [{
                "id": "client-result",
                "releaseId": "release-1",
                "environmentId": "staging",
                "status": "succeeded",
                "exitCode": 0
            }]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(forged.status, StatusCode::CONFLICT);

    let legacy_client = save_project_operations_compat_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": checked["revision"],
            "environments": checked["operations"]["environments"],
            "deployments": [{
                "id": "client-result",
                "releaseId": "release-1",
                "environmentId": "staging",
                "status": "succeeded",
                "exitCode": 0
            }]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(legacy_client.status, StatusCode::CONFLICT);
    assert!(legacy_client.message.contains("client upgrade required"));

    let viewer = AuthContext {
        role: UserRole::Viewer,
        profile_id: "default".to_string(),
    };
    let forbidden = check_project_environment_payload(
        &state,
        &viewer,
        json!({
            "projectId": project_id,
            "environmentId": "staging",
            "expectedRevision": checked["revision"]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(forbidden.status, StatusCode::FORBIDDEN);

    let mut config = (*state.config).clone();
    config.owner_password = Some("owner-secret".to_string());
    state.config = Arc::new(config);
    let admin_local_health = check_project_environment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "environmentId": "staging",
            "expectedRevision": checked["revision"]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(admin_local_health.status, StatusCode::FORBIDDEN);
    let admin_local_deployment = run_project_deployment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "releaseId": "release-1",
            "environmentId": "staging",
            "expectedRevision": checked["revision"]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(admin_local_deployment.status, StatusCode::FORBIDDEN);

    let owner = AuthContext {
        role: UserRole::Owner,
        profile_id: "default".to_string(),
    };
    let owner_checked = check_project_environment_payload(
        &state,
        &owner,
        json!({
            "projectId": project_id,
            "environmentId": "staging",
            "expectedRevision": checked["revision"]
        }),
    )
    .await
    .unwrap();
    let owner_deployed = run_project_deployment_payload(
        &state,
        &owner,
        json!({
            "projectId": project_id,
            "releaseId": "release-1",
            "environmentId": "staging",
            "expectedRevision": owner_checked["revision"]
        }),
    )
    .await
    .unwrap();
    assert_eq!(
        owner_deployed["operations"]["deployments"][0]["status"],
        json!("succeeded")
    );

    with_ui_state_write(&state, "default", |ui_state| {
        let lifecycle = &mut ui_state["projectLifecycleById"][project_id];
        lifecycle["operations"]["deployments"]
            .as_array_mut()
            .unwrap()
            .insert(
                0,
                json!({
                    "id": "deployment-left-running",
                    "releaseId": "release-1",
                    "environmentId": "staging",
                    "status": "running",
                    "startedAt": 10,
                    "finishedAt": Value::Null,
                    "exitCode": Value::Null,
                    "logs": Value::Null,
                    "operator": { "profileId": "default", "role": "admin" }
                }),
            );
        let environment = &mut lifecycle["operations"]["environments"][0];
        environment["health"] = json!("checking");
        environment["lastHealthCheck"] = json!({
            "id": "health-left-checking",
            "status": "checking",
            "startedAt": 10,
            "finishedAt": Value::Null,
            "exitCode": Value::Null,
            "logs": Value::Null,
            "operator": { "profileId": "default", "role": "admin" }
        });
        Ok(())
    })
    .await
    .unwrap();
    let recovered =
        get_project_lifecycle_payload(&state, "default", json!({ "projectId": project_id }))
            .await
            .unwrap();
    assert_eq!(
        recovered["operations"]["deployments"][0]["status"],
        json!("failed")
    );
    assert_eq!(
        recovered["operations"]["deployments"][0]["evidenceDigest"]
            .as_str()
            .map(str::len),
        Some(64)
    );
    assert_eq!(
        recovered["operations"]["environments"][0]["health"],
        json!("unhealthy")
    );
    assert_eq!(
        recovered["operations"]["environments"][0]["lastHealthCheck"]["status"],
        json!("interrupted")
    );
    append_audit_log(
        &state.config,
        AuditLogEntry {
            id: "legacy-name-collision".to_string(),
            at: now_unix_ms(),
            role: "admin".to_string(),
            method: "legacy/project/update".to_string(),
            target: Some("Execution Project".to_string()),
            ok: true,
            error: None,
        },
    )
    .await
    .unwrap();
    let audit = list_project_audit_payload(
        &state,
        "default",
        json!({ "projectId": project_id, "limit": 20 }),
    )
    .await
    .unwrap();
    assert!(audit["entries"].as_array().is_some_and(|entries| {
        entries.iter().any(|entry| {
            entry.get("method").and_then(Value::as_str)
                == Some("projectLifecycle/operations/recover")
                && entry.get("target").and_then(Value::as_str) == Some(project_id)
                && entry.get("role").and_then(Value::as_str) == Some("system")
                && entry.get("ok").and_then(Value::as_bool) == Some(true)
        })
    }));
    assert!(audit["entries"].as_array().is_some_and(|entries| {
        entries
            .iter()
            .all(|entry| entry.get("id").and_then(Value::as_str) != Some("legacy-name-collision"))
    }));

    fs::remove_dir_all(sandbox).unwrap();
}
