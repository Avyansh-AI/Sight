"""Run actual implemented tests and record evidence; never certify unrun phase gates."""
from datetime import datetime, timezone
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "reports/runs" / run_id
    output.mkdir(parents=True)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", SIGHT_TEST_ARTIFACTS=str(output / "ui_visual_diffs"))
    command = [sys.executable, "-m", "pytest", "tests", "-q", "--junitxml=" + str(output / "junit.xml")]
    started = datetime.now(timezone.utc).isoformat()
    with (output / "pytest.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, shell=False)
    print((output / "pytest.log").read_text(encoding="utf-8"))
    tests = []
    if (output / "junit.xml").exists():
        for case in ET.parse(output / "junit.xml").iter("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            skip = case.find("skipped")
            status = "FAIL" if failure is not None or error is not None else "SKIP" if skip is not None else "PASS"
            detail = failure if failure is not None else error if error is not None else skip
            tests.append({"id": case.get("name"), "class": case.get("classname"), "status": status, "seconds": case.get("time"), "timestamp_utc": started, "environment": platform.platform(), "command": command, "model": "Ollama HTTP fixtures or no installed model; no actual Gemma inference", "fixture": "pytest temporary data; original embedded HTML for UI baselines", "raw_artifact": str(output / "junit.xml"), "root_cause": detail.get("message", "") if detail is not None else None})
    gate = "WINDOWS_CORE_REGRESSION_CHECKS_PASS" if platform.system() == "Windows" and result.returncode == 0 else "PENDING_WINDOWS_TARGET_VALIDATION" if result.returncode == 0 else "CORE_CHECKS_FAILED"
    metadata = {"run_id": run_id, "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(), "command": command, "exit_code": result.returncode, "environment": platform.platform(), "python": platform.python_version(), "tests": tests, "phase": 4, "phase_gate": gate, "release": "PARTIAL", "not_validated": ["fresh Windows user account (this suite uses isolated directories on the current account)", "live inference is recorded separately in reports/live_phase4_latest.json", "live optional ChatGPT account sign-in; protocol fixtures are covered", "remote accounts/devices and microphone/camera pipelines", "complete cross-language source semantic review", "owner voice enrollment"]}
    (output / "results.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (ROOT / "reports/latest_test_run.json").write_text(json.dumps({"run_id": run_id, "results": str(output / "results.json"), "counts": {status: sum(t["status"] == status for t in tests) for status in ("PASS", "FAIL", "SKIP")}, "exit_code": result.returncode, "phase_gate": metadata["phase_gate"]}, indent=2) + "\n")
    components = [{"type": "library", "name": d.metadata.get("Name"), "version": d.version, "licenses": [{"license": {"name": d.metadata.get("License-Expression") or d.metadata.get("License") or "Review package license files"}}]} for d in distributions()]
    (ROOT / "reports/test_environment_sbom.cdx.json").write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "metadata": {"timestamp": started, "component": {"type": "application", "name": "SIGHT core", "version": "0.4.0"}}, "components": components}, indent=2) + "\n")
    print("Evidence:", output)
    print("Regression evidence recorded. Consult docs/PHASE4_READINESS.md for enabled scope, live inference and remaining gates.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
