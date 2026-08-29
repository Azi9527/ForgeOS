use super::*;

fn owner_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Owner,
        profile_id: "operator-a".to_string(),
    }
}

fn admin_auth() -> AuthContext {
    AuthContext {
        role: UserRole::Admin,
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
fn viewer_lifecycle_redaction_preserves_evidence_without_sensitive_details() {
    let mut lifecycle = json!({
        "validation": {
            "checks": [{ "id": "build", "command": "secret-build" }],
            "runs": [{
                "operator": { "profileId": "owner-a", "role": "owner" },
                "checks": [{ "command": "secret-build", "output": "secret-output" }]
            }]
        },
        "release": {
            "artifacts": [{ "createdBy": { "profileId": "owner-a", "role": "owner" } }],
            "releases": [{
                "approvals": [{ "profileId": "approver-a", "role": "admin", "approvedAt": 1 }]
            }]
        },
        "operations": {
            "environments": [{
                "deployCommand": "secret-deploy",
                "healthCommand": "secret-health",
                "lastHealthOutput": "secret-health-output",
                "lastHealthCheck": {
                    "logs": "secret-health-log",
                    "operator": { "profileId": "owner-a", "role": "owner" }
                }
            }],
            "deployments": [{
                "logs": "secret-deployment-log",
                "operator": { "profileId": "owner-a", "role": "owner" }
            }]
        }
    });

    redact_project_lifecycle_for_viewer(&mut lifecycle);

    assert_eq!(
        lifecycle,
        json!({
            "validation": {
                "checks": [{ "id": "build", "command": "" }],
                "runs": [{
                    "operator": { "profileId": "redacted", "role": "owner" },
                    "checks": [{ "command": "", "output": "" }]
                }]
            },
            "release": {
                "artifacts": [{ "createdBy": { "profileId": "redacted", "role": "owner" } }],
                "releases": [{
                    "approvals": [{ "profileId": "redacted", "role": "admin", "approvedAt": 1 }]
                }]
            },
            "operations": {
                "environments": [{
                    "deployCommand": Value::Null,
                    "healthCommand": Value::Null,
                    "lastHealthOutput": Value::Null,
                    "lastHealthCheck": {
                        "logs": Value::Null,
                        "operator": { "profileId": "redacted", "role": "owner" }
                    }
                }],
                "deployments": [{
                    "logs": Value::Null,
                    "operator": { "profileId": "redacted", "role": "owner" }
                }]
            }
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
fn validation_checks_are_capped() {
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
fn approvals_are_distinct_by_profile_and_role() {
    let owner_release = normalized_release(
        &json!({
            "id": "release-1",
            "version": "1.0.0",
            "status": "awaitingApproval",
            "approvals": [{ "approvedAt": 10 }]
        }),
        &owner_auth(),
        None,
    )
    .unwrap();
    let admin_release = normalized_release(
        &json!({
            "id": "release-1",
            "version": "1.0.0",
            "status": "awaitingApproval",
            "approvals": [{ "approvedAt": 10 }, { "approvedAt": 20 }]
        }),
        &admin_auth(),
        Some(&owner_release),
    )
    .unwrap();

    assert_eq!(
        admin_release.get("approvals"),
        Some(&json!([
            { "profileId": "operator-a", "role": "owner", "approvedAt": 10 },
            { "profileId": "operator-a", "role": "admin", "approvedAt": 20 }
        ]))
    );
}

#[test]
fn repeated_approval_from_the_same_profile_and_role_is_deduplicated() {
    let first = normalized_release(
        &json!({
            "id": "release-1",
            "version": "1.0.0",
            "status": "awaitingApproval",
            "approvals": [{ "approvedAt": 10 }]
        }),
        &admin_auth(),
        None,
    )
    .unwrap();
    let replayed = normalized_release(
        &json!({
            "id": "release-1",
            "version": "1.0.0",
            "status": "awaitingApproval",
            "approvals": [{ "approvedAt": 10 }, { "approvedAt": 20 }]
        }),
        &admin_auth(),
        Some(&first),
    )
    .unwrap();

    assert_eq!(replayed.get("approvals"), first.get("approvals"));
}

#[test]
fn environment_schema_does_not_persist_external_credentials() {
    let environment = normalized_environment(
        &json!({
            "id": "production",
            "name": "Production",
            "kind": "production",
            "adapter": "githubActions",
            "githubRepository": "example/forgeos",
            "githubWorkflow": "deploy.yml",
            "githubRef": "main",
            "healthCommand": "curl --fail https://example.com/health",
            "credential": "credential-secret",
            "credentialId": "credential-reference",
            "githubToken": "github-secret",
            "password": "password-secret",
            "headers": { "Authorization": "Bearer bearer-secret" }
        }),
        None,
    )
    .unwrap();

    for field in [
        "credential",
        "credentialId",
        "githubToken",
        "password",
        "headers",
    ] {
        assert!(
            environment.get(field).is_none(),
            "environment persisted forbidden credential field {field}"
        );
    }
    for secret in [
        "credential-secret",
        "credential-reference",
        "github-secret",
        "password-secret",
        "bearer-secret",
    ] {
        assert!(!environment.to_string().contains(secret));
    }
}

#[test]
fn release_approval_states_require_an_existing_target_environment() {
    let lifecycle = json!({
        "operations": {
            "environments": [{ "id": "production", "kind": "production" }]
        }
    });
    for status in ["awaitingApproval", "approved", "released"] {
        assert!(
            validate_release_environment_binding(
                &lifecycle,
                &json!({ "status": status, "targetEnvironmentId": "production" })
            )
            .is_ok(),
            "{status} should accept an existing target"
        );
        assert!(
            validate_release_environment_binding(&lifecycle, &json!({ "status": status })).is_err(),
            "{status} should require a target"
        );
        assert!(
            validate_release_environment_binding(
                &lifecycle,
                &json!({ "status": status, "targetEnvironmentId": "missing" })
            )
            .is_err(),
            "{status} should reject an unknown target"
        );
    }
    assert!(
        validate_release_environment_binding(&lifecycle, &json!({ "status": "draft" })).is_ok()
    );
}

#[test]
fn unchanged_legacy_targetless_releases_survive_upgrade_without_allowing_mutation() {
    let legacy = json!({
        "id": "legacy-release",
        "version": "0.1.0",
        "artifactIds": [],
        "status": "released",
        "targetEnvironmentId": Value::Null,
        "approvals": [],
        "createdAt": 10,
        "releasedAt": 20,
        "rollbackOf": Value::Null
    });
    let current = json!({
        "release": { "artifacts": [], "releases": [legacy.clone()] },
        "operations": { "environments": [] }
    });
    let proposed = current.clone();
    assert!(
        validate_release_environment_upgrade(&current, &proposed, &legacy).is_ok(),
        "an unchanged pre-upgrade record must not block unrelated lifecycle saves"
    );

    let mut changed = legacy.clone();
    changed["version"] = json!("0.1.1");
    assert!(validate_release_environment_upgrade(&current, &proposed, &changed).is_err());
    let new_targetless = json!({
        "id": "new-release",
        "status": "awaitingApproval",
        "targetEnvironmentId": Value::Null
    });
    assert!(validate_release_environment_upgrade(&current, &proposed, &new_targetless).is_err());
}

#[test]
fn production_release_requires_two_distinct_credentials_including_owner() {
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
    assert!(
        validate_release_policy(
            &lifecycle,
            &one_approval,
            OwnerApprovalPolicy::DedicatedOwner
        )
        .is_err()
    );

    let two_approvals = json!({
        "status": "released",
        "targetEnvironmentId": "production",
        "artifactIds": ["artifact-1"],
        "approvals": [
            { "profileId": "operator-a", "role": "owner" },
            { "profileId": "operator-a", "role": "admin" }
        ]
    });
    assert!(
        validate_release_policy(
            &lifecycle,
            &two_approvals,
            OwnerApprovalPolicy::DedicatedOwner
        )
        .is_ok()
    );
}

#[test]
fn admin_approval_is_owner_equivalent_only_without_a_dedicated_owner() {
    let lifecycle = json!({
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
            { "profileId": "operator-a", "role": "admin" },
            { "profileId": "operator-b", "role": "admin" }
        ]
    });

    assert!(
        validate_release_policy(&lifecycle, &release, OwnerApprovalPolicy::AdminEquivalent).is_ok()
    );
    assert!(
        validate_release_policy(&lifecycle, &release, OwnerApprovalPolicy::DedicatedOwner).is_err()
    );
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
    assert!(
        validate_release_policy(&lifecycle, &release, OwnerApprovalPolicy::DedicatedOwner).is_err()
    );
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
    assert!(
        validate_release_policy(&lifecycle, &release, OwnerApprovalPolicy::DedicatedOwner).is_err()
    );
}

#[test]
fn deployment_requires_a_released_release_for_the_same_environment() {
    let lifecycle = json!({
        "operations": {
            "environments": [
                { "id": "staging", "kind": "staging" },
                { "id": "production", "kind": "production" }
            ]
        },
        "release": {
            "releases": [
                {
                    "id": "release-staging",
                    "status": "released",
                    "targetEnvironmentId": "staging"
                },
                {
                    "id": "release-targetless",
                    "status": "released",
                    "targetEnvironmentId": null
                },
                {
                    "id": "release-approved",
                    "status": "approved",
                    "targetEnvironmentId": "production"
                }
            ]
        }
    });
    let valid = json!({
        "id": "deployment-1",
        "releaseId": "release-staging",
        "environmentId": "staging",
        "status": "running"
    });
    assert!(validate_deployment_release_binding(&lifecycle, &valid, None).is_ok());

    let wrong_environment = json!({
        "id": "deployment-2",
        "releaseId": "release-staging",
        "environmentId": "production",
        "status": "running"
    });
    assert!(validate_deployment_release_binding(&lifecycle, &wrong_environment, None).is_err());

    let targetless_production = json!({
        "id": "deployment-3",
        "releaseId": "release-targetless",
        "environmentId": "production",
        "status": "running"
    });
    assert!(validate_deployment_release_binding(&lifecycle, &targetless_production, None).is_err());

    let not_released = json!({
        "id": "deployment-4",
        "releaseId": "release-approved",
        "environmentId": "production",
        "status": "running"
    });
    assert!(validate_deployment_release_binding(&lifecycle, &not_released, None).is_err());
}

#[test]
fn deployment_binding_is_immutable_after_creation() {
    let lifecycle = json!({
        "operations": {
            "environments": [
                { "id": "staging", "kind": "staging" },
                { "id": "production", "kind": "production" }
            ]
        },
        "release": {
            "releases": [{
                "id": "release-staging",
                "status": "released",
                "targetEnvironmentId": "staging"
            }]
        }
    });
    let existing = json!({
        "id": "deployment-1",
        "releaseId": "release-staging",
        "environmentId": "staging",
        "status": "running"
    });
    let rebound = json!({
        "id": "deployment-1",
        "releaseId": "release-staging",
        "environmentId": "production",
        "status": "running"
    });
    assert!(validate_deployment_release_binding(&lifecycle, &rebound, Some(&existing)).is_err());
}

#[test]
fn published_release_history_cannot_be_rebound_or_removed() {
    let current = json!({
        "release": {
            "artifacts": [{ "id": "artifact-1" }],
            "releases": [{
                "id": "release-1",
                "version": "1.0.0",
                "artifactIds": ["artifact-1"],
                "status": "released",
                "targetEnvironmentId": "production",
                "approvals": [],
                "createdAt": 10,
                "releasedAt": 20,
                "rollbackOf": Value::Null
            }]
        }
    });
    let removed = json!({ "release": { "artifacts": [], "releases": [] } });
    assert!(validate_published_release_history(&current, &removed).is_err());

    let mut rebound = current.clone();
    rebound["release"]["releases"][0]["targetEnvironmentId"] = json!("staging");
    assert!(validate_published_release_history(&current, &rebound).is_err());

    let mut rolled_back = current.clone();
    rolled_back["release"]["releases"][0]["status"] = json!("rolledBack");
    assert!(validate_published_release_history(&current, &rolled_back).is_ok());
}

#[test]
fn published_release_artifacts_must_remain_present() {
    let current = json!({ "release": { "artifacts": [], "releases": [] } });
    let proposed = json!({
        "release": {
            "artifacts": [],
            "releases": [{
                "id": "release-1",
                "version": "1.0.0",
                "artifactIds": ["artifact-1"],
                "status": "released",
                "targetEnvironmentId": "staging",
                "approvals": [],
                "createdAt": 10,
                "releasedAt": 20,
                "rollbackOf": Value::Null
            }]
        }
    });
    assert!(validate_published_release_history(&current, &proposed).is_err());
}
