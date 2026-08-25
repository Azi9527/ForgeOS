import subprocess
from pathlib import Path

from forgeos.git_evidence import GitEvidenceService, GitSnapshot
from forgeos.service import ForgeService


def git(workspace: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=workspace, check=True, capture_output=True)


def initialized_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "forgeos@example.invalid")
    git(tmp_path, "config", "user.name", "ForgeOS Tests")
    source = tmp_path / "source.txt"
    source.write_text("baseline\n", encoding="utf-8")
    git(tmp_path, "add", "source.txt")
    git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def test_captures_clean_and_dirty_git_evidence_without_mutating_repo(tmp_path: Path) -> None:
    workspace = initialized_repo(tmp_path)
    service = GitEvidenceService(workspace, clock=lambda: "2026-08-24T00:00:00Z")
    baseline = service.capture("FORGE-0001", kind="baseline")
    (workspace / "source.txt").write_text("changed\n", encoding="utf-8")
    (workspace / "新文件.txt").write_text("new\n", encoding="utf-8")
    current = service.capture("FORGE-0001", kind="current")

    assert baseline.available is True
    assert baseline.dirty is False
    assert baseline.changed_files == ()
    assert baseline.head is not None
    assert current.available is True
    assert current.dirty is True
    assert current.head == baseline.head
    assert current.changed_files == ("source.txt", "新文件.txt")
    assert current.diff_sha256 != baseline.diff_sha256


def test_non_repository_is_explicitly_unavailable(tmp_path: Path) -> None:
    actual = GitEvidenceService(tmp_path, clock=lambda: "2026-08-24T00:00:00Z").capture(
        "FORGE-0001",
        kind="baseline",
    )

    assert actual.available is False
    assert actual.warning == "workspace is not a Git repository"
    assert actual.changed_files == ()


def test_git_snapshot_persists_as_versioned_evidence(tmp_path: Path) -> None:
    initialized_repo(tmp_path)
    forge = ForgeService(tmp_path, clock=lambda: "2026-08-24T00:00:00Z")
    forge.init_project(name="Git Evidence")
    service = GitEvidenceService(tmp_path, clock=lambda: "2026-08-24T00:00:00Z")

    snapshot = service.capture_and_store(forge.store, "FORGE-0001", kind="baseline")
    record = forge.store.read_json(
        forge.store.forge_dir / "evidence" / "git" / "FORGE-0001" / f"{snapshot.id}.json"
    )

    assert GitSnapshot.from_dict(record) == snapshot
