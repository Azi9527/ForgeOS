"""ForgeOS project configuration schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ForgeConfigError
from .models import SCHEMA_VERSION, ForgeProject
from .validation_types import ValidationLevel


@dataclass(frozen=True, slots=True)
class ValidationCheckConfig:
    """One validation command executed without a command shell."""

    name: str
    argv: tuple[str, ...]
    level: ValidationLevel = ValidationLevel.unit
    timeout_seconds: int = 60
    required: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ForgeConfigError("validation check name must not be empty")
        if not self.argv or any(not item for item in self.argv):
            raise ForgeConfigError("validation check argv must contain non-empty arguments")
        if not 1 <= self.timeout_seconds <= 3_600:
            raise ForgeConfigError("validation timeout_seconds must be between 1 and 3600")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "level": self.level.value,
            "timeout_seconds": self.timeout_seconds,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ValidationCheckConfig:
        name = value.get("name")
        argv = value.get("argv")
        timeout = value.get("timeout_seconds", 60)
        required = value.get("required", True)
        level = value.get("level", ValidationLevel.unit.value)
        if not isinstance(name, str):
            raise ForgeConfigError("validation check name must be a string")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ForgeConfigError("validation check argv must be an array of strings")
        if not isinstance(timeout, int):
            raise ForgeConfigError("validation timeout_seconds must be an integer")
        if not isinstance(required, bool):
            raise ForgeConfigError("validation required must be a boolean")
        if not isinstance(level, str):
            raise ForgeConfigError("validation level must be a string")
        try:
            parsed_level = ValidationLevel(level)
        except ValueError as exc:
            raise ForgeConfigError(f"unsupported validation level: {level!r}") from exc
        return cls(
            name=name,
            argv=tuple(argv),
            level=parsed_level,
            timeout_seconds=timeout,
            required=required,
        )


@dataclass(frozen=True, slots=True)
class ForgeConfig:
    """Versioned ForgeOS configuration stored in `.forge/forge.yaml`."""

    project: ForgeProject
    task_prefix: str = "FORGE"
    validation_checks: tuple[ValidationCheckConfig, ...] = ()
    repair_limit: int = 3
    execution_attempt_limit: int = 8
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.task_prefix or not self.task_prefix.isascii() or not self.task_prefix.isalpha():
            raise ForgeConfigError("task_prefix must contain ASCII letters only")
        if not 0 <= self.repair_limit <= 20:
            raise ForgeConfigError("repair_limit must be between 0 and 20")
        if not 1 <= self.execution_attempt_limit <= 100:
            raise ForgeConfigError("execution_attempt_limit must be between 1 and 100")
        names = [check.name for check in self.validation_checks]
        if len(set(names)) != len(names):
            raise ForgeConfigError("validation check names must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project.to_dict(),
            "task": {"prefix": self.task_prefix},
            "validation": {
                "checks": [check.to_dict() for check in self.validation_checks],
            },
            "repair": {"limit": self.repair_limit},
            "execution": {"attempt_limit": self.execution_attempt_limit},
            "runtime": {
                "provider": "openai-codex-python-sdk",
                "approval_policy": "deny_all",
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ForgeConfig:
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ForgeConfigError(
                f"unsupported ForgeConfig schema_version: {value.get('schema_version')!r}"
            )
        project = value.get("project")
        task = value.get("task")
        validation = value.get("validation", {})
        repair = value.get("repair", {})
        execution = value.get("execution", {})
        if not isinstance(project, dict):
            raise ForgeConfigError("project must be an object")
        if not isinstance(task, dict) or not isinstance(task.get("prefix"), str):
            raise ForgeConfigError("task.prefix must be a string")
        if not isinstance(validation, dict) or not isinstance(validation.get("checks", []), list):
            raise ForgeConfigError("validation.checks must be an array")
        if not isinstance(repair, dict) or not isinstance(repair.get("limit", 3), int):
            raise ForgeConfigError("repair.limit must be an integer")
        if not isinstance(execution, dict) or not isinstance(
            execution.get("attempt_limit", 8), int
        ):
            raise ForgeConfigError("execution.attempt_limit must be an integer")
        try:
            loaded_project = ForgeProject.from_dict(project)
            checks = tuple(
                ValidationCheckConfig.from_dict(check)
                for check in validation.get("checks", [])
                if isinstance(check, dict)
            )
        except ValueError as exc:
            raise ForgeConfigError(str(exc)) from exc
        if len(checks) != len(validation.get("checks", [])):
            raise ForgeConfigError("each validation check must be an object")
        return cls(
            project=loaded_project,
            task_prefix=task["prefix"],
            validation_checks=checks,
            repair_limit=repair.get("limit", 3),
            execution_attempt_limit=execution.get("attempt_limit", 8),
        )
