"""One-shot administrative CLI for ForgeOS project and task records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .audit import AuditActor
from .audit_query import AuditQueryService
from .bundle import ForgeBundleService
from .codex_sdk import CodexSdkSettings, WorkspaceAccess
from .control import ForgeControlService
from .doctor import ForgeDoctor
from .errors import ForgeError
from .execution import ForgeExecutionService
from .governance import (
    AcceptanceCriterionEvidence,
    CriterionStatus,
    ReviewChecklistItem,
    ReviewDimension,
    ReviewStatus,
)
from .memory import MemoryKind, MemoryService, MemoryStatus
from .models import ForgeTask, TaskPriority, TaskRisk, TaskType
from .operations import ForgeOperations
from .policy import PolicyEngine, PolicyTarget
from .policy_admin import PolicyAdminService
from .protocol_fixtures import ProtocolFixtureVerifier
from .release import ReleaseReadinessService
from .service import ForgeService
from .task_report import TaskReportService
from .validation import ValidationRunner
from .web_server import ForgeWebServer
from .workflow import ForgeWorkflowService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge", description="ForgeOS administrative CLI")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize .forge in a workspace")
    init.add_argument("--name", required=True)
    init.add_argument("--repair-limit", type=int, default=3)
    init.add_argument("--attempt-limit", type=int, default=8)

    commands.add_parser("status", help="show project status")
    commands.add_parser("doctor", help="check ForgeOS workspace and runtime prerequisites")

    validate = commands.add_parser("validate", help="run typed validation for a waiting task")
    validate.add_argument("task_id")

    review = commands.add_parser("review", help="record structured human Review evidence")
    review.add_argument("task_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--approved", action="store_true")
    review.add_argument("--summary", default="")
    review.add_argument(
        "--check",
        action="append",
        required=True,
        help="DIMENSION=STATUS:NOTE; provide each required dimension once",
    )
    review.add_argument("--risk-note", action="append", default=[])
    review.add_argument("--technical-debt", action="append", default=[])

    accept = commands.add_parser("accept", help="record criterion-level Acceptance evidence")
    accept.add_argument("task_id")
    accept.add_argument("--accepted-by", required=True)
    accept.add_argument("--note", default="")
    accept.add_argument(
        "--criterion",
        action="append",
        required=True,
        help="STATUS:EVIDENCE in the same order as the task criteria",
    )

    ui = commands.add_parser("ui", help="run the local ForgeOS Web control interface")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--codex-bin", type=Path)
    ui.add_argument("--read-only", action="store_true")

    task = commands.add_parser("task", help="manage ForgeTask records")
    task_commands = task.add_subparsers(dest="task_command", required=True)

    new = task_commands.add_parser("new", help="create a ForgeTask")
    new.add_argument("--title", required=True)
    new.add_argument("--type", choices=[item.value for item in TaskType], required=True)
    new.add_argument("--objective", required=True)
    new.add_argument("--acceptance", action="append", required=True)
    new.add_argument("--priority", choices=[item.value for item in TaskPriority], default="NORMAL")
    new.add_argument("--risk", choices=[item.value for item in TaskRisk], default="MEDIUM")
    new.add_argument("--constraint", action="append", default=[])
    new.add_argument("--module", action="append", default=[])

    show = task_commands.add_parser("show", help="show one ForgeTask")
    show.add_argument("task_id")
    report = task_commands.add_parser("report", help="show the latest Forge Task Report")
    report.add_argument("task_id")
    task_commands.add_parser("list", help="list ForgeTask records")

    memory = commands.add_parser("memory", help="manage accepted engineering memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_new = memory_commands.add_parser("new", help="create a draft memory")
    memory_new.add_argument("--kind", choices=[item.value for item in MemoryKind], required=True)
    memory_new.add_argument("--title", required=True)
    memory_new.add_argument("--body", required=True)
    memory_new.add_argument("--created-by", required=True)
    memory_new.add_argument("--tag", action="append", default=[])
    memory_new.add_argument("--module", action="append", default=[])
    memory_new.add_argument("--task-id")
    memory_list = memory_commands.add_parser("list", help="list memory records")
    memory_list.add_argument("--status", choices=[item.value for item in MemoryStatus])
    memory_show = memory_commands.add_parser("show", help="show one memory record")
    memory_show.add_argument("memory_id")
    for decision in ("accept", "reject"):
        decision_parser = memory_commands.add_parser(decision, help=f"{decision} a draft memory")
        decision_parser.add_argument("memory_id")
        decision_parser.add_argument("--decided-by", required=True)
        decision_parser.add_argument("--reason", required=True)
        decision_parser.add_argument("--revision", type=int, required=True)

    policy = commands.add_parser("policy", help="evaluate minimal ForgePolicy gates")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_check = policy_commands.add_parser("check", help="check a task without running Codex")
    policy_check.add_argument("task_id")
    policy_commands.add_parser("list", help="list built-in, active, and retired rules")
    policy_new = policy_commands.add_parser("new", help="create an additive project DENY rule")
    policy_new.add_argument("--id", required=True)
    policy_new.add_argument("--name", required=True)
    policy_new.add_argument(
        "--target", choices=[item.value for item in PolicyTarget], required=True
    )
    policy_new.add_argument("--pattern", action="append", required=True)
    policy_new.add_argument("--reason", required=True)
    policy_new.add_argument("--created-by", required=True)
    policy_retire = policy_commands.add_parser("retire", help="retire a project policy")
    policy_retire.add_argument("policy_id")
    policy_retire.add_argument("--retired-by", required=True)
    policy_retire.add_argument("--reason", required=True)

    audit = commands.add_parser("audit", help="query append-only audit evidence")
    audit.add_argument("--task-id")
    audit.add_argument("--event-type")
    audit.add_argument("--actor", choices=[item.value for item in AuditActor])
    audit.add_argument("--after-sequence", type=int, default=0)
    audit.add_argument("--limit", type=int, default=100)

    bundle = commands.add_parser("bundle", help="export, verify, or import Forge evidence")
    bundle_commands = bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_export = bundle_commands.add_parser("export", help="create a verified bundle")
    bundle_export.add_argument("path", type=Path)
    bundle_verify = bundle_commands.add_parser("verify", help="verify without importing")
    bundle_verify.add_argument("path", type=Path)
    bundle_import = bundle_commands.add_parser("import", help="import into an empty workspace")
    bundle_import.add_argument("path", type=Path)

    release = commands.add_parser("release", help="evaluate release-readiness contracts")
    release.add_argument("action", choices=("check", "fixtures"))

    budget = commands.add_parser("budget", help="inspect a task execution budget")
    budget.add_argument("task_id")

    cancel = commands.add_parser("cancel", help="request durable task cancellation")
    cancel.add_argument("task_id")
    cancel.add_argument("--requested-by", required=True)
    cancel.add_argument("--reason", required=True)

    integrity = commands.add_parser("integrity", help="scan persisted evidence integrity")
    integrity.add_argument("action", choices=("scan",))

    migrate = commands.add_parser("migrate", help="manage additive protocol migration")
    migrate.add_argument("action", choices=("status", "apply"))

    commands.add_parser("recover", help="reconcile abandoned execution attempts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ui":
        return _serve_ui(args)
    if args.command == "doctor":
        report = ForgeDoctor(args.workspace).run()
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    try:
        service = ForgeService(args.workspace)
        payload = _execute(service, args)
    except (ForgeError, ValueError) as exc:
        print(f"forge: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _execute(service: ForgeService, args: argparse.Namespace) -> dict[str, object]:
    if args.command == "init":
        return service.init_project(
            name=args.name,
            repair_limit=args.repair_limit,
            execution_attempt_limit=args.attempt_limit,
        ).to_dict()
    if args.command == "status":
        config = service.config()
        tasks = service.tasks()
        return {
            "project": config.project.to_dict(),
            "task_count": len(tasks),
            "tasks_by_status": _status_counts(tasks),
        }
    if args.command == "validate":
        workflow = _workflow(service)
        result = workflow.validate(args.task_id)
        return {
            "task": result.task.to_dict(),
            "validation_report": result.validation_report.to_dict(),
            "regression_report": result.regression_report.to_dict(),
        }
    if args.command == "review":
        task = _workflow(service).review(
            args.task_id,
            approved=args.approved,
            reviewer=args.reviewer,
            summary=args.summary,
            checklist=tuple(_parse_review_check(item) for item in args.check),
            risks=tuple(args.risk_note),
            technical_debt=tuple(args.technical_debt),
        )
        return task.to_dict()
    if args.command == "accept":
        task = service.task(args.task_id)
        if len(args.criterion) != len(task.acceptance_criteria):
            raise ValueError("--criterion count must match the task acceptance criteria")
        criteria = tuple(
            _parse_acceptance_criterion(index, criterion, value)
            for index, (criterion, value) in enumerate(
                zip(task.acceptance_criteria, args.criterion, strict=True),
                1,
            )
        )
        accepted = _workflow(service).accept(
            task.id,
            accepted_by=args.accepted_by,
            note=args.note,
            criteria=criteria,
        )
        return accepted.to_dict()
    if args.command == "memory":
        memory = MemoryService(service.store, clock=service.clock)
        if args.memory_command == "new":
            return memory.create(
                kind=MemoryKind(args.kind),
                title=args.title,
                body=args.body,
                created_by=args.created_by,
                tags=tuple(args.tag),
                related_modules=tuple(args.module),
                source_task_id=args.task_id,
            ).to_dict()
        if args.memory_command == "list":
            status = MemoryStatus(args.status) if args.status else None
            return {"memories": [item.to_dict() for item in memory.list(status=status)]}
        if args.memory_command == "show":
            return memory.get(args.memory_id).to_dict()
        return memory.decide(
            args.memory_id,
            accepted=args.memory_command == "accept",
            decided_by=args.decided_by,
            reason=args.reason,
            expected_revision=args.revision,
        ).to_dict()
    if args.command == "policy":
        admin = PolicyAdminService(service.store, clock=service.clock)
        if args.policy_command == "list":
            return {"policies": [item.to_dict() for item in admin.list()]}
        if args.policy_command == "new":
            return admin.create(
                rule_id=args.id,
                name=args.name,
                target=PolicyTarget(args.target),
                patterns=tuple(args.pattern),
                reason=args.reason,
                created_by=args.created_by,
            ).to_dict()
        if args.policy_command == "retire":
            return admin.retire(
                args.policy_id,
                retired_by=args.retired_by,
                reason=args.reason,
            ).to_dict()
        task = service.task(args.task_id)
        return (
            PolicyEngine(service.store, clock=service.clock)
            .enforce_task(task, service.config().validation_checks)
            .to_dict()
        )
    if args.command == "audit":
        return (
            AuditQueryService(service.audit)
            .query(
                task_id=args.task_id,
                event_type=args.event_type,
                actor=AuditActor(args.actor) if args.actor else None,
                after_sequence=args.after_sequence,
                limit=args.limit,
            )
            .to_dict()
        )
    if args.command == "bundle":
        bundles = ForgeBundleService(service.store, clock=service.clock)
        if args.bundle_command == "export":
            return bundles.export(args.path).to_dict()
        if args.bundle_command == "verify":
            return bundles.verify(args.path).to_dict()
        return bundles.import_bundle(args.path).to_dict()
    if args.command == "release":
        if args.action == "fixtures":
            fixtures = ProtocolFixtureVerifier().verify()
            return {
                "passed": all(item.passed for item in fixtures),
                "fixtures": [item.to_dict() for item in fixtures],
            }
        return ReleaseReadinessService(service.store, clock=service.clock).check().to_dict()
    if args.command == "budget":
        operations = ForgeOperations(service)
        return operations.budget.evaluate(service.task(args.task_id)).to_dict()
    if args.command == "cancel":
        operations = ForgeOperations(service)
        request = operations.request_cancellation(
            args.task_id,
            requested_by=args.requested_by,
            reason=args.reason,
        )
        return {"request": request, "task": operations.apply_cancellation(args.task_id)}
    if args.command == "integrity":
        return ForgeOperations(service).integrity_scan()
    if args.command == "migrate":
        operations = ForgeOperations(service)
        return (
            operations.migration_apply()
            if args.action == "apply"
            else operations.migration_status()
        )
    if args.command == "recover":
        return ForgeOperations(service).recover()
    if args.command == "task" and args.task_command == "new":
        task = service.create_task(
            title=args.title,
            task_type=TaskType(args.type),
            objective=args.objective,
            acceptance_criteria=tuple(args.acceptance),
            priority=TaskPriority(args.priority),
            risk=TaskRisk(args.risk),
            constraints=tuple(args.constraint),
            related_modules=tuple(args.module),
        )
        return task.to_dict()
    if args.command == "task" and args.task_command == "show":
        return service.task(args.task_id).to_dict()
    if args.command == "task" and args.task_command == "report":
        reports = TaskReportService(service.store, clock=service.clock).for_task(args.task_id)
        if not reports:
            raise ValueError(f"task has no Forge Task Report: {args.task_id}")
        return reports[-1].to_dict()
    return {"tasks": [task.to_dict() for task in service.tasks()]}


def _status_counts(tasks: Sequence[ForgeTask]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = task.status.value
        counts[status] = counts.get(status, 0) + 1
    return counts


def _workflow(service: ForgeService) -> ForgeWorkflowService:
    return ForgeWorkflowService(
        service,
        ForgeExecutionService(service, _UnavailableGateway()),
        ValidationRunner(service.store.project_root, clock=service.clock),
    )


def _parse_review_check(value: str) -> ReviewChecklistItem:
    try:
        dimension_value, decision = value.split("=", 1)
        status_value, note = decision.split(":", 1)
        return ReviewChecklistItem(
            dimension=ReviewDimension(dimension_value),
            status=ReviewStatus(status_value),
            note=note,
        )
    except ValueError as exc:
        raise ValueError(f"invalid --check value: {value!r}") from exc


def _parse_acceptance_criterion(
    index: int,
    criterion: str,
    value: str,
) -> AcceptanceCriterionEvidence:
    try:
        status_value, evidence = value.split(":", 1)
        return AcceptanceCriterionEvidence(
            criterion_id=f"AC-{index:03d}",
            criterion=criterion,
            status=CriterionStatus(status_value),
            evidence=evidence,
        )
    except ValueError as exc:
        raise ValueError(f"invalid --criterion value: {value!r}") from exc


class _UnavailableGateway:
    def run_turn(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("Codex is unavailable to this one-shot administrative command")


def _serve_ui(args: argparse.Namespace) -> int:
    settings = CodexSdkSettings(
        workspace=args.workspace,
        codex_bin=args.codex_bin,
        workspace_access=(
            WorkspaceAccess.read_only if args.read_only else WorkspaceAccess.workspace_write
        ),
    )
    control = ForgeControlService(args.workspace, codex_settings=settings)
    server = ForgeWebServer(control, port=args.port)
    print(f"ForgeOS UI: {server.url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.close()
        control.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
