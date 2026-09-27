from pathlib import Path

from app.tools.file_actions import delete_file, is_allowed_path


def test_is_allowed_path():
    downloads_file = Path.home() / "Downloads" / "test_sample.pdf"
    assert is_allowed_path(downloads_file) is True

    documents_file = Path.home() / "Documents" / "doc.docx"
    assert is_allowed_path(documents_file) is True

    forbidden_file = Path("/tmp/system_file.txt")
    assert is_allowed_path(forbidden_file) is False


def test_delete_file_non_existent():
    result = delete_file("~/Downloads/non_existent_file_xyz123.pdf")
    assert "File does not exist" in result


def test_delete_file_outside_allowed(tmp_path):
    forbidden_file = tmp_path / "outside.txt"
    forbidden_file.write_text("content")

    result = delete_file(str(forbidden_file))
    assert "Deletion blocked" in result
    assert forbidden_file.exists()


def test_delete_file_success(monkeypatch, tmp_path):
    test_file = tmp_path / "allowed.txt"
    test_file.write_text("delete me")

    # Monkeypatch ALLOWED_DIRECTORIES to include tmp_path for safe testing
    import app.tools.file_actions as fa
    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    result = delete_file(str(test_file))
    assert "Verified" in result
    assert not test_file.exists()
