"""Static, non-executing inventory of supplied archives. Never prints matched secrets."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath

LICENSES = {
    "Ada-SI-main.zip": "MIT",
    "Brahma-AI-main.zip": "MIT",
    "ada_v2-main.zip": "MIT",
    "hermes-agent-main.zip": "MIT",
    "Brahma-Echo-main.zip": "Custom source-available; restricted",
    "Brahma-AI---Lite-main.zip": "Custom source-available; restricted",
    "Brahma-Ai-Evo-main.zip": "Personal local noncommercial; restricted",
    "ada_local-main.zip": "Unresolved; no root license",
}
FIELDS = "archive relative_path sha256 bytes file_type source_license secret_flag pii_flag risk_level functional_family capability_id duplicate_group chosen_implementation disposition phase tests notes".split()
SECRET = re.compile(rb"(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{25,}|AIza[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
SENSITIVE = re.compile(r"(?:^|/)(?:\.env(?!\.example|\.sample)|credentials|secrets|history|training_data)|\.(?:db|sqlite3?|log|wav|mp3|ogg|pem|key)$", re.I)
RULES = {"dynamic_execution": r"\b(?:eval|exec)\(", "shell_execution": r"shell\s*=\s*True|os\.system\(", "tls_bypass": r"verify\s*=\s*False", "deserialization": r"pickle\.loads?\(", "package_install": r"pip\s+install|npm\s+install"}


def canonical(name: str) -> str:
    return re.sub(r"\(\d+\)", "", name)


def safe_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > 100_000 or sum(e.file_size for e in entries) > 2 * 1024**3:
        raise ValueError("Archive exceeds audit resource limit")
    seen = set()
    for entry in entries:
        # ZipInfo normalizes backslashes on Windows; inspect the original name too.
        original = entry.orig_filename
        p = PurePosixPath(original)
        mode = entry.external_attr >> 16
        if (not original or p.is_absolute() or ".." in p.parts or "\\" in original
                or any(re.search(r'[\x00-\x1f<>:"|?*]', c) or c.endswith((" ", "."))
                       or PureWindowsPath(c).is_reserved() for c in p.parts)
                or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
            raise ValueError("Unsafe archive entry rejected")
        key = str(p).casefold()
        if key in seen:
            raise ValueError("Ambiguous duplicate archive entry")
        seen.add(key)
        if entry.file_size > 256 * 1024**2:
            raise ValueError("Archive member exceeds audit limit")
    return entries


def csv_write(path, rows, fields=None):
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def audit(attachments: Path, spec: Path, inputs: Path, reports: Path):
    reports.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    previous = {}
    with (spec / "SIGHT_All_Files_Manifest.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            previous[(canonical(row["archive"]), row["relative_path"])] = row["sha256"]
    rows, findings, archives, functions, inventory, skills, notices = [], [], [], [], [], [], []
    known_hashes = {}
    for source in sorted(attachments.glob("*/*.zip")):
        name = canonical(source.name)
        archive_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        with zipfile.ZipFile(source) as z:
            entries = safe_entries(z)
            top = {PurePosixPath(i.filename).parts[0] for i in entries}
            if len(top) != 1:
                raise ValueError("Expected a single source root")
            tree = inputs / name.removesuffix(".zip")
            files = [i for i in entries if not i.is_dir()]
            archives.append({"archive": name, "sha256": archive_hash, "files": len(files), "directory_entries": len(entries)-len(files), "bytes": sum(i.file_size for i in files)})
            for entry in entries:
                relative = str(PurePosixPath(*PurePosixPath(entry.filename).parts[1:]))
                if relative == ".":
                    if not entry.is_dir():
                        raise ValueError("Expected all files below the source root directory")
                    inventory.append({"archive": name, "path": ".", "type": "directory", "disposition": "reference-only"})
                    continue
                if entry.is_dir():
                    inventory.append({"archive": name, "path": relative, "type": "directory", "disposition": "reference-only"})
                    continue
                content = z.read(entry)  # ZipFile validates CRC; SHA-256 records source identity.
                digest = hashlib.sha256(content).hexdigest()
                path = tree / relative
                if not path.resolve().is_relative_to(inputs.resolve()):
                    raise ValueError("Extraction escaped quarantine")
                if path.exists():
                    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError("Existing input differs; refusing overwrite")
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    path.chmod(0o400)
                suffix = path.suffix.lower()
                text = content.decode("utf-8", errors="replace") if suffix in {".py", ".js", ".ts", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".html", ".ps1", ".sh"} else ""
                secret = bool(SECRET.search(content))
                private = bool(SENSITIVE.search(relative))
                restricted = LICENSES.get(name, "Unresolved") != "MIT"
                duplicate = known_hashes.get(digest, "")
                disposition = "excluded-sensitive" if private or secret else "restricted" if restricted else "duplicate" if duplicate else "reference-only"
                note = "No source imported or executed. Automated classification; semantic review required before reuse."
                old = previous.get((name, relative))
                note += " Prior hash matches." if old == digest else " Prior hash MISMATCH." if old else " Not in prior manifest."
                row = dict(zip(FIELDS, [name, relative, digest, len(content), suffix or "extensionless", LICENSES.get(name, "Unresolved"), secret, private, "high" if private or secret else "review", relative.split("/")[0], "", duplicate, "none", disposition, "audit", "not-executed", note]))
                rows.append(row)
                if Path(relative).name.lower() in {"license", "license.md", "license.txt", "copying", "notice"}:
                    notices.append({"archive": name, "path": relative, "sha256": digest, "root_only": "/" not in relative, "review": "Preserve; root license does not override bundled terms"})
                if Path(relative).name == "SKILL.md":
                    skills.append({"archive": name, "path": relative, "sha256": digest, "catalog": "optional" if "optional-skills" in relative or "optional_skills" in relative else "built-in" if relative.startswith("skills/") else "other", "status": "disabled; source manifest only", "requirements": "Per-skill dependency, rights, platform, account and security review required", "network_indicators": bool(re.search(r"https?://|api[_ -]?key|oauth|internet", text, re.I)), "unsafe_indicators": bool(re.search(r"sudo |rm -rf|shell|subprocess|credentials|password", text, re.I)), "execution": "never executed"})
                inventory.append({"archive": name, "path": relative, "type": "file", "disposition": disposition})
                known_hashes.setdefault(digest, name + ":" + relative)
                for rule, pattern in RULES.items():
                    for match in re.finditer(pattern, text):
                        findings.append({"archive": name, "path": relative, "line": text[:match.start()].count("\n")+1, "rule": rule, "verdict": "review; heuristic is not malware proof"})
                if secret:
                    findings.append({"archive": name, "path": relative, "line": "redacted", "rule": "possible_credential", "verdict": "quarantined; no value displayed"})
                if suffix == ".py" and not private and not secret:
                    try:
                        module = ast.parse(text)
                        for node in ast.walk(module):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                functions.append({"archive": name, "path": relative, "symbol": node.name, "line": node.lineno, "ast_sha256": hashlib.sha256(ast.dump(node).encode()).hexdigest(), "status": "REFERENCE_ONLY", "review": "candidate, not an independently verified capability"})
                    except (SyntaxError, ValueError):
                        findings.append({"archive": name, "path": relative, "line": 0, "rule": "unparsed_python", "verdict": "manual review required"})
            for folder in sorted(tree.rglob("*"), reverse=True):
                if folder.is_dir():
                    folder.chmod(0o500)
            tree.chmod(0o500)
    for filename in ("input_manifest.csv", "file_dispositions.csv"):
        csv_write(reports / filename, rows, FIELDS)
    csv_write(reports / "archive_entries.csv", inventory)
    csv_write(reports / "static_findings.csv", findings)
    csv_write(reports / "source_symbols.csv", functions)
    (reports / "source_archives.json").write_text(json.dumps(archives, indent=2) + "\n")
    supplied = {(r["archive"], r["relative_path"]): r for r in rows}
    capabilities = []
    with (spec / "SIGHT_V2_Expanded_Feature_Evidence.csv").open(encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            found = supplied.get((canonical(row["source_zip"]), row["source_path"]))
            capabilities.append({"capability_id": f"spec.{i:03d}", "archive": canonical(row["source_zip"]), "source_path": row["source_path"], "capability": row["proposed_capability"], "phase": row["phase"], "status": "REFERENCE_ONLY" if found else "BLOCKED_SOURCE", "required_tests": row["required_verification"], "active_implementation": "none", "reason": "Not integrated yet; source is not execution evidence" if found else "Path absent from accessible source; compare pinned Git revision with original ZIP", "rights": LICENSES.get(canonical(row["source_zip"]), "Unresolved")})
    csv_write(reports / "capability_matrix.csv", capabilities)
    csv_write(reports / "skill_inventory.csv", skills, list(skills[0]) if skills else ["archive", "path", "sha256", "status", "requirements"])
    csv_write(reports / "license_notices.csv", notices)
    missing = sorted(set(a for a, _ in previous) - {a["archive"] for a in archives})
    differences = [{"archive": a, "path": p, "difference": "missing_from_current_source" if (a,p) not in supplied else "changed_content"} for (a,p), h in previous.items() if (a,p) not in supplied or supplied[(a,p)]["sha256"] != h]
    differences += [{"archive": a, "path": p, "difference": "added_to_current_source"} for a,p in supplied if (a,p) not in previous]
    csv_write(reports / "prior_manifest_differences.csv", differences, ["archive", "path", "difference"])
    reconciliation = {"prior_file_count": len(previous), "supplied_file_count": len(rows), "matched_prior_hashes": sum(previous.get((r["archive"], r["relative_path"])) == r["sha256"] for r in rows), "unavailable_archives": missing, "prior_unavailable_files": sum(a in missing for a, _ in previous), "candidate_python_symbols": len(functions), "spec_references": len(capabilities), "skill_manifests": dict(Counter(s["catalog"] for s in skills)), "static_findings": len(findings), "credential_flags": sum(r["secret_flag"] for r in rows), "private_file_flags": sum(r["pii_flag"] for r in rows), "dispositions": dict(Counter(r["disposition"] for r in rows)), "complete_current_source_entry_inventory": not missing, "original_hermes_zip_identity_verified": False, "semantic_capability_review_complete": False}
    (reports / "input_reconciliation.json").write_text(json.dumps(reconciliation, indent=2) + "\n")
    print(json.dumps(reconciliation, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--attachments", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    audit(args.attachments, args.spec, args.inputs, args.reports)
