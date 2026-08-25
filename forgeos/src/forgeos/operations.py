"""Operational hardening facade for recovery, integrity, migration and budgets."""

from typing import Any

from .budget import BudgetService
from .integrity import IntegrityService
from .migration import ProtocolMigrator
from .recovery import CancellationService, RecoveryService
from .service import ForgeService


class ForgeOperations:
    """Expose N4 services without expanding the core Control API implementation."""

    def __init__(self, forge: ForgeService) -> None:
        self.forge = forge
        self.budget = BudgetService(forge.store, clock=forge.clock)
        self.cancellations = CancellationService(forge.store, clock=forge.clock)
        self.integrity = IntegrityService(forge.store, clock=forge.clock)
        self.migrations = ProtocolMigrator(forge.store, clock=forge.clock)
        self.recovery = RecoveryService(forge)

    def status(self) -> dict[str, Any]:
        recovery_runs = self.forge.store.list_records("recovery/runs")
        return {
            "migration": self.migrations.plan().to_dict(),
            "integrity": self.integrity.latest(),
            "recovery": recovery_runs[-1] if recovery_runs else None,
        }

    def task_evidence(self, task_id: str) -> dict[str, Any]:
        return {
            "budgets": list(self.budget.for_task(task_id)),
            "cancellation": (
                request.to_dict()
                if (request := self.cancellations.for_task(task_id)) is not None
                else None
            ),
            "recovery_runs": [
                record
                for record in self.forge.store.list_records("recovery/runs")
                if task_id in record.get("blocked_task_ids", [])
                or task_id in record.get("cancelled_task_ids", [])
            ],
            "integrity": self.integrity.latest(),
        }

    def request_cancellation(
        self, task_id: str, *, requested_by: str, reason: str
    ) -> dict[str, Any]:
        task = self.forge.task(task_id)
        return self.cancellations.request(task, requested_by=requested_by, reason=reason).to_dict()

    def apply_cancellation(self, task_id: str) -> dict[str, Any]:
        task = self.forge.task(task_id)
        updated = self.cancellations.apply(self.forge, task)
        if updated is None:
            return task.to_dict()
        return updated.to_dict()

    def integrity_scan(self) -> dict[str, Any]:
        return self.integrity.scan(persist=True).to_dict()

    def migration_status(self) -> dict[str, Any]:
        return self.migrations.plan().to_dict()

    def migration_apply(self) -> dict[str, Any]:
        return self.migrations.apply().to_dict()

    def recover(self) -> dict[str, Any]:
        return self.recovery.recover().to_dict()
