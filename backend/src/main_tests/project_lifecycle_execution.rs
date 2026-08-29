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

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn artifact_release_deployment_chain_enforces_project_and_environment_authority() {
    let sandbox = std::env::temp_dir().join(format!("fac-{}", Uuid::new_v4().simple()));
    let project_root = sandbox.join("a");
    let other_project_root = sandbox.join("b");
    let codex_home = sandbox.join("c");
    fs::create_dir_all(&project_root).unwrap();
    fs::create_dir_all(&other_project_root).unwrap();
    fs::create_dir_all(&codex_home).unwrap();
    let state = test_state(sandbox.clone(), vec![sandbox.clone()], codex_home);
    let profile_data_dir = resolve_runtime_profile(&state.config, "default").data_dir;
    fs::create_dir_all(&profile_data_dir).unwrap();
    fs::write(profile_data_dir.join("artifact-signing.key"), [7_u8; 32]).unwrap();
    let project_id = "prj_artifact_chain";
    let other_project_id = "prj_artifact_chain_other";
    with_ui_state_write(&state, "default", |ui_state| {
        ui_state["projectRegistry"]["projectsById"][project_id] = json!({
            "projectId": project_id,
            "name": "Artifact Chain",
            "rootPath": project_root.display().to_string(),
            "status": "active"
        });
        ui_state["projectRegistry"]["projectsById"][other_project_id] = json!({
            "projectId": other_project_id,
            "name": "Other Artifact Chain",
            "rootPath": other_project_root.display().to_string(),
            "status": "active"
        });
        Ok(())
    })
    .await
    .unwrap();

    let auth = AuthContext {
        role: UserRole::Admin,
        profile_id: "default".to_string(),
    };
    let configured = save_project_operations_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "environments": [{
                "id": "staging",
                "name": "Staging",
                "kind": "staging",
                "adapter": "localCommand",
                "deployCommand": local_script("artifact-chain-deployed")
            }]
        }),
    )
    .await
    .unwrap();

    let boundary = "forgeos-artifact-chain-boundary";
    let upload_body = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"projectId\"\r\n\r\n{project_id}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"version\"\r\n\r\n1.0.0\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"sourceCommit\"\r\n\r\ndeadbeef\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"forgeos.zip\"\r\nContent-Type: application/zip\r\n\r\nrelease-bytes\r\n\
         --{boundary}--\r\n"
    );
    let upload_request = Request::builder()
        .method(Method::POST)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(upload_body))
        .unwrap();
    let upload_response = handle_project_artifacts_api_http(
        state.clone(),
        upload_request,
        auth.clone(),
        "/api/project-artifacts",
    )
    .await;
    let upload_status = upload_response.status();
    let upload_body = to_bytes(upload_response.into_body(), usize::MAX)
        .await
        .unwrap();
    assert_eq!(
        upload_status,
        StatusCode::CREATED,
        "artifact upload failed: {}",
        String::from_utf8_lossy(&upload_body)
    );
    let upload: Value = serde_json::from_slice(&upload_body).unwrap();
    let artifact = upload["artifact"].clone();
    let artifact_id = artifact["id"].as_str().unwrap();

    let wrong_project_verify_request = Request::builder()
        .method(Method::GET)
        .uri(format!(
            "/api/project-artifacts/verify?projectId={other_project_id}&artifactId={artifact_id}"
        ))
        .body(Body::empty())
        .unwrap();
    let wrong_project_verify = handle_project_artifacts_api_http(
        state.clone(),
        wrong_project_verify_request,
        auth.clone(),
        "/api/project-artifacts/verify",
    )
    .await;
    assert_eq!(wrong_project_verify.status(), StatusCode::NOT_FOUND);

    let cross_project_release = save_project_release_payload(
        &state,
        &auth,
        json!({
            "projectId": other_project_id,
            "artifacts": [artifact.clone()],
            "releases": [{
                "id": "release-cross-project",
                "version": "1.0.0",
                "artifactIds": [artifact_id],
                "status": "released",
                "targetEnvironmentId": "staging",
                "approvals": [{}]
            }]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(cross_project_release.status, StatusCode::NOT_FOUND);

    let draft_release = json!({
        "id": "release-1",
        "version": "1.0.0",
        "artifactIds": [artifact_id],
        "status": "draft",
        "targetEnvironmentId": "staging",
        "approvals": []
    });
    let draft = save_project_release_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": configured["revision"],
            "artifacts": [artifact.clone()],
            "releases": [draft_release]
        }),
    )
    .await
    .unwrap();
    let mut awaiting_release = draft["release"]["releases"][0].clone();
    awaiting_release["status"] = json!("awaitingApproval");
    let awaiting = save_project_release_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": draft["revision"],
            "artifacts": draft["release"]["artifacts"].clone(),
            "releases": [awaiting_release]
        }),
    )
    .await
    .unwrap();
    let mut approved_release = awaiting["release"]["releases"][0].clone();
    approved_release["status"] = json!("approved");
    approved_release["approvals"] = json!([{}]);
    let approved = save_project_release_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": awaiting["revision"],
            "artifacts": awaiting["release"]["artifacts"].clone(),
            "releases": [approved_release]
        }),
    )
    .await
    .unwrap();
    let mut released_release = approved["release"]["releases"][0].clone();
    released_release["status"] = json!("released");
    released_release["releasedAt"] = json!(now_unix_ms());
    let released = save_project_release_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "revision": approved["revision"],
            "artifacts": approved["release"]["artifacts"].clone(),
            "releases": [released_release]
        }),
    )
    .await
    .unwrap();
    assert_eq!(
        released["release"]["releases"][0]["status"],
        json!("released")
    );
    assert_eq!(
        released["release"]["artifacts"][0]["signatureVerified"],
        json!(true)
    );

    let wrong_environment = run_project_deployment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "releaseId": "release-1",
            "environmentId": "production",
            "expectedRevision": released["revision"]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(wrong_environment.status, StatusCode::CONFLICT);

    let other_lifecycle =
        get_project_lifecycle_payload(&state, "default", json!({ "projectId": other_project_id }))
            .await
            .unwrap();
    let cross_project_deployment = run_project_deployment_payload(
        &state,
        &auth,
        json!({
            "projectId": other_project_id,
            "releaseId": "release-1",
            "environmentId": "staging",
            "expectedRevision": other_lifecycle["revision"]
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(cross_project_deployment.status, StatusCode::NOT_FOUND);

    let deployed = run_project_deployment_payload(
        &state,
        &auth,
        json!({
            "projectId": project_id,
            "releaseId": "release-1",
            "environmentId": "staging",
            "expectedRevision": released["revision"]
        }),
    )
    .await
    .unwrap();
    let deployment = &deployed["operations"]["deployments"][0];
    assert_eq!(deployment["releaseId"], json!("release-1"));
    assert_eq!(deployment["environmentId"], json!("staging"));
    assert_eq!(deployment["status"], json!("succeeded"));
    assert_eq!(deployment["logs"], json!("artifact-chain-deployed"));

    let stored_name = artifact["storedName"].as_str().unwrap();
    tokio_fs::write(
        project_artifact_root(&state, "default", project_id).join(stored_name),
        b"tampered-release-bytes",
    )
    .await
    .unwrap();
    let tampered_verify_request = Request::builder()
        .method(Method::GET)
        .uri(format!(
            "/api/project-artifacts/verify?projectId={project_id}&artifactId={artifact_id}"
        ))
        .body(Body::empty())
        .unwrap();
    let tampered_verify = handle_project_artifacts_api_http(
        state,
        tampered_verify_request,
        auth,
        "/api/project-artifacts/verify",
    )
    .await;
    assert_eq!(tampered_verify.status(), StatusCode::CONFLICT);

    fs::remove_dir_all(sandbox).unwrap();
}
