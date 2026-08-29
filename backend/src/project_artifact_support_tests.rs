use super::*;

#[test]
fn artifact_names_are_confined_to_a_single_file_name() {
    assert_eq!(
        sanitize_project_artifact_name("../ForgeOS gateway 1.0.zip"),
        ".._ForgeOS_gateway_1.0.zip"
    );
    assert_eq!(sanitize_project_artifact_name(""), "artifact.bin");
}

#[test]
fn artifact_text_metadata_is_bounded_before_persistence() {
    assert_eq!(
        bounded_artifact_text(b"  0.3.0-rc.1  ", "version", ARTIFACT_VERSION_MAX_BYTES).unwrap(),
        "0.3.0-rc.1"
    );
    let error = bounded_artifact_text(
        &vec![b'x'; ARTIFACT_SOURCE_COMMIT_MAX_BYTES + 1],
        "sourceCommit",
        ARTIFACT_SOURCE_COMMIT_MAX_BYTES,
    )
    .unwrap_err();
    assert_eq!(error.status, StatusCode::BAD_REQUEST);
    assert!(error.message.contains("sourceCommit"));
}

#[test]
fn artifact_project_keys_are_stable_and_do_not_expose_names() {
    let first = project_artifact_key("ForgeOS");
    assert_eq!(first, project_artifact_key("ForgeOS"));
    assert_eq!(first.len(), 64);
    assert_ne!(first, project_artifact_key("Another Project"));
    assert!(!first.contains("ForgeOS"));
}

#[test]
fn stored_artifact_names_cannot_escape_the_project_artifact_root() {
    let root = Path::new("artifact-root");
    assert_eq!(
        stored_artifact_path(root, "artifact-1-release.zip").unwrap(),
        root.join("artifact-1-release.zip")
    );
    for stored_name in [
        "../secret",
        "subdirectory/file",
        "subdirectory\\file",
        "C:artifact.bin",
        ".",
        "artifact name.zip",
    ] {
        assert!(
            stored_artifact_path(root, stored_name).is_err(),
            "{stored_name} must be rejected"
        );
    }
}

#[test]
fn signatures_are_bound_to_artifact_manifest_fields() {
    let key = [7_u8; 32];
    let payload = artifact_signature_payload("artifact-1", "prj_forgeos", "1.2.0", "abc", 42);
    let signature = sign_artifact_manifest(&key, &payload).unwrap();
    assert_eq!(signature, sign_artifact_manifest(&key, &payload).unwrap());
    assert_ne!(
        signature,
        sign_artifact_manifest(
            &key,
            &artifact_signature_payload("artifact-1", "prj_forgeos", "1.2.1", "abc", 42)
        )
        .unwrap()
    );
}

#[tokio::test]
async fn signing_key_reader_rejects_truncated_and_non_regular_keys() {
    let root = std::env::temp_dir().join(format!("forgeos-artifact-key-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create signing key test root");
    let key_path = root.join("artifact-signing.key");
    std::fs::write(&key_path, [7_u8; 12]).expect("write truncated key");
    assert!(read_artifact_signing_key(&key_path).await.is_err());

    std::fs::remove_file(&key_path).expect("remove truncated key");
    std::fs::create_dir(&key_path).expect("create invalid key directory");
    assert!(read_artifact_signing_key(&key_path).await.is_err());
    std::fs::remove_dir_all(root).expect("remove signing key test root");
}

#[cfg(unix)]
#[tokio::test]
async fn signing_key_reader_hardens_unix_permissions() {
    use std::os::unix::fs::PermissionsExt;

    let root = std::env::temp_dir().join(format!("forgeos-artifact-mode-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create signing key test root");
    let key_path = root.join("artifact-signing.key");
    std::fs::write(&key_path, [9_u8; 32]).expect("write signing key");
    std::fs::set_permissions(&key_path, std::fs::Permissions::from_mode(0o644))
        .expect("make signing key permissive");

    assert_eq!(
        read_artifact_signing_key(&key_path)
            .await
            .expect("read signing key"),
        Some(vec![9_u8; 32])
    );
    assert_eq!(
        std::fs::metadata(&key_path)
            .expect("read hardened key metadata")
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    std::fs::remove_dir_all(root).expect("remove signing key test root");
}

fn artifact_multipart_body(
    boundary: &str,
    project_id: &str,
    version: &str,
    source_commit: &str,
) -> String {
    format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"projectId\"\r\n\r\n{project_id}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"version\"\r\n\r\n{version}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"sourceCommit\"\r\n\r\n{source_commit}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"forgeos.zip\"\r\nContent-Type: application/zip\r\n\r\nrelease-bytes\r\n\
         --{boundary}--\r\n"
    )
}

fn legacy_artifact_multipart_body(boundary: &str, project_name: &str) -> String {
    format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"projectName\"\r\n\r\n{project_name}\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"version\"\r\n\r\n0.3.0-rc.1\r\n\
         --{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"forgeos.zip\"\r\nContent-Type: application/zip\r\n\r\nrelease-bytes\r\n\
         --{boundary}--\r\n"
    )
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn artifact_http_upload_verifies_and_rejects_oversized_metadata() {
    let root = std::env::temp_dir().join(format!("forgeos-artifact-http-{}", Uuid::new_v4()));
    tokio_fs::create_dir_all(&root).await.unwrap();
    let state =
        crate::main_tests::test_state(root.clone(), vec![root.clone()], root.join("codex-home"));
    let project_id = "prj_artifact_http";
    let project_root = root.display().to_string();
    with_ui_state_write(&state, "default", |ui_state| {
        ui_state["projectRegistry"]["projectsById"][project_id] = json!({
            "schemaVersion": 2,
            "projectId": project_id,
            "name": "Artifact HTTP Test",
            "rootPath": project_root,
            "status": "active",
            "revision": 1
        });
        Ok(())
    })
    .await
    .unwrap();
    let auth = AuthContext {
        role: UserRole::Admin,
        profile_id: "default".to_string(),
    };
    let boundary = "forgeos-artifact-boundary";
    let body = artifact_multipart_body(boundary, project_id, "0.3.0-rc.1", "deadbeef");
    let request = Request::builder()
        .method(Method::POST)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(body))
        .unwrap();
    let response = handle_project_artifacts_api_http(
        state.clone(),
        request,
        auth.clone(),
        "/api/project-artifacts",
    )
    .await;
    assert_eq!(response.status(), StatusCode::CREATED);
    let response_body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let payload: Value = serde_json::from_slice(&response_body).unwrap();
    let artifact_id = payload["artifact"]["id"].as_str().unwrap();

    let verify_request = Request::builder()
        .method(Method::GET)
        .uri(format!(
            "/api/project-artifacts/verify?projectId={project_id}&artifactId={artifact_id}"
        ))
        .body(Body::empty())
        .unwrap();
    let verify_response = handle_project_artifacts_api_http(
        state.clone(),
        verify_request,
        AuthContext {
            role: UserRole::Viewer,
            profile_id: "default".to_string(),
        },
        "/api/project-artifacts/verify",
    )
    .await;
    assert_eq!(verify_response.status(), StatusCode::OK);
    let verify_body = to_bytes(verify_response.into_body(), usize::MAX)
        .await
        .unwrap();
    let verified: Value = serde_json::from_slice(&verify_body).unwrap();
    assert_eq!(verified["ok"], json!(true));
    assert_eq!(verified["artifact"]["signatureVerified"], json!(true));
    assert_eq!(
        verified["artifact"]["createdBy"]["profileId"],
        json!("redacted")
    );

    let oversized_version = "x".repeat(ARTIFACT_VERSION_MAX_BYTES + 1);
    let oversized_body =
        artifact_multipart_body(boundary, project_id, &oversized_version, "deadbeef");
    let oversized_request = Request::builder()
        .method(Method::POST)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(oversized_body))
        .unwrap();
    let oversized_response = handle_project_artifacts_api_http(
        state.clone(),
        oversized_request,
        auth,
        "/api/project-artifacts",
    )
    .await;
    assert_eq!(oversized_response.status(), StatusCode::BAD_REQUEST);

    let legacy_request = Request::builder()
        .method(Method::POST)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(legacy_artifact_multipart_body(
            boundary,
            "Artifact HTTP Test",
        )))
        .unwrap();
    let legacy_response = handle_project_artifacts_api_http(
        state.clone(),
        legacy_request,
        AuthContext {
            role: UserRole::Admin,
            profile_id: "default".to_string(),
        },
        "/api/project-artifacts",
    )
    .await;
    assert_eq!(legacy_response.status(), StatusCode::CONFLICT);

    let legacy_verify_request = Request::builder()
        .method(Method::GET)
        .uri("/api/project-artifacts/verify?projectName=Artifact%20HTTP%20Test&artifactId=legacy")
        .body(Body::empty())
        .unwrap();
    let legacy_verify_response = handle_project_artifacts_api_http(
        state.clone(),
        legacy_verify_request,
        AuthContext {
            role: UserRole::Viewer,
            profile_id: "default".to_string(),
        },
        "/api/project-artifacts/verify",
    )
    .await;
    assert_eq!(legacy_verify_response.status(), StatusCode::CONFLICT);

    let metadata_files = std::fs::read_dir(project_artifact_root(&state, "default", project_id))
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().and_then(|value| value.to_str()) == Some("json"))
        .count();
    assert_eq!(metadata_files, 1);
    tokio_fs::remove_dir_all(root).await.unwrap();
}
