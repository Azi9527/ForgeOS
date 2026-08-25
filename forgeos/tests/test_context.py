import json
from dataclasses import replace
from pathlib import Path

from forgeos.context import ContextAuthority, ContextPackage, ContextPackageBuilder
from forgeos.git_evidence import GitSnapshot
from forgeos.models import TaskType
from forgeos.service import ForgeService


def fixture(tmp_path: Path):
    def clock() -> str:
        return "2026-08-24T00:00:00Z"

    service = ForgeService(tmp_path, clock=clock)
    service.init_project(name="Context")
    task = service.create_task(
        title="Bound context",
        task_type=TaskType.feature,
        objective="Implement the bounded context package",
        acceptance_criteria=("context is deterministic",),
    )
    metadata = {
        "id": "RULE-1",
        "name": "No secrets",
        "scope": "PROJECT",
        "severity": "BLOCK",
        "enforcement": "PROMPT_GUIDANCE",
    }
    (tmp_path / ".forge" / "rules" / "project.md").write_text(
        f"---\n{json.dumps(metadata)}\n---\nNever expose token=super-secret-value\n",
        encoding="utf-8",
    )
    git = GitSnapshot(
        id="git-baseline",
        task_id=task.id,
        kind="baseline",
        captured_at=clock(),
        available=True,
        repository_root=str(tmp_path),
        head="a" * 40,
        branch="main",
        detached=False,
        dirty=False,
        changed_files=(),
        status_sha256="b" * 64,
        diff_sha256="c" * 64,
    )
    return service, task, git, clock


def test_context_is_deterministic_bounded_and_keeps_user_authority_separate(
    tmp_path: Path,
) -> None:
    service, task, git, clock = fixture(tmp_path)
    builder = ContextPackageBuilder(service.store, clock=clock)

    first = builder.build(task, git)
    second = builder.build(task, git)

    assert first == second
    assert first.total_bytes <= 32_768
    assert all(fragment.size_bytes <= 8_192 for fragment in first.fragments)
    assert [fragment.authority for fragment in first.fragments] == [
        ContextAuthority.runtime_data,
        ContextAuthority.user,
        ContextAuthority.developer,
        ContextAuthority.runtime_data,
    ]
    instructions = first.developer_instructions()
    assert task.objective not in instructions
    assert "super-secret-value" not in instructions
    assert "[REDACTED]" in instructions


def test_context_truncates_at_fragment_and_package_limits(tmp_path: Path) -> None:
    service, task, git, clock = fixture(tmp_path)
    task = service.create_task(
        title="Large context",
        task_type=TaskType.feature,
        objective="中" * 3_000,
        acceptance_criteria=("bounded",),
    )
    git = replace(git, task_id=task.id)
    builder = ContextPackageBuilder(
        service.store,
        clock=clock,
        fragment_limit=1_024,
        package_limit=2_048,
    )

    package = builder.build(task, git)

    assert package.total_bytes <= 2_048
    assert package.truncated is True
    assert any(fragment.truncated for fragment in package.fragments)


def test_context_package_persists_and_round_trips(tmp_path: Path) -> None:
    service, task, git, clock = fixture(tmp_path)
    builder = ContextPackageBuilder(service.store, clock=clock)

    package = builder.build_and_store(task, git)
    record = service.store.read_json(
        service.store.forge_dir / "context" / "packages" / task.id / f"{package.id}.json"
    )

    assert ContextPackage.from_dict(record) == package
