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
