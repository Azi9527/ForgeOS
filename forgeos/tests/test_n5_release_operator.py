import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from forgeos.audit import AuditActor
from forgeos.audit_query import AuditQueryService
from forgeos.bundle import ForgeBundleService
from forgeos.cli import main
from forgeos.errors import ForgeBundleError, ForgeConflictError
from forgeos.integrity import IntegrityService
from forgeos.migration import ProtocolMigrator
from forgeos.models import TaskType
from forgeos.policy import PolicyEngine, PolicyTarget
from forgeos.policy_admin import PolicyAdminService
from forgeos.protocol_fixtures import ProtocolFixtureVerifier
from forgeos.release import PACKAGE_VERSION, ReleaseReadinessService
from forgeos.service import ForgeService

NOW = "2026-08-25T01:00:00Z"


def initialized(path: Path, *, name: str = "N5") -> ForgeService:
    service = ForgeService(path, clock=lambda: NOW)
    service.init_project(name=name)
    return service


def test_protocol_v1_fixtures_are_canonical_and_versioned() -> None:
    results = ProtocolFixtureVerifier().verify()

    assert len(results) == 4
    assert all(result.passed for result in results)
    assert {result.name for result in results} == {
        "forge_config.json",
        "task_created.json",
        "policy_deny.json",
        "protocol.json",
    }
    assert all(len(result.sha256) == 64 for result in results)


def test_audit_query_is_filtered_bounded_and_cursor_stable(tmp_path: Path) -> None:
    forge = initialized(tmp_path)
    for index in range(3):
        forge.create_task(
            title=f"Audit {index}",
            task_type=TaskType.test,
            objective="Exercise audit pagination",
            acceptance_criteria=("query is stable",),
        )
    query = AuditQueryService(forge.audit)

    first = query.query(event_type="task.created", limit=2)
    second = query.query(
        event_type="task.created",
        after_sequence=first.next_cursor or 0,
        limit=2,
    )

    assert len(first.events) == 2
    assert first.next_cursor == first.events[-1].sequence
    assert len(second.events) == 1
    assert second.next_cursor is None
    assert first.events[-1].sequence < second.events[0].sequence
    assert query.query(actor=AuditActor.human).matched == 3
    assert query.query(actor=AuditActor.system).matched == 1
    with pytest.raises(ValueError, match="between 1 and 200"):
        query.query(limit=201)


def test_policy_admin_preserves_retired_rules_and_human_authority(tmp_path: Path) -> None:
    forge = initialized(tmp_path)
    admin = PolicyAdminService(forge.store, clock=lambda: NOW)

    with pytest.raises(ForgeConflictError, match="non-human"):
        admin.create(
            rule_id="project.no-secrets",
            name="No secret paths",
            target=PolicyTarget.task_path,
            patterns=("secrets/**",),
            reason="Secrets need a separate workflow",
            created_by="codex-agent",
        )
    created = admin.create(
        rule_id="project.no-secrets",
        name="No secret paths",
        target=PolicyTarget.task_path,
        patterns=("secrets/**",),
        reason="Secrets need a separate workflow",
        created_by="maintainer",
    )
    retired = admin.retire(
        created.rule.id,
        retired_by="maintainer",
        reason="Replaced by repository rules",
    )

    assert created.active is True
    assert retired.active is False
    assert retired.retirement_reason == "Replaced by repository rules"
    assert len(admin.list()) == 3
    assert {rule.id for rule in PolicyEngine(forge.store, clock=lambda: NOW).rules()} == {
        "builtin.protect-git-metadata",
        "builtin.validation-nondestructive",
    }
    assert (forge.store.forge_dir / "policies/retired/project.no-secrets.json").is_file()
    forge.store.write_record(
        "policies/manual-file.json",
        {
            "schema_version": 1,
            "id": "project.manual-name",
            "name": "Manual filename",
            "effect": "DENY",
            "target": "TASK_PATH",
            "patterns": ["manual/**"],
            "reason": "manual policy fixture",
        },
    )
    admin.retire(
        "project.manual-name",
        retired_by="maintainer",
        reason="manual policy retired",
    )
    assert (forge.store.forge_dir / "policies/retired/manual-file.json").is_file()
    with pytest.raises(ForgeConflictError, match="built-in"):
        admin.retire(
            "builtin.validation-nondestructive",
            retired_by="maintainer",
            reason="unsafe request",
        )


def test_bundle_export_verify_and_atomic_import_rebinds_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    forge = initialized(source, name="Bundle Source")
    task = forge.create_task(
        title="Portable task",
        task_type=TaskType.feature,
        objective="Move evidence safely",
        acceptance_criteria=("hashes verify",),
    )
    bundle_path = tmp_path / "forgeos-export.zip"

    exported = ForgeBundleService(forge.store, clock=lambda: NOW).export(bundle_path)
    imported = ForgeBundleService(
        ForgeService(target, clock=lambda: NOW).store,
        clock=lambda: NOW,
    ).import_bundle(bundle_path)
    restored = ForgeService(target, clock=lambda: NOW)

    assert exported == imported
    assert restored.config().project.root == str(target.resolve())
    assert restored.task(task.id).title == task.title
    assert IntegrityService(restored.store, clock=lambda: NOW).scan().passed is True
    with zipfile.ZipFile(bundle_path) as archive:
        names = archive.namelist()
        assert names[0] == "manifest.json"
        assert names[1:] == sorted(names[1:])
        assert all(info.date_time == (2020, 1, 1, 0, 0, 0) for info in archive.infolist())
    with pytest.raises(ForgeConflictError, match="without .forge"):
        ForgeBundleService(restored.store, clock=lambda: NOW).import_bundle(bundle_path)


def test_bundle_verification_rejects_duplicate_or_tampered_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    forge = initialized(source)
    bundle_path = tmp_path / "forgeos-export.zip"
    bundles = ForgeBundleService(forge.store, clock=lambda: NOW)
    bundles.export(bundle_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(bundle_path, "a") as archive:
            archive.writestr("files/protocol.json", b"tampered")

    with pytest.raises(ForgeBundleError, match="duplicate"):
        bundles.verify(bundle_path)

    symlink_path = tmp_path / "symlink.zip"
    payload = b"x"
    manifest = {
        "schema_version": 1,
        "source_project_id": "project-symlink",
        "source_project_name": "Unsafe",
        "protocol_version": 1,
        "entries": [
            {
                "path": "protocol.json",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(symlink_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        info = zipfile.ZipInfo("files/protocol.json")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, payload)
    with pytest.raises(ForgeBundleError):
        bundles.verify(symlink_path)


def test_release_readiness_persists_six_passing_gates(tmp_path: Path) -> None:
    forge = initialized(tmp_path)
    release = ReleaseReadinessService(forge.store, clock=lambda: NOW)

    report = release.check()

    assert report.passed is True
    assert report.package_version == PACKAGE_VERSION == "0.2.1"
    assert len(report.checks) == 6
    assert release.latest()["id"] == report.id
    assert forge.audit.read_all()[-1].event_type == "release.readiness_checked"


def test_n5_layout_extension_is_explicit_and_additive(tmp_path: Path) -> None:
    forge = initialized(tmp_path)
    retired = forge.store.forge_dir / "policies" / "retired"
    retired.rmdir()
    migrator = ProtocolMigrator(forge.store, clock=lambda: NOW)

    plan = migrator.plan()
    record = migrator.apply()

    assert plan.required is True
    assert plan.from_version == plan.to_version == 1
    assert plan.actions == ("create directory .forge/policies/retired",)
    assert record.actions == plan.actions
    assert retired.is_dir()


def test_cli_n5_release_audit_policy_and_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    bundle_path = tmp_path / "cli-export.zip"
    assert main(("--workspace", str(source), "init", "--name", "N5 CLI")) == 0
    capsys.readouterr()
    assert main(("--workspace", str(source), "release", "fixtures")) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert (
        main(
            (
                "--workspace",
                str(source),
                "policy",
                "new",
                "--id",
                "project.cli-deny",
                "--name",
                "CLI deny",
                "--target",
                "TASK_PATH",
                "--pattern",
                "private/**",
                "--reason",
                "operator policy",
                "--created-by",
                "maintainer",
            )
        )
        == 0
    )
    capsys.readouterr()
    assert main(("--workspace", str(source), "audit", "--event-type", "policy.created")) == 0
    assert json.loads(capsys.readouterr().out)["matched"] == 1
    assert main(("--workspace", str(source), "bundle", "export", str(bundle_path))) == 0
    capsys.readouterr()
    assert main(("--workspace", str(source), "bundle", "verify", str(bundle_path))) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert main(("--workspace", str(target), "bundle", "import", str(bundle_path))) == 0
    capsys.readouterr()
    assert ForgeService(target, clock=lambda: NOW).config().project.name == "N5 CLI"
