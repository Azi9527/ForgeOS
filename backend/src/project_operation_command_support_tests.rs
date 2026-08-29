use super::*;

#[test]
fn persisted_operation_logs_redact_credentials_before_evidence_digest() {
    let logs = bounded_logs(
        b"deployment started\nAuthorization: Bearer bearer-secret\nGH_TOKEN=github-secret\napi_key=api-secret\nsk-project-secret",
        b"password: password-secret\nclient_secret=client-secret\ndeployment failed safely",
    );

    for secret in [
        "bearer-secret",
        "github-secret",
        "api-secret",
        "sk-project-secret",
        "password-secret",
        "client-secret",
    ] {
        assert!(!logs.contains(secret), "operation evidence leaked {secret}");
    }
    assert!(logs.contains("deployment started"));
    assert!(logs.contains("deployment failed safely"));
    assert!(logs.contains("[redacted]"));
}

#[test]
fn persisted_operation_logs_remain_bounded_after_redaction() {
    let logs = bounded_logs("safe output ".repeat(2_000).as_bytes(), b"");

    assert!(logs.len() <= MAX_OPERATION_LOG_BYTES + "… earlier output truncated …\n".len());
    assert!(logs.ends_with("safe output"));
}
