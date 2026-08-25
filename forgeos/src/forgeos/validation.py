"""Independent, bounded validation command execution."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .config import ValidationCheckConfig
from .errors import ForgeValidationError
from .validation_types import (
    ValidationCheckResult,
    ValidationPurpose,
    ValidationReport,
    ValidationStatus,
    check_identity,
    summarize_levels,
)

OUTPUT_LIMIT = 32_768


class ValidationRunner:
    """Run declared argv checks without invoking a command shell."""

    def __init__(self, workspace: Path, *, clock: Callable[[], str]) -> None:
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace must be an existing directory: {self.workspace}")
        self.clock = clock

    def run(
        self,
        task_id: str,
        checks: tuple[ValidationCheckConfig, ...],
        *,
        purpose: ValidationPurpose = ValidationPurpose.current,
    ) -> ValidationReport:
        if not checks:
            raise ForgeValidationError("at least one validation check is required")
        started_at = self.clock()
        results = tuple(self._run_check(check) for check in checks)
        levels = summarize_levels(results)
        passed = all(result.passed for result in results if result.required)
        return ValidationReport(
            report_id=f"validation-{uuid4()}",
            task_id=task_id,
            purpose=purpose,
            passed=passed,
            started_at=started_at,
            completed_at=self.clock(),
            checks=results,
            levels=levels,
        )

    def _run_check(self, check: ValidationCheckConfig) -> ValidationCheckResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(check.argv),
                cwd=self.workspace,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=check.timeout_seconds,
                check=False,
            )
            return ValidationCheckResult(
                check_id=check_identity(check.name, check.level, check.argv),
                name=check.name,
                level=check.level,
                argv=check.argv,
                required=check.required,
                status=(
                    ValidationStatus.passed
                    if completed.returncode == 0
                    else ValidationStatus.failed
                ),
                exit_code=completed.returncode,
                timed_out=False,
                duration_ms=_duration_ms(started),
                stdout=_bounded_output(completed.stdout),
                stderr=_bounded_output(completed.stderr),
                error=None,
            )
        except subprocess.TimeoutExpired as exc:
            return ValidationCheckResult(
                check_id=check_identity(check.name, check.level, check.argv),
                name=check.name,
                level=check.level,
                argv=check.argv,
                required=check.required,
                status=ValidationStatus.error,
                exit_code=None,
                timed_out=True,
                duration_ms=_duration_ms(started),
                stdout=_bounded_output(_decode_timeout_output(exc.stdout)),
                stderr=_bounded_output(_decode_timeout_output(exc.stderr)),
                error=f"timed out after {check.timeout_seconds} seconds",
            )
        except OSError as exc:
            return ValidationCheckResult(
                check_id=check_identity(check.name, check.level, check.argv),
                name=check.name,
                level=check.level,
                argv=check.argv,
                required=check.required,
                status=ValidationStatus.error,
                exit_code=None,
                timed_out=False,
                duration_ms=_duration_ms(started),
                stdout="",
                stderr="",
                error=f"{type(exc).__name__}: {exc}",
            )


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _bounded_output(value: str) -> str:
    if len(value) <= OUTPUT_LIMIT:
        return value
    return value[:OUTPUT_LIMIT] + "\n[TRUNCATED BY FORGEOS]"
