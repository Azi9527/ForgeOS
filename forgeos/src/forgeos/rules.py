"""Deterministic, file-backed ForgeRules with explicit source authority."""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .errors import ForgeConfigError
from .models import ForgeTask
from .storage import ForgeStore

SCHEMA_VERSION = 1
MAX_RULE_BYTES = 8_192


class RuleScope(str, Enum):
    """Specificity layer used for deterministic Rule resolution."""

    global_scope = "GLOBAL"
    project = "PROJECT"
    module = "MODULE"
    task = "TASK"


class RuleSeverity(str, Enum):
    """Required ForgeRules severity values."""

    info = "INFO"
    warning = "WARNING"
    block = "BLOCK"


class RuleEnforcement(str, Enum):
    """Whether a Rule guides the model or is mechanically enforced."""

    prompt_guidance = "PROMPT_GUIDANCE"
    validator = "VALIDATOR"
    policy_gate = "POLICY_GATE"


@dataclass(frozen=True, slots=True)
class RuleRecord:
    """One resolved Rule with stable identity, source and content hash."""

    id: str
    name: str
    scope: RuleScope
    severity: RuleSeverity
    enforcement: RuleEnforcement
    description: str
    source_path: str
    source_sha256: str
    selector: str | None = None
    version: int = 1
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "scope": self.scope.value,
            "severity": self.severity.value,
            "enforcement": self.enforcement.value,
            "description": self.description,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "selector": self.selector,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class RuleResolution:
    """Immutable ordered Rule set selected for one ForgeTask."""

    task_id: str
    resolved_at: str
    rules: tuple[RuleRecord, ...]
    content_sha256: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "resolved_at": self.resolved_at,
            "rules": [rule.to_dict() for rule in self.rules],
            "content_sha256": self.content_sha256,
        }


class RuleResolver:
    """Resolve `.forge/rules/**/*.md` without implicit overrides."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock

    def resolve(self, task: ForgeTask) -> RuleResolution:
        loaded = self._load_all()
        selected = tuple(
            rule
            for rule in loaded
            if rule.scope in {RuleScope.global_scope, RuleScope.project}
            or rule.scope is RuleScope.task
            and rule.selector == task.id
            or rule.scope is RuleScope.module
            and rule.selector in task.related_modules
        )
        ordered = tuple(sorted(selected, key=_rule_sort_key))
        digest = hashlib.sha256(
            json.dumps(
                [rule.to_dict() for rule in ordered],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return RuleResolution(
            task_id=task.id,
            resolved_at=self.clock(),
            rules=ordered,
            content_sha256=digest,
        )

    def _load_all(self) -> tuple[RuleRecord, ...]:
        root = self.store.forge_dir / "rules"
        if not root.exists():
            return ()
        records: list[RuleRecord] = []
        ids: set[str] = set()
        names_by_scope: set[tuple[RuleScope, str]] = set()
        for path in sorted(root.rglob("*.md")):
            _reject_symlink_path(path, root=root)
            rule = _parse_rule(path, project_root=self.store.project_root)
            if rule.id in ids:
                raise ForgeConfigError(f"duplicate Rule id: {rule.id}")
            name_key = (rule.scope, rule.name.casefold())
            if name_key in names_by_scope:
                raise ForgeConfigError(f"conflicting Rule name in {rule.scope.value}: {rule.name}")
            ids.add(rule.id)
            names_by_scope.add(name_key)
            records.append(rule)
        return tuple(records)


def _parse_rule(path: Path, *, project_root: Path) -> RuleRecord:
    raw = path.read_bytes()
    if len(raw) > MAX_RULE_BYTES:
        raise ForgeConfigError(f"Rule exceeds {MAX_RULE_BYTES} bytes: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ForgeConfigError(f"Rule must be UTF-8: {path}") from exc
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise ForgeConfigError(f"Rule must start with JSON front matter: {path}")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise ForgeConfigError(f"Rule front matter is not closed: {path}") from exc
    metadata_text = "\n".join(lines[1:closing]).strip()
    try:
        metadata = json.loads(metadata_text)
    except json.JSONDecodeError as exc:
        raise ForgeConfigError(f"Rule front matter must be a JSON object: {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ForgeConfigError(f"Rule front matter must be an object: {path}")
    description = "\n".join(lines[closing + 1 :]).strip()
    if not description:
        raise ForgeConfigError(f"Rule description must not be empty: {path}")
    scope = RuleScope(_metadata_string(metadata, "scope"))
    selector = metadata.get("selector")
    if selector is not None and (not isinstance(selector, str) or not selector.strip()):
        raise ForgeConfigError(f"Rule selector must be null or a non-empty string: {path}")
    if scope in {RuleScope.module, RuleScope.task} and selector is None:
        raise ForgeConfigError(f"{scope.value} Rule requires selector: {path}")
    if scope in {RuleScope.global_scope, RuleScope.project} and selector is not None:
        raise ForgeConfigError(f"{scope.value} Rule must not define selector: {path}")
    version = metadata.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise ForgeConfigError(f"Rule version must be a positive integer: {path}")
    return RuleRecord(
        id=_rule_id(_metadata_string(metadata, "id")),
        name=_bounded(_metadata_string(metadata, "name"), field="Rule name", maximum=200),
        scope=scope,
        severity=RuleSeverity(_metadata_string(metadata, "severity")),
        enforcement=RuleEnforcement(_metadata_string(metadata, "enforcement")),
        description=_bounded(description, field="Rule description", maximum=7_000),
        source_path=path.relative_to(project_root).as_posix(),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        selector=selector.strip() if isinstance(selector, str) else None,
        version=version,
    )


def _reject_symlink_path(path: Path, *, root: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ForgeConfigError(f"Rule path must not contain a symbolic link: {path}")
        if current == root:
            return
        if current.parent == current:
            raise ForgeConfigError(f"Rule path escapes the rules root: {path}")
        current = current.parent


def _rule_sort_key(rule: RuleRecord) -> tuple[int, str, str]:
    rank = {
        RuleScope.global_scope: 0,
        RuleScope.project: 1,
        RuleScope.module: 2,
        RuleScope.task: 3,
    }
    return (rank[rule.scope], rule.id, rule.source_path)


def _metadata_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ForgeConfigError(f"Rule {key} must be a non-empty string")
    return item.strip()


def _rule_id(value: str) -> str:
    normalized = _bounded(value, field="Rule id", maximum=120)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./"
    if any(character not in allowed for character in normalized):
        raise ForgeConfigError("Rule id contains unsupported characters")
    return normalized


def _bounded(value: str, *, field: str, maximum: int) -> str:
    if not value.strip():
        raise ForgeConfigError(f"{field} must not be empty")
    if len(value) > maximum:
        raise ForgeConfigError(f"{field} exceeds {maximum} characters")
    return value
