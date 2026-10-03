import pytest

import app.database as db
from app.tools.filesystem import search_files


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """
    Redirect the database to an empty temp DB for each test in this module.
    This ensures WorkspaceManager.count_workspaces() == 0, so the real-path
    search tests aren't blocked by workspace authorization.
    """
    temp_db = tmp_path / "test_filesystem.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db))
    monkeypatch.delenv("AGENT_ENFORCE_WORKSPACES", raising=False)
    db.init_db(temp_db)


# ------------------------------------------------------------------
# Basic search
# ------------------------------------------------------------------


def test_search_files_non_existent_directory():
    result = search_files.invoke({"directory": "/non/existent/path/xyz123", "extension": ".pdf"})
    assert result["found"] is False
    assert "Directory does not exist" in result["message"]


def test_search_files_valid(tmp_path):
    # Create sample files
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_text("dummy pdf")

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("dummy txt")

    result = search_files.invoke({"directory": str(tmp_path), "extension": ".pdf"})

    assert result["found"] is True
    assert result["count"] == 1
    assert result["files"][0]["path"] == str(pdf_file)


# ------------------------------------------------------------------
# Exclusion filter
# ------------------------------------------------------------------


def test_search_excludes_app_bundle(tmp_path):
    """Files inside a .app bundle must not appear in search results."""
    app_dir = tmp_path / "MyApp.app" / "Contents" / "Resources"
    app_dir.mkdir(parents=True)
    internal = app_dir / "internal.txt"
    internal.write_text("hidden")

    real = tmp_path / "real.txt"
    real.write_text("user file")

    result = search_files.invoke(
        {
            "directory": str(tmp_path),
            "extension": ".txt",
        }
    )

    paths = [f["path"] for f in result["files"]]
    assert str(real) in paths
    assert str(internal) not in paths


def test_search_excludes_git_directory(tmp_path):
    """Files inside .git must not appear in search results."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    git_txt = git_dir / "HEAD.txt"
    git_txt.write_text("ref: refs/heads/main")

    real = tmp_path / "readme.txt"
    real.write_text("project readme")

    result = search_files.invoke(
        {
            "directory": str(tmp_path),
            "extension": ".txt",
        }
    )

    paths = [f["path"] for f in result["files"]]
    assert str(real) in paths
    assert str(git_txt) not in paths


def test_search_excludes_pycache(tmp_path):
    """Files inside __pycache__ must not appear in search results."""
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    pyc = cache_dir / "module.pyc"
    pyc.write_bytes(b"\x00\x01\x02")

    real = tmp_path / "script.py"
    real.write_text("print('hello')")

    result = search_files.invoke(
        {
            "directory": str(tmp_path),
            "filename": "script.py",
        }
    )

    paths = [f["path"] for f in result["files"]]
    assert str(real) in paths


def test_search_real_files_alongside_excluded(tmp_path):
    """Real user files adjacent to excluded directories are still returned."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.txt").write_text("git cfg")

    app_dir = tmp_path / "SomeApp.app"
    app_dir.mkdir()
    (app_dir / "internal.txt").write_text("bundle")

    user_pdf = tmp_path / "report.pdf"
    user_pdf.write_text("my report")
    user_txt = tmp_path / "notes.txt"
    user_txt.write_text("my notes")

    result = search_files.invoke(
        {
            "directory": str(tmp_path),
            "extension": ".txt",
        }
    )

    paths = [f["path"] for f in result["files"]]
    assert str(user_txt) in paths
    assert str(git_dir / "config.txt") not in paths
    assert str(app_dir / "internal.txt") not in paths
