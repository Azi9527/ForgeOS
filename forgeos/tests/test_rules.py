import json
from pathlib import Path

import pytest

from forgeos.errors import ForgeConfigError
from forgeos.models import TaskType
from forgeos.rules import RuleResolver, RuleScope, RuleSeverity
from forgeos.service import ForgeService


def initialized(tmp_path: Path) -> ForgeService:
    service = ForgeService(tmp_path, clock=lambda: "2026-08-24T00:00:00Z")
    service.init_project(name="Rules")
    return service


def write_rule(
    root: Path,
    filename: str,
    *,
    rule_id: str,
    name: str,
    scope: str,
    severity: str = "WARNING",
    selector: str | None = None,
    description: str = "Follow the declared engineering rule.",
) -> None:
    metadata = {
        "id": rule_id,
        "name": name,
        "scope": scope,
        "severity": severity,
        "enforcement": "PROMPT_GUIDANCE",
        "version": 1,
    }
    if selector is not None:
        metadata["selector"] = selector
    path = root / ".forge" / "rules" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n{json.dumps(metadata, ensure_ascii=False)}\n---\n{description}\n",
        encoding="utf-8",
    )


def task(service: ForgeService):
    return service.create_task(
        title="Resolve Rules",
        task_type=TaskType.feature,
        objective="Build deterministic context",
        acceptance_criteria=("rules resolved",),
        related_modules=("backend",),
    )


def test_resolves_rules_in_specificity_order_with_sources_and_hashes(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    actual_task = task(service)
    write_rule(tmp_path, "z-global.md", rule_id="R-G", name="Global", scope="GLOBAL")
    write_rule(tmp_path, "project.md", rule_id="R-P", name="Project", scope="PROJECT")
    write_rule(
        tmp_path,
        "module.md",
        rule_id="R-M",
        name="Module",
        scope="MODULE",
        selector="backend",
    )
    write_rule(
        tmp_path,
        "task.md",
        rule_id="R-T",
        name="Task",
        scope="TASK",
        selector=actual_task.id,
        severity="BLOCK",
    )

    resolution = RuleResolver(service.store, clock=service.clock).resolve(actual_task)

    assert [rule.scope for rule in resolution.rules] == [
        RuleScope.global_scope,
        RuleScope.project,
        RuleScope.module,
        RuleScope.task,
    ]
    assert resolution.rules[-1].severity is RuleSeverity.block
    assert all(rule.source_path.startswith(".forge/rules/") for rule in resolution.rules)
    assert len(resolution.content_sha256) == 64


def test_unselected_module_and_task_rules_do_not_enter_resolution(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    actual_task = task(service)
    write_rule(
        tmp_path,
        "other-module.md",
        rule_id="R-M",
        name="Other module",
        scope="MODULE",
        selector="frontend",
    )
    write_rule(
        tmp_path,
        "other-task.md",
        rule_id="R-T",
        name="Other task",
        scope="TASK",
        selector="FORGE-9999",
    )

    resolution = RuleResolver(service.store, clock=service.clock).resolve(actual_task)

    assert resolution.rules == ()


def test_duplicate_id_and_same_scope_name_fail_closed(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    actual_task = task(service)
    write_rule(tmp_path, "one.md", rule_id="R-1", name="Collision", scope="PROJECT")
    write_rule(tmp_path, "two.md", rule_id="R-1", name="Other", scope="GLOBAL")

    with pytest.raises(ForgeConfigError, match="duplicate Rule id"):
        RuleResolver(service.store, clock=service.clock).resolve(actual_task)

    (tmp_path / ".forge" / "rules" / "two.md").unlink()
    write_rule(tmp_path, "two.md", rule_id="R-2", name="Collision", scope="PROJECT")
    with pytest.raises(ForgeConfigError, match="conflicting Rule name"):
        RuleResolver(service.store, clock=service.clock).resolve(actual_task)


def test_rule_parser_rejects_missing_selector_and_unbounded_content(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    actual_task = task(service)
    write_rule(tmp_path, "missing.md", rule_id="R-M", name="Missing", scope="MODULE")

    with pytest.raises(ForgeConfigError, match="requires selector"):
        RuleResolver(service.store, clock=service.clock).resolve(actual_task)

    (tmp_path / ".forge" / "rules" / "missing.md").unlink()
    write_rule(
        tmp_path,
        "large.md",
        rule_id="R-L",
        name="Large",
        scope="PROJECT",
        description="x" * 9_000,
    )
    with pytest.raises(ForgeConfigError, match="exceeds 8192 bytes"):
        RuleResolver(service.store, clock=service.clock).resolve(actual_task)
