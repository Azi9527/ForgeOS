"""Explicit, persisted execution and repair budget gates."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .errors import ForgeBudgetError
from .execution_records import ExecutionAttemptRepository
from .models import ForgeTask
from .storage import ForgeStore


@dataclass(frozen=True, slots=True)
class BudgetEvaluation:
    """One immutable snapshot of Task budget consumption."""

    id: str
    task_id: str
    evaluated_at: str
    passed: bool
    execution_attempt_limit: int
    execution_attempts_used: int
    execution_attempts_remaining: int
    repair_limit: int
    repair_attempts_used: int
    repair_attempts_remaining: int
    input_sha256: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "evaluated_at": self.evaluated_at,
            "passed": self.passed,
            "execution_attempt_limit": self.execution_attempt_limit,
            "execution_attempts_used": self.execution_attempts_used,
            "execution_attempts_remaining": self.execution_attempts_remaining,
            "repair_limit": self.repair_limit,
            "repair_attempts_used": self.repair_attempts_used,
            "repair_attempts_remaining": self.repair_attempts_remaining,
            "input_sha256": self.input_sha256,
        }


class BudgetService:
    """Evaluate budgets before ForgeOS starts baseline or Codex work."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.attempts = ExecutionAttemptRepository(store)
        self.audit = AuditLog(store, clock=clock)

    def evaluate(self, task: ForgeTask, *, persist: bool = True) -> BudgetEvaluation:
        config = self.store.load_config()
        execution_used = len(self.attempts.list_for_task(task.id))
        repair_used = task.repair_attempts
        execution_remaining = max(0, config.execution_attempt_limit - execution_used)
        repair_remaining = max(0, config.repair_limit - repair_used)
        passed = execution_used < config.execution_attempt_limit
        payload = {
            "task_id": task.id,
            "task_revision": task.revision,
            "execution_attempt_limit": config.execution_attempt_limit,
            "execution_attempts_used": execution_used,
            "repair_limit": config.repair_limit,
            "repair_attempts_used": repair_used,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        evaluation = BudgetEvaluation(
            id=f"budget-{uuid4()}",
            task_id=task.id,
            evaluated_at=self.clock(),
            passed=passed,
            execution_attempt_limit=config.execution_attempt_limit,
            execution_attempts_used=execution_used,
            execution_attempts_remaining=execution_remaining,
            repair_limit=config.repair_limit,
            repair_attempts_used=repair_used,
            repair_attempts_remaining=repair_remaining,
            input_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        )
        if persist:
            self.store.write_record(
                f"budget/evaluations/{task.id}/{evaluation.id}.json", evaluation.to_dict()
            )
            self.audit.append(
                "budget.evaluated" if passed else "budget.exhausted",
                actor=AuditActor.system,
                task_id=task.id,
                payload={
                    "budget_id": evaluation.id,
                    "passed": passed,
                    "execution_attempts_used": execution_used,
                    "execution_attempt_limit": config.execution_attempt_limit,
                    "repair_attempts_used": repair_used,
                    "repair_limit": config.repair_limit,
                },
            )
        return evaluation

    def enforce(self, task: ForgeTask) -> BudgetEvaluation:
        evaluation = self.evaluate(task)
        if not evaluation.passed:
            raise ForgeBudgetError(
                f"task {task.id} exhausted execution attempt budget "
                f"{evaluation.execution_attempts_used}/{evaluation.execution_attempt_limit}"
            )
        return evaluation

    def for_task(self, task_id: str) -> tuple[dict[str, Any], ...]:
        return self.store.list_records(f"budget/evaluations/{task_id}")
