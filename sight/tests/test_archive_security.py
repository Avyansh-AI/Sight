import io
import stat
import zipfile

import pytest

from scripts.audit_inputs import safe_entries


@pytest.mark.parametrize("name", ["../escape", "/absolute", "root/../../escape", "root\\windows", "root/C:ads", "root/trim. "])
def test_zip_traversal_rejected(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("placeholder")
        info.filename = name  # Bypass Windows ZipInfo normalization in this malicious fixture.
        archive.writestr(info, b"not executed")
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError):
        safe_entries(archive)


def test_zip_symlink_and_duplicate_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("root/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"/etc/passwd")
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError):
        safe_entries(archive)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("root/File", b"first")
        archive.writestr("root/file", b"second")
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError):
        safe_entries(archive)


@pytest.mark.parametrize('name', ['root/CON', 'root/nul.txt', 'root/aux.log',
                                  'root/COM1/data', 'root/lpt9.txt', 'root/com¹.txt',
                                  'root/invalid?.txt', 'root/pipe|name', 'root/control\nname'])
def test_windows_reserved_archive_paths_rejected(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(name, b'never extract a Windows device path')
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError):
        safe_entries(archive)


def test_archive_nul_name_is_rejected_before_zipinfo_truncation():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('root/nameX.txt', b'synthetic')
    raw = buffer.getvalue().replace(b'root/nameX.txt', b'root/name\0.txt')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive, pytest.raises(ValueError):
        safe_entries(archive)
