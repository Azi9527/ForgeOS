"""Minimal fail-closed ForgePolicy gates for Forge-owned execution boundaries."""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .config import ValidationCheckConfig
from .errors import ForgeConfigError, ForgePolicyError
from .models import ForgeTask
from .storage import ForgeStore

SCHEMA_VERSION = 1


class PolicyTarget(str, Enum):
    """Structured operation surfaces currently controlled by ForgeOS."""

    task_path = "TASK_PATH"
    validation_command = "VALIDATION_COMMAND"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Additive DENY rule; N3 deliberately has no user-defined allow override."""

    id: str
    name: str
    target: PolicyTarget
    patterns: tuple[str, ...]
    reason: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyRule":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported PolicyRule schema_version")
        effect = value.get("effect")
        if effect != "DENY":
            raise ValueError("N3 policy files only support additive DENY rules")
        patterns = value.get("patterns")
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(item, str) and item.strip() for item in patterns)
        ):
            raise ValueError("policy patterns must be a non-empty string array")
        return cls(
            id=_text(value, "id", 120),
            name=_text(value, "name", 200),
            target=PolicyTarget(_text(value, "target", 40)),
            patterns=tuple(item.strip() for item in patterns),
            reason=_text(value, "reason", 2_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "effect": "DENY",
            "target": self.target.value,
            "patterns": list(self.patterns),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    rule_id: str
    target: PolicyTarget
    subject: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "target": self.target.value,
            "subject": self.subject,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    id: str
    task_id: str
    evaluated_at: str
    passed: bool
    input_sha256: str
    rules_sha256: str
    rule_ids: tuple[str, ...]
    violations: tuple[PolicyViolation, ...]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "evaluated_at": self.evaluated_at,
            "passed": self.passed,
            "input_sha256": self.input_sha256,
            "rules_sha256": self.rules_sha256,
            "rule_ids": list(self.rule_ids),
            "violations": [item.to_dict() for item in self.violations],
        }


class PolicyEngine:
    """Evaluate paths and validation argv before ForgeOS starts external work."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def rules(self) -> tuple[PolicyRule, ...]:
        rules = list(_built_in_rules())
        try:
            values = self.store.list_records("policies")
            rules.extend(PolicyRule.from_dict(value) for value in values)
        except ValueError as exc:
            raise ForgeConfigError(f"invalid ForgePolicy file: {exc}") from exc
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ForgeConfigError("ForgePolicy rule ids must be unique")
        return tuple(sorted(rules, key=lambda rule: rule.id))

    def enforce_task(
        self, task: ForgeTask, checks: tuple[ValidationCheckConfig, ...]
    ) -> PolicyEvaluation:
        rules = self.rules()
        violations = [
            *self._path_violations(task.related_modules, rules),
            *self._command_violations(checks, rules),
        ]
        payload = {
            "task_id": task.id,
            "related_modules": list(task.related_modules),
            "validation_argv": [list(check.argv) for check in checks],
        }
        evaluation = self._evaluation(task.id, payload, rules, tuple(violations))
        self.store.write_record(
            f"policy/evaluations/{task.id}/{evaluation.id}.json", evaluation.to_dict()
        )
        self.audit.append(
            "policy.evaluated" if evaluation.passed else "policy.denied",
            actor=AuditActor.system,
            task_id=task.id,
            payload={
                "evaluation_id": evaluation.id,
                "passed": evaluation.passed,
                "rule_ids": list(evaluation.rule_ids),
                "violations": [item.to_dict() for item in evaluation.violations],
            },
        )
        if not evaluation.passed:
            reasons = "; ".join(
                f"{item.rule_id}: {item.subject} ({item.reason})" for item in evaluation.violations
            )
            raise ForgePolicyError(f"ForgePolicy denied task {task.id}: {reasons}")
        return evaluation

    def evaluations(self, task_id: str) -> tuple[dict[str, Any], ...]:
        return self.store.list_records(f"policy/evaluations/{task_id}")

    def _path_violations(
        self, paths: Iterable[str], rules: tuple[PolicyRule, ...]
    ) -> list[PolicyViolation]:
        result: list[PolicyViolation] = []
        for raw in paths:
            normalized = raw.strip().replace("\\", "/")
            path = Path(raw)
            if path.is_absolute():
                resolved = path.resolve(strict=False)
            else:
                resolved = (self.store.project_root / path).resolve(strict=False)
            if not resolved.is_relative_to(self.store.project_root):
                result.append(
                    PolicyViolation(
                        "builtin.workspace-boundary",
                        PolicyTarget.task_path,
                        normalized,
                        "task path escapes the workspace",
                    )
                )
            for rule in rules:
                if rule.target is not PolicyTarget.task_path:
                    continue
                if any(_path_matches(normalized, pattern) for pattern in rule.patterns):
                    result.append(PolicyViolation(rule.id, rule.target, normalized, rule.reason))
        return _unique(result)

    def _command_violations(
        self, checks: Iterable[ValidationCheckConfig], rules: tuple[PolicyRule, ...]
    ) -> list[PolicyViolation]:
        result: list[PolicyViolation] = []
        for check in checks:
            command = _normalize_argv(check.argv)
            for rule in rules:
                if rule.target is not PolicyTarget.validation_command:
                    continue
                if any(_command_matches(command, pattern) for pattern in rule.patterns):
                    result.append(PolicyViolation(rule.id, rule.target, command, rule.reason))
        return _unique(result)

    def _evaluation(
        self,
        task_id: str,
        payload: dict[str, Any],
        rules: tuple[PolicyRule, ...],
        violations: tuple[PolicyViolation, ...],
    ) -> PolicyEvaluation:
        input_value = _canonical(payload)
        rule_value = _canonical([rule.to_dict() for rule in rules])
        return PolicyEvaluation(
            id=f"policy-evaluation-{uuid4()}",
            task_id=task_id,
            evaluated_at=self.clock(),
            passed=not violations,
            input_sha256=hashlib.sha256(input_value.encode()).hexdigest(),
            rules_sha256=hashlib.sha256(rule_value.encode()).hexdigest(),
            rule_ids=tuple(rule.id for rule in rules),
            violations=violations,
        )


def _built_in_rules() -> tuple[PolicyRule, ...]:
    return (
        PolicyRule(
            id="builtin.protect-git-metadata",
            name="Protect Git metadata",
            target=PolicyTarget.task_path,
            patterns=(".git", ".git/**", "**/.git", "**/.git/**"),
            reason="ForgeOS tasks must not target Git metadata",
        ),
        PolicyRule(
            id="builtin.validation-nondestructive",
            name="Validation must be non-destructive",
            target=PolicyTarget.validation_command,
            patterns=(
                "rm *",
                "rmdir *",
                "del *",
                "format *",
                "shutdown *",
                "reboot *",
                "git reset*",
                "git clean*",
                "git checkout*",
                "git restore*",
                "git commit*",
                "git push*",
            ),
            reason="validation commands may observe or test but may not mutate source/history",
        ),
    )


def _path_matches(subject: str, pattern: str) -> bool:
    subject = str(PurePosixPath(subject)).lower()
    pattern = pattern.lower()
    while subject.startswith("./"):
        subject = subject[2:]
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return subject == prefix or subject.startswith(f"{prefix}/")
    if pattern.startswith("**/"):
        suffix = pattern[3:]
        return subject == suffix or subject.endswith(f"/{suffix}")
    return PurePosixPath(subject).match(pattern)


def _command_matches(subject: str, pattern: str) -> bool:
    pattern = pattern.casefold().strip()
    subject = subject.casefold()
    if pattern.endswith("*"):
        return subject.startswith(pattern[:-1])
    if pattern.endswith(" *"):
        prefix = pattern[:-2]
        return subject == prefix or subject.startswith(f"{prefix} ")
    return subject == pattern


def _normalize_argv(argv: tuple[str, ...]) -> str:
    if not argv:
        return ""
    executable = Path(argv[0]).name.casefold()
    if executable.endswith(".exe") or executable.endswith(".cmd"):
        executable = executable.rsplit(".", 1)[0]
    return " ".join((executable, *(item.strip() for item in argv[1:]))).strip()


def _unique(items: list[PolicyViolation]) -> list[PolicyViolation]:
    result: list[PolicyViolation] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.rule_id, item.subject)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: dict[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    normalized = item.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{key} exceeds {maximum} characters")
    return normalized
