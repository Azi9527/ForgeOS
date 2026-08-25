"""Serialized in-process job projection for the local ForgeOS control surface."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from .errors import ForgeConflictError, ForgeNotFoundError
from .service import Clock


class JobState(str, Enum):
    """Observable lifecycle for one local control operation."""

    queued = "QUEUED"
    running = "RUNNING"
    succeeded = "SUCCEEDED"
    failed = "FAILED"


@dataclass(slots=True)
class ControlJob:
    """Bounded in-process projection for a background control operation."""

    id: str
    kind: str
    task_id: str
    state: JobState
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    progress: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "task_id": self.task_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "progress": self.progress,
        }


JobOperation = Callable[[str], dict[str, Any]]


class ControlJobManager:
    """Serialize task mutations while exposing non-blocking UI job status."""

    def __init__(self, *, clock: Clock, maximum_history: int = 200) -> None:
        self._clock = clock
        self._maximum_history = maximum_history
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge-control")
        self._lock = threading.Lock()
        self._jobs: dict[str, ControlJob] = {}
        self._active_tasks: set[str] = set()

    def submit(self, kind: str, task_id: str, operation: JobOperation) -> ControlJob:
        with self._lock:
            if task_id in self._active_tasks:
                raise ForgeConflictError(f"task {task_id} already has an active control job")
            job = ControlJob(
                id=f"job-{uuid4()}",
                kind=kind,
                task_id=task_id,
                state=JobState.queued,
                created_at=self._clock(),
            )
            self._jobs[job.id] = job
            self._active_tasks.add(task_id)
            self._trim_history()
            self._executor.submit(self._run, job.id, operation)
            return _copy_job(job)

    def get(self, job_id: str) -> ControlJob:
        with self._lock:
            try:
                return _copy_job(self._jobs[job_id])
            except KeyError as exc:
                raise ForgeNotFoundError(f"control job not found: {job_id}") from exc

    def list(self) -> tuple[ControlJob, ...]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return tuple(_copy_job(job) for job in jobs)

    def wait(self, job_id: str, *, timeout_seconds: float = 10.0) -> ControlJob:
        deadline = threading.Event()
        remaining = timeout_seconds
        while remaining > 0:
            job = self.get(job_id)
            if job.state in {JobState.succeeded, JobState.failed}:
                return job
            interval = min(0.02, remaining)
            deadline.wait(interval)
            remaining -= interval
        raise TimeoutError(f"control job did not finish: {job_id}")

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def update_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id].progress = dict(progress)

    def _run(self, job_id: str, operation: JobOperation) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = JobState.running
            job.started_at = self._clock()
        try:
            result = operation(job_id)
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.state = JobState.failed
                job.error_type = type(exc).__name__
                job.error_message = str(exc)[:2_000]
                job.completed_at = self._clock()
        else:
            with self._lock:
                job = self._jobs[job_id]
                job.state = JobState.succeeded
                job.result = result
                job.completed_at = self._clock()
        finally:
            with self._lock:
                self._active_tasks.discard(self._jobs[job_id].task_id)

    def _trim_history(self) -> None:
        completed = [
            job for job in self._jobs.values() if job.state in {JobState.succeeded, JobState.failed}
        ]
        excess = len(self._jobs) - self._maximum_history
        for job in sorted(completed, key=lambda item: item.created_at)[: max(0, excess)]:
            del self._jobs[job.id]


def _copy_job(job: ControlJob) -> ControlJob:
    return ControlJob(**job.to_dict() | {"state": job.state})
