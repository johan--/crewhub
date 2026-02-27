"""Tests for project_files routes."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.routes.project_files import (
    _analyze_project_folder,
    _build_dir_item,
    _build_file_item,
    _get_file_type,
    _is_browsable_entry,
    _is_safe_path,
    _read_text_with_fallback,
    _resolve_project_folder,
    _scan_project_dir,
)

# ── Helper unit tests ────────────────────────────────────────────


class TestGetFileType:
    def test_document(self):
        assert _get_file_type(Path("readme.md")) == "document"
        assert _get_file_type(Path("notes.txt")) == "document"

    def test_image(self):
        assert _get_file_type(Path("logo.png")) == "image"
        assert _get_file_type(Path("photo.jpg")) == "image"

    def test_config(self):
        assert _get_file_type(Path("data.json")) == "config"
        assert _get_file_type(Path("cfg.yaml")) == "config"

    def test_code(self):
        assert _get_file_type(Path("main.py")) == "code"
        assert _get_file_type(Path("app.ts")) == "code"


class TestIsSafePath:
    def test_safe(self, tmp_path):
        child = tmp_path / "sub"
        child.mkdir()
        assert _is_safe_path(tmp_path, child) is True

    def test_unsafe(self, tmp_path):
        assert _is_safe_path(tmp_path, tmp_path / ".." / "etc") is False


class TestIsBrowsableEntry:
    def test_hidden_dir_skipped(self, tmp_path):
        d = tmp_path / ".hidden"
        d.mkdir()
        assert _is_browsable_entry(d) is False

    def test_gitignore_allowed(self, tmp_path):
        f = tmp_path / ".gitignore"
        f.touch()
        assert _is_browsable_entry(f) is True

    def test_skip_dir(self, tmp_path):
        d = tmp_path / "node_modules"
        d.mkdir()
        assert _is_browsable_entry(d) is False

    def test_normal_dir(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        assert _is_browsable_entry(d) is True


class TestResolveProjectFolder:
    def test_valid(self, tmp_path):
        result = _resolve_project_folder(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_not_found(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _resolve_project_folder("/nonexistent/path/xyz")

    def test_not_a_dir(self, tmp_path):
        from fastapi import HTTPException

        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(HTTPException):
            _resolve_project_folder(str(f))


class TestBuildItems:
    def test_build_file_item(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello")
        item = _build_file_item(f, Path("test.py"))
        assert item["name"] == "test.py"
        assert item["type"] == "code"
        assert item["size"] == 5

    def test_build_dir_item(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        item = _build_dir_item(d, Path("src"), [{"name": "a.py"}])
        assert item["type"] == "directory"
        assert item["child_count"] == 1


class TestScanProjectDir:
    def test_scan(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x")
        (tmp_path / "readme.md").write_text("hi")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / ".git").mkdir()

        items = _scan_project_dir(tmp_path, tmp_path, 1, 2)
        names = [i["name"] for i in items]
        assert "src" in names
        assert "readme.md" in names
        assert "node_modules" not in names
        assert ".git" not in names


class TestReadTextWithFallback:
    def test_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("héllo", encoding="utf-8")
        assert _read_text_with_fallback(f) == "héllo"

    def test_latin1_fallback(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"\xff\xfe latin1 content")
        result = _read_text_with_fallback(f)
        assert "latin1 content" in result


class TestAnalyzeProjectFolder:
    def test_analyze(self, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        (tmp_path / "docs").mkdir()
        (tmp_path / "main.py").write_text("x")
        info = _analyze_project_folder(tmp_path)
        assert info["has_readme"] is True
        assert info["has_docs"] is True
        assert info["file_count"] >= 2


# ── Route integration tests ──────────────────────────────────────


@pytest.mark.anyio
async def test_list_files_project_not_found(client):
    resp = await client.get("/api/projects/nonexistent/files")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_files_success(client):
    """Create a project with a real tmp folder and list files."""
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "hello.py").write_text("print('hi')")
        (Path(tmpdir) / "sub").mkdir()
        (Path(tmpdir) / "sub" / "notes.md").write_text("notes")

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj1", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj1/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "proj1"
        names = [f["name"] for f in data["files"]]
        assert "hello.py" in names
        assert "sub" in names


@pytest.mark.anyio
async def test_list_files_path_traversal(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj2", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj2/files", params={"path": "../../etc"})
        assert resp.status_code in (403, 404)


@pytest.mark.anyio
async def test_read_file_content(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "test.py").write_text("print('hello')")

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj3", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj3/files/content", params={"path": "test.py"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "print('hello')"
        assert data["type"] == "code"


@pytest.mark.anyio
async def test_read_file_not_allowed_extension(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "data.exe").write_bytes(b"binary")

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj4", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj4/files/content", params={"path": "data.exe"})
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_read_file_too_large(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        big = Path(tmpdir) / "big.txt"
        big.write_bytes(b"x" * (1_048_576 + 1))

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj5", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj5/files/content", params={"path": "big.txt"})
        assert resp.status_code == 413


@pytest.mark.anyio
async def test_get_image(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        img = Path(tmpdir) / "logo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj6", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj6/files/image", params={"path": "logo.png"})
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_image_not_image(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "code.py"
        f.write_text("x = 1")

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj7", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj7/files/image", params={"path": "code.py"})
        assert resp.status_code == 400


@pytest.mark.anyio
async def test_discover_project_folders(client):
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "myproject").mkdir()
        (Path(tmpdir) / "myproject" / "README.md").write_text("hi")

        with patch("app.routes.project_files._get_projects_base_path", return_value=tmpdir):
            resp = await client.get("/api/project-folders/discover")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["folders"]) >= 1
            assert data["folders"][0]["name"] == "myproject"


@pytest.mark.anyio
async def test_read_file_content_image_returns_file_response(client):
    """Reading an image via /content should return FileResponse."""
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        img = Path(tmpdir) / "pic.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj8", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj8/files/content", params={"path": "pic.png"})
        assert resp.status_code == 200
        assert "image" in resp.headers.get("content-type", "")


@pytest.mark.anyio
async def test_read_file_not_a_file(client):
    from app.db.database import get_db

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "subdir").mkdir()

        async with get_db() as db:
            await db.execute(
                "INSERT INTO projects (id, name, folder_path, created_at, updated_at) VALUES (?, ?, ?, 0, 0)",
                ("proj9", "Test", tmpdir),
            )
            await db.commit()

        resp = await client.get("/api/projects/proj9/files/content", params={"path": "subdir"})
        assert resp.status_code == 400
