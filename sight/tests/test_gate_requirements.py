"""Phase gate evidence checks for the implemented cloud core only."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_archived_inventory_is_internally_consistent():
    with (ROOT / "reports/input_manifest.csv").open() as f:
        manifest = list(csv.DictReader(f))
    with (ROOT / "reports/file_dispositions_phase1_historical.csv").open() as f:
        dispositions = list(csv.DictReader(f))
    assert len(manifest) == len(dispositions) == 21358
    assert len({(row["archive"], row["relative_path"]) for row in manifest}) == len(manifest)
    assert len({row["archive"] for row in manifest}) == 8
    archives = json.loads((ROOT / "reports/source_archives.json").read_text())
    with (ROOT / "reports/archive_entries.csv").open() as f:
        entries = list(csv.DictReader(f))
    for archive in archives:
        assert sum(entry["archive"] == archive["archive"] for entry in entries) == archive["files"] + archive["directory_entries"]
    for row in dispositions:
        assert row["disposition"] and len(row["sha256"]) == 64
        assert row["chosen_implementation"] == "none"  # Audit is separate from source-code reuse.


def test_archived_hermes_revision_and_skill_catalog():
    provenance = json.loads((ROOT / "reports/hermes_provenance.json").read_text())
    assert len(provenance["commit"]) == 40
    assert not provenance["original_uploaded_zip_identity_verified"]
    with (ROOT / "reports/skill_inventory.csv").open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert sum(row["catalog"] == "built-in" for row in rows) == 58
    assert sum(row["catalog"] == "optional" for row in rows) == 153
    assert all(row["execution"] == "never executed" for row in rows)
    assert len(rows) == 212  # Includes one additional Google Meet plugin manifest.
    assert [row["path"] for row in rows if row["catalog"] == "plugin/other"] == ["plugins/google_meet/SKILL.md"]


def test_supplied_reference_zip_has_current_source_evidence():
    summary = json.loads((ROOT / 'reports/reference_reconciliation_current.json').read_text(encoding='utf-8'))
    with (ROOT / 'reports/reference_inventory_current.csv').open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == summary['total_files'] == 21207
    assert len(summary['archives']) == 8
    assert len({(r['archive'],r['path']) for r in rows}) == len(rows)
    assert all(len(r['sha256']) == 64 and r['execution'] == 'not executed' for r in rows)
    assert summary['prior_hash_matches'] == 20781
    for archive in summary['archives']:
        assert len(archive['sha256']) == 64
        assert sum(r['archive'] == archive['archive'] for r in rows) == archive['files']


def test_phase4_current_file_and_capability_dispositions():
    from sight_core.capabilities import SPECS, BLOCKED
    summary = json.loads((ROOT / 'reports/phase4_reconciliation.json').read_text())
    with (ROOT / 'reports/file_dispositions.csv').open(encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == summary['all_archive_entries'] == 22638
    assert sum(row['entry_type'] == 'file' for row in rows) == summary['file_entries'] == 21207
    assert len({(row['archive'], row['archive_entry']) for row in rows}) == len(rows)
    assert all(row['extracted_matches'] == 'True' and len(row['sha256']) == 64 for row in rows)
    assert all(row['chosen_implementation'] == 'none' for row in rows)
    with (ROOT / 'reports/capability_matrix.csv').open(encoding='utf-8') as handle:
        matrix = list(csv.DictReader(handle))
    ids = {row['capability_id'] for row in matrix}
    assert len(ids) == len(matrix) == summary['canonical_capability_rows']
    assert sum(row['kind'] == 'manual-reference' for row in matrix) == 77
    assert {'local.' + spec.id for spec in SPECS} <= ids
    assert {'local.' + row[0] for row in BLOCKED} <= ids
    assert not summary['complete_semantic_feature_coverage']
