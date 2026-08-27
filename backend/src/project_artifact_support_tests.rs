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
fn signatures_are_bound_to_artifact_manifest_fields() {
    let key = [7_u8; 32];
    let payload = artifact_signature_payload("artifact-1", "ForgeOS", "1.2.0", "abc", 42);
    let signature = sign_artifact_manifest(&key, &payload).unwrap();
    assert_eq!(signature, sign_artifact_manifest(&key, &payload).unwrap());
    assert_ne!(
        signature,
        sign_artifact_manifest(
            &key,
            &artifact_signature_payload("artifact-1", "ForgeOS", "1.2.1", "abc", 42)
        )
        .unwrap()
    );
}
