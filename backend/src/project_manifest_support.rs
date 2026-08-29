use super::*;

const PROJECT_MANIFEST_SCHEMA_VERSION: u64 = 2;
const PROJECT_MANIFEST_MAX_BYTES: u64 = 64 * 1024;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProjectManifest {
    pub(crate) schema_version: u64,
    pub(crate) project_id: String,
    pub(crate) name: String,
    pub(crate) root_path: String,
    pub(crate) repository_root: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) enum ProjectManifestRead {
    Missing,
    Legacy,
    Valid(ProjectManifest),
    Corrupt,
}

pub(crate) async fn resolve_or_create_project_directory(
    state: &AppState,
    requested_path: &str,
    project_name: &str,
) -> ApiResult<String> {
    if tokio_fs::metadata(resolve_input_path(
        &state.config.project_root,
        requested_path,
    ))
    .await
    .is_ok()
    {
        return resolve_allowed_directory(state, requested_path).await;
    }

    let candidate = resolve_input_path(&state.config.project_root, requested_path);
    let directory_name = candidate
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| {
            if cfg!(windows) {
                value.eq_ignore_ascii_case(project_name)
            } else {
                *value == project_name
            }
        })
        .ok_or_else(|| {
            api_error(
                StatusCode::BAD_REQUEST,
                "A new project directory must use the project name.",
            )
        })?;
    let parent = candidate.parent().ok_or_else(|| {
        api_error(
            StatusCode::BAD_REQUEST,
            "The project directory has no parent.",
        )
    })?;
    let parent = tokio_fs::canonicalize(parent).await.map_err(|_| {
        api_error(
            StatusCode::BAD_REQUEST,
            "The parent project directory does not exist.",
        )
    })?;
    let allowed_roots = resolved_allowed_roots(&state.config).await;
    if !allowed_roots
        .iter()
        .any(|allowed_root| path_is_within(allowed_root, &parent))
    {
        return Err(api_error(
            StatusCode::FORBIDDEN,
            "The project directory is outside the allowed roots.",
        ));
    }
    let candidate = parent.join(directory_name);
    match tokio_fs::create_dir(&candidate).await {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(_) => {
            return Err(api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Failed to create the project directory.",
            ));
        }
    }
    resolve_allowed_directory(state, &candidate.to_string_lossy()).await
}

fn project_manifest_path(root_path: &Path) -> PathBuf {
    root_path.join(".forgeos").join("project.json")
}

pub(crate) fn is_project_manifest_path(path: &Path) -> bool {
    let matches_component = |value: Option<&str>, expected: &str| {
        value.is_some_and(|value| {
            if cfg!(windows) {
                value.eq_ignore_ascii_case(expected)
            } else {
                value == expected
            }
        })
    };
    matches_component(
        path.file_name().and_then(|value| value.to_str()),
        "project.json",
    ) && matches_component(
        path.parent()
            .and_then(Path::file_name)
            .and_then(|value| value.to_str()),
        ".forgeos",
    )
}

fn valid_project_manifest_name(name: &str) -> bool {
    let name = name.trim();
    !name.is_empty()
        && name.chars().count() <= 120
        && !name.chars().any(|character| {
            character.is_control()
                || matches!(
                    character,
                    '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|'
                )
        })
}

fn parse_project_manifest(raw: &str) -> ProjectManifestRead {
    let Ok(value) = serde_json::from_str::<Value>(raw) else {
        return ProjectManifestRead::Corrupt;
    };
    if value.get("schemaVersion").and_then(Value::as_u64) == Some(1) {
        return ProjectManifestRead::Legacy;
    }
    let Ok(mut manifest) = serde_json::from_value::<ProjectManifest>(value) else {
        return ProjectManifestRead::Corrupt;
    };
    manifest.project_id = manifest.project_id.trim().to_string();
    manifest.name = manifest.name.trim().to_string();
    manifest.root_path = manifest.root_path.trim().to_string();
    manifest.repository_root = manifest.repository_root.map(|root| root.trim().to_string());
    if manifest.schema_version != PROJECT_MANIFEST_SCHEMA_VERSION
        || !manifest.project_id.starts_with("prj_")
        || manifest.project_id.len() <= 4
        || !valid_project_manifest_name(&manifest.name)
        || manifest.root_path.trim().is_empty()
        || manifest
            .repository_root
            .as_deref()
            .is_some_and(|root| root.trim().is_empty())
    {
        return ProjectManifestRead::Corrupt;
    }
    ProjectManifestRead::Valid(manifest)
}

pub(crate) async fn read_project_manifest(
    root_path: &str,
    allowed_roots: &[PathBuf],
) -> ProjectManifestRead {
    let Ok(root_path) = tokio_fs::canonicalize(root_path).await else {
        return ProjectManifestRead::Missing;
    };
    if !allowed_roots
        .iter()
        .any(|allowed_root| path_is_within(allowed_root, &root_path))
    {
        return ProjectManifestRead::Corrupt;
    }
    let manifest_path = project_manifest_path(&root_path);
    let metadata = match tokio_fs::symlink_metadata(&manifest_path).await {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return ProjectManifestRead::Missing;
        }
        Err(_) => return ProjectManifestRead::Corrupt,
    };
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() > PROJECT_MANIFEST_MAX_BYTES
    {
        return ProjectManifestRead::Corrupt;
    }
    match tokio_fs::read_to_string(manifest_path).await {
        Ok(raw) => parse_project_manifest(&raw),
        Err(_) => ProjectManifestRead::Corrupt,
    }
}

pub(crate) fn project_manifest_file_update(
    project: &Value,
    allowed_roots: &[PathBuf],
) -> ApiResult<UiStateTextFileUpdate> {
    let root_path = project
        .get("rootPath")
        .and_then(Value::as_str)
        .filter(|root| !root.trim().is_empty())
        .ok_or_else(|| {
            api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project root is missing while writing its manifest.",
            )
        })?;
    let repository_root = match project.get("repositoryRoot") {
        None | Some(Value::Null) => None,
        Some(Value::String(root)) if !root.trim().is_empty() => Some(root.clone()),
        _ => {
            return Err(api_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Project repository root is invalid while writing its manifest.",
            ));
        }
    };
    let manifest = ProjectManifest {
        schema_version: PROJECT_MANIFEST_SCHEMA_VERSION,
        project_id: project
            .get("projectId")
            .and_then(Value::as_str)
            .filter(|project_id| project_id.starts_with("prj_") && project_id.len() > 4)
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Project identity is missing while writing its manifest.",
                )
            })?
            .to_string(),
        name: project
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| valid_project_manifest_name(name))
            .ok_or_else(|| {
                api_error(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Project name is invalid while writing its manifest.",
                )
            })?
            .to_string(),
        root_path: root_path.to_string(),
        repository_root,
    };
    let mut content = serde_json::to_string_pretty(&manifest).map_err(|error| {
        api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Failed to encode project manifest: {error}"),
        )
    })?;
    content.push('\n');
    Ok(UiStateTextFileUpdate {
        path: project_manifest_path(Path::new(root_path)),
        content,
        allowed_roots: allowed_roots.to_vec(),
    })
}

fn candidate_warning(candidate: &mut Value, warning: &str) {
    let warnings = candidate
        .as_object_mut()
        .expect("project candidates are objects")
        .entry("warnings")
        .or_insert_with(|| json!([]))
        .as_array_mut()
        .expect("project candidate warnings are arrays");
    if !warnings.iter().any(|value| value.as_str() == Some(warning)) {
        warnings.push(Value::String(warning.to_string()));
    }
}

fn candidate_conflict(candidate: &mut Value, kind: &str, message: &str) {
    let object = candidate
        .as_object_mut()
        .expect("project candidates are objects");
    object.insert("status".to_string(), json!("conflict"));
    object
        .entry("conflicts")
        .or_insert_with(|| json!([]))
        .as_array_mut()
        .expect("project candidate conflicts are arrays")
        .push(json!({ "kind": kind, "message": message }));
    candidate_warning(candidate, message);
}

pub(crate) async fn enrich_project_candidates_with_manifests(
    candidates: &mut [Value],
    projects: &[Value],
    allowed_roots: &[PathBuf],
) {
    let mut reads = Vec::with_capacity(candidates.len());
    for candidate in candidates.iter() {
        let read = match candidate.get("rootPath").and_then(Value::as_str) {
            Some(root_path) => read_project_manifest(root_path, allowed_roots).await,
            None => ProjectManifestRead::Missing,
        };
        reads.push(read);
    }

    let mut roots_by_project_id: HashMap<String, HashSet<String>> = HashMap::new();
    for (candidate, read) in candidates.iter().zip(&reads) {
        if let ProjectManifestRead::Valid(manifest) = read
            && let Some(root_path) = candidate.get("rootPath").and_then(Value::as_str)
        {
            roots_by_project_id
                .entry(manifest.project_id.clone())
                .or_default()
                .insert(normalized_path_key(root_path));
        }
    }

    for (candidate, read) in candidates.iter_mut().zip(reads) {
        match read {
            ProjectManifestRead::Missing => {
                candidate["manifestStatus"] = json!("missing");
            }
            ProjectManifestRead::Legacy => {
                candidate["manifestStatus"] = json!("legacy");
                candidate_warning(
                    candidate,
                    "A legacy project manifest will be upgraded during import.",
                );
            }
            ProjectManifestRead::Corrupt => {
                candidate["manifestStatus"] = json!("corrupt");
                candidate_conflict(
                    candidate,
                    "corruptManifest",
                    "The project manifest is damaged or unreadable.",
                );
            }
            ProjectManifestRead::Valid(manifest) => {
                let Some(candidate_root) = candidate
                    .get("rootPath")
                    .and_then(Value::as_str)
                    .map(str::to_string)
                else {
                    continue;
                };
                let candidate_root_key = normalized_path_key(&candidate_root);
                candidate["manifestStatus"] = json!("valid");
                candidate["manifestProjectId"] = json!(manifest.project_id.clone());
                candidate["proposedProjectId"] = json!(manifest.project_id.clone());
                candidate["name"] = json!(manifest.name.clone());
                candidate["repositoryRoot"] = json!(manifest.repository_root.clone());

                if normalized_path_key(&manifest.root_path) != candidate_root_key {
                    candidate_conflict(
                        candidate,
                        "manifestRootMismatch",
                        "The manifest rootPath does not match the directory containing it.",
                    );
                }
                if roots_by_project_id
                    .get(&manifest.project_id)
                    .is_some_and(|roots| roots.len() > 1)
                {
                    candidate_conflict(
                        candidate,
                        "projectIdRootMismatch",
                        "The same projectId was found in more than one directory.",
                    );
                }

                let project_with_id = projects.iter().find(|project| {
                    project.get("projectId").and_then(Value::as_str)
                        == Some(manifest.project_id.as_str())
                });
                let project_at_root = projects.iter().find(|project| {
                    project
                        .get("rootPath")
                        .and_then(Value::as_str)
                        .is_some_and(|root| normalized_path_key(root) == candidate_root_key)
                });
                if let Some(project) = project_with_id {
                    let registered_root_matches = project
                        .get("rootPath")
                        .and_then(Value::as_str)
                        .is_some_and(|root| normalized_path_key(root) == candidate_root_key);
                    if registered_root_matches {
                        candidate["existingProjectId"] = json!(manifest.project_id);
                        if candidate.get("status").and_then(Value::as_str) != Some("conflict") {
                            candidate["status"] = json!("alreadyImported");
                        }
                        if project.get("name").and_then(Value::as_str)
                            != Some(manifest.name.as_str())
                        {
                            candidate_warning(
                                candidate,
                                "The manifest projectId matches a renamed registered project.",
                            );
                        }
                    } else {
                        candidate_conflict(
                            candidate,
                            "projectIdRootMismatch",
                            "This projectId is already registered to another directory.",
                        );
                    }
                }
                if let Some(project) = project_at_root
                    && project.get("projectId").and_then(Value::as_str)
                        != Some(manifest.project_id.as_str())
                {
                    candidate_conflict(
                        candidate,
                        "rootProjectIdMismatch",
                        "This directory is already registered with another projectId.",
                    );
                }
                if project_with_id.is_none()
                    && project_at_root.is_none()
                    && candidate.get("status").and_then(Value::as_str) == Some("alreadyImported")
                {
                    candidate_conflict(
                        candidate,
                        "nameRootMismatch",
                        "A registered project with this name uses another directory.",
                    );
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "project_manifest_support_tests.rs"]
mod tests;
