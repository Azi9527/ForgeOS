use super::*;

fn owner_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Owner,
        profile_id: "operator-a".to_string(),
    }
}

#[test]
fn lifecycle_default_has_bounded_empty_sections() {
    assert_eq!(
        lifecycle_default("prj_forgeos", "ForgeOS"),
        json!({
            "projectId": "prj_forgeos",
            "projectName": "ForgeOS",
            "revision": 0,
            "updatedAt": Value::Null,
            "validation": { "checks": [], "runs": [] },
            "release": { "artifacts": [], "releases": [] },
            "operations": { "environments": [], "deployments": [] },
            "governance": default_project_governance()
        })
    );
}

#[test]
fn governance_is_bounded_and_keeps_secure_production_minimums() {
    let governance = normalized_project_governance(Some(&json!({
        "approvalPolicy": { "standardApprovals": 0, "productionApprovals": 1 },
        "artifactRetention": { "maxArtifacts": 500, "maxAgeDays": 0 },
        "notificationRoutes": { "approvalRequested": false }
    })));
    assert_eq!(
        governance,
        json!({
            "approvalPolicy": { "standardApprovals": 1, "productionApprovals": 2 },
            "artifactRetention": { "maxArtifacts": 50, "maxAgeDays": 1 },
            "notificationRoutes": {
                "approvalRequested": false,
                "releaseCompleted": true,
                "rollbackCompleted": true,
                "deploymentFailed": true
            }
        })
    );
}

#[test]
fn retention_marks_only_unprotected_expired_artifacts_for_archive() {
    let now = now_unix_ms();
    let lifecycle = json!({
        "governance": {
            "artifactRetention": { "maxArtifacts": 1, "maxAgeDays": 1 }
        },
        "release": {
            "artifacts": [
                { "id": "released", "createdAt": 1 },
                { "id": "fresh", "createdAt": now },
                { "id": "old", "createdAt": 1 }
            ],
            "releases": [{
                "status": "released",
                "artifactIds": ["released"]
            }]
        }
    });
    assert_eq!(
        artifact_retention_status(&lifecycle),
        json!({
            "eligibleForArchive": ["old"],
            "protectedCount": 1,
            "automaticDeletion": false
        })
    );
}

#[test]
fn validation_run_is_bound_to_server_operator_and_digest() {
    let run = normalized_validation_run(
        &json!({
            "id": "run-1",
            "startedAt": 10,
            "finishedAt": 20,
            "status": "passed",
            "rootPath": "D:/code/ForgeOS",
            "branch": "main",
            "commit": "abc123",
            "operator": { "profileId": "untrusted", "role": "owner" },
            "checks": [{
                "id": "test",
                "label": "自动测试",
                "command": "npm test",
                "required": true,
                "status": "passed",
                "exitCode": 0,
                "durationMs": 50,
                "output": "ok"
            }]
        }),
        &owner_auth(),
    )
    .unwrap();

    assert_eq!(
        run.get("operator"),
        Some(&json!({ "profileId": "operator-a", "role": "owner" }))
    );
    assert_eq!(
        run.get("evidenceDigest")
            .and_then(Value::as_str)
            .map(str::len),
        Some(64)
    );
}

#[test]
fn validation_checks_and_output_are_capped() {
    let checks = (0..20)
        .map(|index| {
            json!({
                "id": format!("check-{index}"),
                "label": format!("Check {index}"),
                "command": "run",
                "required": true
            })
        })
        .collect::<Vec<_>>();
    assert_eq!(normalized_validation_checks(Some(&json!(checks))).len(), 12);

    let evidence = normalized_validation_evidence(&json!({
        "id": "test",
        "label": "test",
        "command": "run",
        "required": true,
        "status": "passed",
        "output": "x".repeat(MAX_EVIDENCE_OUTPUT_BYTES + 100)
    }))
    .unwrap();
    assert_eq!(
        evidence.get("output").and_then(Value::as_str).map(str::len),
        Some(MAX_EVIDENCE_OUTPUT_BYTES)
    );
}

#[test]
fn release_requires_approval_before_publish() {
    let awaiting = json!({
        "id": "release-1",
        "status": "awaitingApproval",
        "approvals": []
    });
    let invalid_release = json!({
        "id": "release-1",
        "status": "released",
        "approvals": []
    });
    assert!(validate_release_transition(&invalid_release, Some(&awaiting)).is_err());

    let approved = json!({
        "id": "release-1",
        "status": "approved",
        "approvals": [{ "profileId": "operator-a" }]
    });
    let released = json!({
        "id": "release-1",
        "status": "released",
        "approvals": [{ "profileId": "operator-a" }]
    });
    assert!(validate_release_transition(&released, Some(&approved)).is_ok());
}

#[test]
fn production_release_requires_two_distinct_approvers_including_owner() {
    let lifecycle = json!({
        "operations": {
            "environments": [{ "id": "production", "kind": "production" }]
        },
        "release": {
            "artifacts": [{ "id": "artifact-1", "signatureVerified": true }]
        }
    });
    let one_approval = json!({
        "status": "released",
        "targetEnvironmentId": "production",
        "artifactIds": ["artifact-1"],
        "approvals": [{ "profileId": "operator-a", "role": "owner" }]
    });
    assert!(validate_release_policy(&lifecycle, &one_approval).is_err());

    let two_approvals = json!({
        "status": "released",
        "targetEnvironmentId": "production",
        "artifactIds": ["artifact-1"],
        "approvals": [
            { "profileId": "operator-a", "role": "owner" },
            { "profileId": "operator-b", "role": "admin" }
        ]
    });
    assert!(validate_release_policy(&lifecycle, &two_approvals).is_ok());
}

#[test]
fn configured_production_approval_count_is_enforced() {
    let lifecycle = json!({
        "governance": { "approvalPolicy": { "productionApprovals": 3 } },
        "operations": {
            "environments": [{ "id": "production", "kind": "production" }]
        },
        "release": {
            "artifacts": [{ "id": "artifact-1", "signatureVerified": true }]
        }
    });
    let release = json!({
        "status": "released",
        "targetEnvironmentId": "production",
        "artifactIds": ["artifact-1"],
        "approvals": [
            { "profileId": "operator-a", "role": "owner" },
            { "profileId": "operator-b", "role": "admin" }
        ]
    });
    assert!(validate_release_policy(&lifecycle, &release).is_err());
}

#[test]
fn production_release_rejects_unsigned_artifacts() {
    let lifecycle = json!({
        "operations": {
            "environments": [{ "id": "production", "kind": "production" }]
        },
        "release": {
            "artifacts": [{ "id": "artifact-1", "signatureVerified": false }]
        }
    });
    let release = json!({
        "status": "released",
        "targetEnvironmentId": "production",
        "artifactIds": ["artifact-1"],
        "approvals": [
            { "profileId": "operator-a", "role": "owner" },
            { "profileId": "operator-b", "role": "admin" }
        ]
    });
    assert!(validate_release_policy(&lifecycle, &release).is_err());
}
