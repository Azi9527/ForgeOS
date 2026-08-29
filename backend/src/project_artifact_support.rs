use super::*;
use sha2::Digest as _;

#[cfg(test)]
#[path = "project_artifact_support_tests.rs"]
mod tests;

const ARTIFACT_SIGNATURE_CONTEXT: &str = "forgeos-project-artifact-v2";
const LEGACY_ARTIFACT_SIGNATURE_CONTEXT: &str = "forgeos-project-artifact-v1";
const ARTIFACT_METADATA_MAX_BYTES: u64 = 64 * 1024;
const ARTIFACT_PROJECT_ID_MAX_BYTES: usize = 128;
const ARTIFACT_VERSION_MAX_BYTES: usize = 128;
const ARTIFACT_SOURCE_COMMIT_MAX_BYTES: usize = 256;
const ARTIFACT_ORIGINAL_NAME_MAX_BYTES: usize = 255;

fn bounded_artifact_text(bytes: &[u8], field: &str, max_bytes: usize) -> ApiResult<String> {
    if bytes.len() > max_bytes {
        return Err(api_error(
            StatusCode::BAD_REQUEST,
            format!("Artifact {field} must not exceed {max_bytes} bytes."),
        ));
    }
    std::str::from_utf8(bytes)
        .map(str::trim)
        .map(str::to_string)
        .map_err(|_| {
            api_error(
                StatusCode::BAD_REQUEST,
                format!("Artifact {field} must be valid UTF-8."),
            )
        })
}

fn project_artifact_key(project_id: &str) -> String {
    Sha256::digest(project_id.trim().as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>()
}

fn sanitize_project_artifact_name(name: &str) -> String {
    let sanitized = name
        .trim()
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '.' | '-' | '_') {
                character
            } else {
                '_'
            }
        })
        .take(180)
        .collect::<String>();
    if sanitized.is_empty() {
        "artifact.bin".to_string()
    } else {
        sanitized
    }
}

fn redact_artifact_metadata_for_viewer(metadata: &mut Value) {
    if let Some(created_by) = metadata.get_mut("createdBy").and_then(Value::as_object_mut)
        && created_by.contains_key("profileId")
    {
        created_by.insert("profileId".to_string(), json!("redacted"));
    }
}

fn stored_artifact_path(root: &Path, stored_name: &str) -> ApiResult<PathBuf> {
    if matches!(stored_name, "." | "..")
        || stored_name.is_empty()
        || stored_name.len() > 255
        || !stored_name.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '.' | '-' | '_')
        })
    {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Stored artifact name is invalid.",
        ));
    }
    Ok(root.join(stored_name))
}

pub(crate) fn project_artifact_root(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
) -> PathBuf {
    resolve_runtime_profile(&state.config, profile_id)
        .data_dir
        .join("project-artifacts")
        .join(project_artifact_key(project_id))
}

async fn read_artifact_signing_key(path: &Path) -> ApiResult<Option<Vec<u8>>> {
    let metadata = match tokio_fs::symlink_metadata(path).await {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                error.to_string(),
            ));
        }
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Artifact signing key must be a regular file.",
        ));
    }
    let bytes = tokio_fs::read(path)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    if bytes.len() < 32 {
        return Err(api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Artifact signing key is truncated.",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tokio_fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .await
            .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    }
    Ok(Some(bytes))
}

pub(crate) async fn artifact_signing_key(state: &AppState, profile_id: &str) -> ApiResult<Vec<u8>> {
    let profile = resolve_runtime_profile(&state.config, profile_id);
    let key_path = profile.data_dir.join("artifact-signing.key");
    if let Some(bytes) = read_artifact_signing_key(&key_path).await? {
        return Ok(bytes);
    }
    tokio_fs::create_dir_all(&profile.data_dir)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let seed = format!("{}:{}", Uuid::new_v4(), Uuid::new_v4());
    let key = Sha256::digest(seed.as_bytes()).to_vec();
    let temporary_path = profile
        .data_dir
        .join(format!(".artifact-signing-{}.tmp", Uuid::new_v4()));
    let mut options = tokio_fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut temporary_file = options
        .open(&temporary_path)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let write_result = async {
        temporary_file.write_all(&key).await?;
        temporary_file.sync_all().await
    }
    .await;
    drop(temporary_file);
    if let Err(error) = write_result {
        let _ = tokio_fs::remove_file(&temporary_path).await;
        return Err(api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            error.to_string(),
        ));
    }
    match tokio_fs::hard_link(&temporary_path, &key_path).await {
        Ok(()) => {
            let _ = tokio_fs::remove_file(&temporary_path).await;
            Ok(key)
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let _ = tokio_fs::remove_file(&temporary_path).await;
            read_artifact_signing_key(&key_path).await?.ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Artifact signing key disappeared during initialization.",
                )
            })
        }
        Err(error) => {
            let _ = tokio_fs::remove_file(&temporary_path).await;
            return Err(api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                error.to_string(),
            ));
        }
    }
}

fn artifact_signature_payload(
    artifact_id: &str,
    project_id: &str,
    version: &str,
    sha256: &str,
    size: u64,
) -> String {
    artifact_signature_payload_with_context(
        ARTIFACT_SIGNATURE_CONTEXT,
        artifact_id,
        project_id,
        version,
        sha256,
        size,
    )
}

fn artifact_signature_payload_with_context(
    context: &str,
    artifact_id: &str,
    project_scope: &str,
    version: &str,
    sha256: &str,
    size: u64,
) -> String {
    format!(
        "{context}\n{artifact_id}\n{}\n{}\n{sha256}\n{size}",
        project_scope.trim(),
        version.trim()
    )
}

fn sign_artifact_manifest(key: &[u8], payload: &str) -> ApiResult<String> {
    let mut mac = Hmac::<Sha256>::new_from_slice(key)
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    mac.update(payload.as_bytes());
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

pub(crate) fn artifact_manifest_signature_is_valid(
    key: &[u8],
    project_id: &str,
    artifact: &Value,
) -> bool {
    let Some(artifact_id) = artifact.get("id").and_then(Value::as_str) else {
        return false;
    };
    let Some(version) = artifact.get("version").and_then(Value::as_str) else {
        return false;
    };
    let Some(sha256) = artifact.get("sha256").and_then(Value::as_str) else {
        return false;
    };
    let Some(size) = artifact.get("size").and_then(Value::as_u64) else {
        return false;
    };
    let Some(signature) = artifact.get("signature").and_then(Value::as_str) else {
        return false;
    };
    let payload = artifact_signature_payload(artifact_id, project_id, version, sha256, size);
    sign_artifact_manifest(key, &payload)
        .is_ok_and(|expected| bool::from(expected.as_bytes().ct_eq(signature.as_bytes())))
}

async fn project_is_managed(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
) -> ApiResult<bool> {
    with_ui_state_read(state, profile_id, |ui_state| {
        Ok(project_record(ui_state, project_id).is_some())
    })
    .await
}

async fn write_project_artifact_file(path: &Path, bytes: &[u8]) -> ApiResult<()> {
    let parent = path.parent().ok_or_else(|| {
        api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Project artifact path is invalid.",
        )
    })?;
    tokio_fs::create_dir_all(parent)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    let temporary_path = parent.join(format!(".artifact-{}.tmp", Uuid::new_v4()));
    tokio_fs::write(&temporary_path, bytes)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    replace_file_atomically(&temporary_path, path)
        .await
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?;
    Ok(())
}

async fn read_project_artifact_metadata(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    artifact_id: &str,
) -> ApiResult<Value> {
    if !artifact_id
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || character == '-')
    {
        return Err(api_error(StatusCode::BAD_REQUEST, "Invalid artifact id."));
    }
    let metadata_path =
        project_artifact_root(state, profile_id, project_id).join(format!("{artifact_id}.json"));
    let metadata = tokio_fs::symlink_metadata(&metadata_path)
        .await
        .map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => {
                api_error(StatusCode::NOT_FOUND, "Project artifact was not found.")
            }
            _ => api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()),
        })?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() > ARTIFACT_METADATA_MAX_BYTES
    {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Project artifact metadata must be a bounded regular file.",
        ));
    }
    let bytes = tokio_fs::read(metadata_path)
        .await
        .map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => {
                api_error(StatusCode::NOT_FOUND, "Project artifact was not found.")
            }
            _ => api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()),
        })?;
    serde_json::from_slice(&bytes)
        .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))
}

pub(crate) async fn verify_project_artifact(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    artifact_id: &str,
) -> ApiResult<(Value, PathBuf)> {
    let metadata =
        read_project_artifact_metadata(state, profile_id, project_id, artifact_id).await?;
    let stored_name = metadata
        .get("storedName")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Artifact metadata is invalid.",
            )
        })?;
    let file_path = stored_artifact_path(
        &project_artifact_root(state, profile_id, project_id),
        stored_name,
    )?;
    let bytes = tokio_fs::read(&file_path)
        .await
        .map_err(|error| api_error(StatusCode::NOT_FOUND, error.to_string()))?;
    let actual_digest = Sha256::digest(&bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let expected_digest = metadata
        .get("sha256")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let key = artifact_signing_key(state, profile_id).await?;
    if !bool::from(actual_digest.as_bytes().ct_eq(expected_digest.as_bytes()))
        || !artifact_manifest_signature_is_valid(&key, project_id, &metadata)
    {
        return Err(api_error(
            StatusCode::CONFLICT,
            "Project artifact signature verification failed.",
        ));
    }
    Ok((metadata, file_path))
}

pub(crate) async fn migrate_legacy_project_artifacts(
    state: &AppState,
    profile_id: &str,
    project_id: &str,
    project_name: &str,
    legacy_project_name: &str,
    lifecycle: &mut Value,
) -> ApiResult<()> {
    let artifacts = lifecycle
        .get_mut("release")
        .and_then(|release| release.get_mut("artifacts"))
        .and_then(Value::as_array_mut)
        .ok_or_else(|| api_error(StatusCode::CONFLICT, "Legacy release state is invalid."))?;
    let legacy_root = project_artifact_root(state, profile_id, legacy_project_name);
    let target_root = project_artifact_root(state, profile_id, project_id);
    let key = artifact_signing_key(state, profile_id).await?;

    for artifact in artifacts {
        let Some(artifact_id) = artifact
            .get("id")
            .and_then(Value::as_str)
            .map(str::to_string)
        else {
            continue;
        };
        let metadata_path = legacy_root.join(format!("{artifact_id}.json"));
        let Ok(metadata_bytes) = tokio_fs::read(&metadata_path).await else {
            continue;
        };
        let mut metadata: Value = serde_json::from_slice(&metadata_bytes)
            .map_err(|error| api_error(StatusCode::CONFLICT, error.to_string()))?;
        let stored_name = metadata
            .get("storedName")
            .and_then(Value::as_str)
            .ok_or_else(|| api_error(StatusCode::CONFLICT, "Legacy artifact metadata is invalid."))?
            .to_string();
        let bytes = tokio_fs::read(stored_artifact_path(&legacy_root, &stored_name)?)
            .await
            .map_err(|error| api_error(StatusCode::CONFLICT, error.to_string()))?;
        let actual_digest = Sha256::digest(&bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let expected_digest = metadata
            .get("sha256")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if !bool::from(actual_digest.as_bytes().ct_eq(expected_digest.as_bytes())) {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Legacy artifact digest verification failed.",
            ));
        }
        let version = metadata
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let size = metadata
            .get("size")
            .and_then(Value::as_u64)
            .unwrap_or(bytes.len() as u64);
        let legacy_signature = metadata
            .get("signature")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let legacy_payload = artifact_signature_payload_with_context(
            LEGACY_ARTIFACT_SIGNATURE_CONTEXT,
            &artifact_id,
            legacy_project_name,
            &version,
            &expected_digest,
            size,
        );
        if !sign_artifact_manifest(&key, &legacy_payload).is_ok_and(|expected| {
            bool::from(expected.as_bytes().ct_eq(legacy_signature.as_bytes()))
        }) {
            return Err(api_error(
                StatusCode::CONFLICT,
                "Legacy artifact signature verification failed.",
            ));
        }
        let signature = sign_artifact_manifest(
            &key,
            &artifact_signature_payload(&artifact_id, project_id, &version, &expected_digest, size),
        )?;
        metadata["projectId"] = json!(project_id);
        metadata["projectName"] = json!(project_name);
        metadata["legacyProjectName"] = json!(legacy_project_name);
        metadata["signature"] = json!(signature);
        metadata["signatureAlgorithm"] = json!("hmac-sha256");
        metadata["signatureVerified"] = json!(true);
        write_project_artifact_file(&stored_artifact_path(&target_root, &stored_name)?, &bytes)
            .await?;
        write_project_artifact_file(
            &target_root.join(format!("{artifact_id}.json")),
            &serde_json::to_vec_pretty(&metadata)
                .map_err(|error| api_error(StatusCode::INTERNAL_SERVER_ERROR, error.to_string()))?,
        )
        .await?;
        artifact["signature"] = metadata["signature"].clone();
        artifact["signatureAlgorithm"] = json!("hmac-sha256");
        artifact["signatureVerified"] = json!(true);
    }
    Ok(())
}

pub(crate) async fn handle_project_artifacts_api_http(
    state: AppState,
    request: Request,
    auth: AuthContext,
    route_path: &str,
) -> Response {
    if route_path == "/api/project-artifacts/download"
        && request.method() == Method::GET
        && !role_has_admin_access(auth.role)
    {
        return json_error(StatusCode::FORBIDDEN, "This action requires an admin role.");
    }
    if route_path == "/api/project-artifacts" && request.method() == Method::POST {
        if !role_has_admin_access(auth.role) {
            return json_error(StatusCode::FORBIDDEN, "This action requires an admin role.");
        }
        if request
            .headers()
            .get(header::CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .is_some_and(|length| length > state.config.max_upload_bytes.saturating_add(65_536))
        {
            return json_error(
                StatusCode::PAYLOAD_TOO_LARGE,
                "Project artifact is too large.",
            );
        }
        let mut multipart = match Multipart::from_request(request, &()).await {
            Ok(multipart) => multipart,
            Err(_) => return json_error(StatusCode::BAD_REQUEST, "Invalid artifact upload."),
        };
        let mut project_id = String::new();
        let mut version = String::new();
        let mut source_commit = String::new();
        let mut original_name = String::new();
        let mut file_bytes = Vec::new();
        while let Ok(Some(field)) = multipart.next_field().await {
            let field_name = field.name().unwrap_or_default().to_string();
            if field_name == "file" {
                original_name = field.file_name().unwrap_or("artifact.bin").to_string();
                if original_name.as_bytes().len() > ARTIFACT_ORIGINAL_NAME_MAX_BYTES {
                    return json_error(
                        StatusCode::BAD_REQUEST,
                        "Artifact file name must not exceed 255 bytes.",
                    );
                }
                match field.bytes().await {
                    Ok(bytes) => file_bytes = bytes.to_vec(),
                    Err(_) => {
                        return json_error(StatusCode::BAD_REQUEST, "Invalid artifact upload.");
                    }
                }
            } else if matches!(
                field_name.as_str(),
                "projectId" | "version" | "sourceCommit"
            ) {
                let bytes = match field.bytes().await {
                    Ok(bytes) => bytes,
                    Err(_) => {
                        return json_error(StatusCode::BAD_REQUEST, "Invalid artifact upload.");
                    }
                };
                let result = match field_name.as_str() {
                    "projectId" => {
                        bounded_artifact_text(&bytes, "projectId", ARTIFACT_PROJECT_ID_MAX_BYTES)
                            .map(|value| project_id = value)
                    }
                    "version" => {
                        bounded_artifact_text(&bytes, "version", ARTIFACT_VERSION_MAX_BYTES)
                            .map(|value| version = value)
                    }
                    "sourceCommit" => bounded_artifact_text(
                        &bytes,
                        "sourceCommit",
                        ARTIFACT_SOURCE_COMMIT_MAX_BYTES,
                    )
                    .map(|value| source_commit = value),
                    _ => unreachable!("known artifact metadata field"),
                };
                if let Err(error) = result {
                    return json_error(error.status, &error.message);
                }
            }
        }
        if project_id.is_empty() || version.is_empty() || file_bytes.is_empty() {
            return json_error(
                StatusCode::BAD_REQUEST,
                "projectId, version, and file are required.",
            );
        }
        if file_bytes.len() as u64 > state.config.max_upload_bytes {
            return json_error(
                StatusCode::PAYLOAD_TOO_LARGE,
                "Project artifact is too large.",
            );
        }
        match project_is_managed(&state, &auth.profile_id, &project_id).await {
            Ok(true) => {}
            Ok(false) => return json_error(StatusCode::NOT_FOUND, "Project was not found."),
            Err(error) => return json_error(error.status, &error.message),
        }
        let artifact_id = Uuid::new_v4().to_string();
        let safe_name = sanitize_project_artifact_name(&original_name);
        let stored_name = format!("{artifact_id}-{safe_name}");
        let project_name = match with_ui_state_read(&state, &auth.profile_id, |ui_state| {
            let project = lifecycle_project_record(ui_state, &project_id)?;
            Ok(project
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string())
        })
        .await
        {
            Ok(project_name) => project_name,
            Err(error) => return json_error(error.status, &error.message),
        };
        let root = project_artifact_root(&state, &auth.profile_id, &project_id);
        let file_path = root.join(&stored_name);
        let sha256 = Sha256::digest(&file_bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let key = match artifact_signing_key(&state, &auth.profile_id).await {
            Ok(key) => key,
            Err(error) => return json_error(error.status, &error.message),
        };
        let signature_payload = artifact_signature_payload(
            &artifact_id,
            &project_id,
            &version,
            &sha256,
            file_bytes.len() as u64,
        );
        let signature = match sign_artifact_manifest(&key, &signature_payload) {
            Ok(signature) => signature,
            Err(error) => return json_error(error.status, &error.message),
        };
        let metadata = json!({
            "id": artifact_id,
            "projectId": project_id,
            "projectName": project_name,
            "name": original_name,
            "version": version,
            "sourceCommit": if source_commit.is_empty() { Value::Null } else { json!(source_commit) },
            "sha256": sha256,
            "size": file_bytes.len(),
            "signature": signature,
            "signatureAlgorithm": "hmac-sha256",
            "signatureVerified": true,
            "status": "ready",
            "storedName": stored_name,
            "createdAt": now_unix_ms(),
            "createdBy": {
                "profileId": auth.profile_id,
                "role": user_role_label(auth.role)
            }
        });
        let metadata_bytes = match serde_json::to_vec_pretty(&metadata) {
            Ok(bytes) => bytes,
            Err(error) => return json_error(StatusCode::INTERNAL_SERVER_ERROR, &error.to_string()),
        };
        if metadata_bytes.len() as u64 > ARTIFACT_METADATA_MAX_BYTES {
            return json_error(
                StatusCode::BAD_REQUEST,
                "Project artifact metadata is too large.",
            );
        }
        if let Err(error) = write_project_artifact_file(&file_path, &file_bytes).await {
            return json_error(error.status, &error.message);
        }
        if let Err(error) =
            write_project_artifact_file(&root.join(format!("{artifact_id}.json")), &metadata_bytes)
                .await
        {
            let _ = tokio_fs::remove_file(&file_path).await;
            return json_error(error.status, &error.message);
        }
        let _ = append_audit_log(
            &state.config,
            AuditLogEntry {
                id: Uuid::new_v4().to_string(),
                at: now_unix_ms(),
                role: user_role_label(auth.role).to_string(),
                method: "projectArtifacts/upload".to_string(),
                target: Some(project_id),
                ok: true,
                error: None,
            },
        )
        .await;
        let mut response = Json(json!({ "artifact": metadata })).into_response();
        *response.status_mut() = StatusCode::CREATED;
        return response;
    }

    let project_id = query_param_value(request.uri().query(), "projectId").unwrap_or_default();
    let artifact_id = query_param_value(request.uri().query(), "artifactId").unwrap_or_default();
    if project_id.is_empty() || artifact_id.is_empty() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "projectId and artifactId are required.",
        );
    }
    match (request.method(), route_path) {
        (&Method::GET, "/api/project-artifacts/verify") => {
            match verify_project_artifact(&state, &auth.profile_id, &project_id, &artifact_id).await
            {
                Ok((mut metadata, _)) => {
                    if auth.role == UserRole::Viewer {
                        redact_artifact_metadata_for_viewer(&mut metadata);
                    }
                    Json(json!({
                        "ok": true,
                        "artifact": metadata
                    }))
                    .into_response()
                }
                Err(error) => json_error(error.status, &error.message),
            }
        }
        (&Method::GET, "/api/project-artifacts/download") => {
            match verify_project_artifact(&state, &auth.profile_id, &project_id, &artifact_id).await
            {
                Ok((metadata, file_path)) => match tokio_fs::read(file_path).await {
                    Ok(bytes) => {
                        let mut response = Response::new(Body::from(bytes));
                        response.headers_mut().insert(
                            header::CONTENT_TYPE,
                            HeaderValue::from_static("application/octet-stream"),
                        );
                        if let Some(name) = metadata.get("name").and_then(Value::as_str)
                            && let Ok(value) = HeaderValue::from_str(&format!(
                                "attachment; filename=\"{}\"",
                                sanitize_project_artifact_name(name)
                            ))
                        {
                            response
                                .headers_mut()
                                .insert(header::CONTENT_DISPOSITION, value);
                        }
                        response
                    }
                    Err(error) => json_error(StatusCode::NOT_FOUND, &error.to_string()),
                },
                Err(error) => json_error(error.status, &error.message),
            }
        }
        _ => json_error(StatusCode::METHOD_NOT_ALLOWED, "Method not allowed."),
    }
}
