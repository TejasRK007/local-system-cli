from app.tools.filesystem import search_files


def test_search_files_non_existent_directory():
    result = search_files.invoke({
        "directory": "/non/existent/path/xyz123",
        "extension": ".pdf"
    })
    assert result["found"] is False
    assert "Directory does not exist" in result["message"]


def test_search_files_valid(tmp_path):
    # Create sample files
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_text("dummy pdf")

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("dummy txt")

    result = search_files.invoke({
        "directory": str(tmp_path),
        "extension": ".pdf"
    })

    assert result["found"] is True
    assert result["count"] == 1
    assert result["files"][0]["path"] == str(pdf_file)
