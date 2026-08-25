from pathlib import Path

from forgeos.doctor import DoctorCheck, DoctorStatus, ForgeDoctor
from forgeos.service import ForgeService


def test_doctor_fails_uninitialized_workspace_without_writing(tmp_path: Path) -> None:
    report = ForgeDoctor(tmp_path).run()

    assert report.passed is False
    config = next(check for check in report.checks if check.name == "forge_config")
    assert config.status is DoctorStatus.failed
    assert not (tmp_path / ".forge").exists()


def test_doctor_passes_initialized_forge_layout(tmp_path: Path) -> None:
    ForgeService(tmp_path).init_project(name="Doctor")

    report = ForgeDoctor(tmp_path).run()

    checks = {check.name: check for check in report.checks}
    assert checks["forge_config"].status is DoctorStatus.passed
    assert checks["forge_layout"].status is DoctorStatus.passed
    assert checks["codex_sdk"].status is DoctorStatus.passed


def test_doctor_reports_missing_workspace(tmp_path: Path) -> None:
    report = ForgeDoctor(tmp_path / "missing").run()

    assert report.passed is False
    assert report.checks == (
        DoctorCheck("workspace", DoctorStatus.failed, "workspace directory does not exist"),
    )
