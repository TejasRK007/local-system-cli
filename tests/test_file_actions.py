from pathlib import Path

from app.tools.file_actions import (
    delete_file,
    is_allowed_path,
    move_file,
    rename_file,
)

# ------------------------------------------------------------------
# is_allowed_path
# ------------------------------------------------------------------


def test_is_allowed_path():
    downloads_file = Path.home() / "Downloads" / "test_sample.pdf"
    assert is_allowed_path(downloads_file) is True

    documents_file = Path.home() / "Documents" / "doc.docx"
    assert is_allowed_path(documents_file) is True

    forbidden_file = Path("/tmp/system_file.txt")
    assert is_allowed_path(forbidden_file) is False


def test_is_allowed_path_nested():
    """Nested files inside an allowed directory must be allowed."""
    nested = Path.home() / "Downloads" / "folder" / "subfolder" / "file.pdf"
    assert is_allowed_path(nested) is True


def test_is_allowed_path_home_root_rejected():
    """A file directly in ~ (not in an allowed subdir) must be rejected."""
    home_file = Path.home() / "sensitive.txt"
    assert is_allowed_path(home_file) is False


# ------------------------------------------------------------------
# delete_file
# ------------------------------------------------------------------

def test_delete_file_non_existent():
    result = delete_file("~/Downloads/non_existent_file_xyz123.pdf")
    assert "File does not exist" in result


def test_delete_file_outside_allowed(tmp_path):
    forbidden_file = tmp_path / "outside.txt"
    forbidden_file.write_text("content")

    result = delete_file(str(forbidden_file))
    assert "Deletion blocked" in result
    assert forbidden_file.exists()


def test_delete_file_path_traversal_blocked():
    """Path traversal attempts via ../ must be blocked by is_allowed_path."""
    # This path resolves outside all allowed directories.
    result = delete_file("~/Downloads/../../../tmp/evil.txt")
    # Either the file doesn't exist or the path is blocked.
    assert "does not exist" in result or "blocked" in result.lower()


def test_delete_file_success(monkeypatch, tmp_path):
    test_file = tmp_path / "allowed.txt"
    test_file.write_text("delete me")

    # Monkeypatch ALLOWED_DIRECTORIES to include tmp_path for safe testing
    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = delete_file(str(test_file))
    assert "Verified" in result
    assert not test_file.exists()


# ------------------------------------------------------------------
# rename_file
# ------------------------------------------------------------------

def test_rename_file_outside_allowed_blocked(tmp_path):
    """rename_file must refuse when the source is outside allowed dirs."""
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("content")

    result = rename_file(str(outside_file), "new_name.txt")

    assert "blocked" in result.lower()
    assert outside_file.exists()


def test_rename_file_empty_new_name(monkeypatch, tmp_path):
    """rename_file must reject an empty new filename."""
    src = tmp_path / "source.txt"
    src.write_text("data")

    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = rename_file(str(src), "")
    assert "empty" in result.lower()
    assert src.exists()


def test_rename_file_slash_in_name_blocked(monkeypatch, tmp_path):
    """rename_file must reject new names containing path separators."""
    src = tmp_path / "source.txt"
    src.write_text("data")

    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = rename_file(str(src), "subdir/evil.txt")
    assert "blocked" in result.lower()
    assert src.exists()


def test_rename_file_target_exists_blocked(monkeypatch, tmp_path):
    """rename_file must not overwrite an existing file."""
    src = tmp_path / "source.txt"
    src.write_text("data")
    existing = tmp_path / "existing.txt"
    existing.write_text("already here")

    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = rename_file(str(src), "existing.txt")
    assert "blocked" in result.lower()
    assert src.exists()
    assert existing.exists()


# ------------------------------------------------------------------
# move_file
# ------------------------------------------------------------------

def test_move_file_outside_source_blocked(tmp_path):
    """move_file must refuse when the source is outside allowed dirs."""
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("content")

    dest = Path.home() / "Documents"
    result = move_file(str(outside_file), str(dest))

    assert "blocked" in result.lower()
    assert outside_file.exists()


def test_move_file_target_exists_blocked(monkeypatch, tmp_path):
    """move_file must not overwrite an existing file at the destination."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    src_file = src_dir / "file.txt"
    src_file.write_text("source")
    existing = dst_dir / "file.txt"
    existing.write_text("already here")

    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = move_file(str(src_file), str(dst_dir))
    assert "blocked" in result.lower()
    assert src_file.exists()
    assert existing.read_text() == "already here"


def test_move_file_nonexistent_source(tmp_path):
    """move_file must report a missing source file rather than crashing."""
    result = move_file(
        str(tmp_path / "ghost.txt"),
        str(Path.home() / "Documents"),
    )
    assert "does not exist" in result
