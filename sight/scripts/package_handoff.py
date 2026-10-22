"""Package implementation + audit/evidence, excluding all quarantined code and owner data."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package(destination):
    latest = json.loads((ROOT / "reports/latest_test_run.json").read_text())
    if latest["exit_code"] != 0 or latest["counts"]["FAIL"] or latest["counts"]["SKIP"]:
        raise ValueError("A clean current regression test run is required for this handoff")
    selected_run = "reports/runs/" + latest["run_id"] + "/"
    files = []
    for folder in ("apps", "sight_core", "tests", "scripts", "docs", "reports"):
        for p in sorted((ROOT / folder).rglob("*")):
            relative = p.relative_to(ROOT).as_posix()
            if not p.is_file() or p.is_symlink() or "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            if relative.startswith("reports/runs/") and not relative.startswith(selected_run):
                continue
            if relative.startswith("reports/ui_visual_diffs/"):
                continue  # Use the current evidence run's images only.
            if relative.startswith("reports/evidence/"):
                continue  # The current reports/runs tree already carries this evidence.
            files.append((p, "sight/" + relative))
    for name in ("pyproject.toml", "requirements.in", "requirements.lock", "requirements-bootstrap.in", "requirements-bootstrap.lock"):
        files.append((ROOT / name, "sight/" + name))
    for name in ("README.md", "LICENSE", ".gitattributes", ".gitignore", "PLAN.md", "Start-SIGHT.ps1", "Open-SIGHT.ps1", "Start-Local-Runtime.ps1", "Run-Gemma.ps1", "Verify-SIGHT.ps1"):
        files.append((ROOT.parent / name, name))
    for pattern in ('live_phase4_*.json', 'growth-*.json', 'gemma-*.json', 'gemma_*.json',
                    '*before.xml', '*after*.xml', 'hardening_final.xml', 'recovery_initial.xml',
                    'browser_dependency_refresh.json',
                    'phase3_baseline.json', 'phase3_preservation.json', 'phase4_change_manifest.json'):
        for p in sorted((ROOT.parent/'evidence').glob(pattern)):
            files.append((p,'evidence/'+p.name))
    # Select only synthetic evidence summaries/telemetry, never test databases,
    # backup bundles, browser launch tokens or old unredacted transport logs.
    for folder_pattern in ('soak-*', 'offline-install-*'):
        for directory in sorted((ROOT.parent/'evidence').glob(folder_pattern)):
            if not directory.is_dir():
                continue
            for name in ('result.json', 'telemetry.jsonl'):
                path = directory/name
                if path.is_file():
                    files.append((path, 'evidence/' + directory.name + '/' + name))
    files = sorted({target: path for path, target in files}.items())
    files = [(path, target) for target, path in files]
    manifest = [{"path": target, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p,target in files]
    if any(part in {"inputs", "data", "owner-data", "test-data", ".venv", ".git", ".cache"} for _,target in files for part in Path(target).parts):
        raise ValueError("Forbidden package content")
    def windows_entry(name):
        entry = zipfile.ZipInfo(name)
        entry.create_system = 0  # MS-DOS/Windows; do not preserve host Unix modes.
        entry.create_version = 20
        entry.extract_version = 20
        entry.external_attr = 0x20  # DOS archive bit; no readonly/hidden/system bits.
        entry.compress_type = zipfile.ZIP_DEFLATED
        return entry

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as archive:
        for p, target in files:
            archive.writestr(windows_entry("SIGHT-Phase4-Verification/" + target), p.read_bytes(), compresslevel=6)
        archive.writestr(windows_entry("SIGHT-Phase4-Verification/BUNDLE_MANIFEST.json"), json.dumps({"status": "PARTIAL", "purpose": "Phase 4 audit and local hardening; model quality and remaining mandatory gates are unresolved", "evidence_run": latest["run_id"], "files": manifest}, indent=2), compresslevel=6)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC validation failed")
        if any(entry.create_system != 0 or entry.external_attr != 0x20 or entry.flag_bits & 1 for entry in archive.infolist()):
            raise ValueError("Unexpected ZIP platform, permission or encryption attributes")
        for item in manifest:
            if hashlib.sha256(archive.read("SIGHT-Phase4-Verification/" + item["path"])).hexdigest() != item["sha256"]:
                raise ValueError("Packaged content hash differs")
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.chmod(0o644)
    destination.with_suffix(".zip.sha256").write_text(checksum + "  " + destination.name + "\n")
    print(json.dumps({"bundle": str(destination), "bytes": destination.stat().st_size, "files": len(files), "sha256": checksum, "status": "PARTIAL"}, indent=2))


if __name__ == "__main__":
    package(Path(sys.argv[1]))
