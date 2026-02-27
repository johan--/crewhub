"""Tests for task_service.py."""

import pytest

from app.db.task_models import TaskCreate, TaskUpdate
from app.services.task_service import (
    add_history_event,
    create_task,
    delete_task,
    get_agent_row,
    get_display_name,
    get_task,
    get_task_row,
    list_tasks,
    row_to_task,
    set_task_running,
    update_task,
)

# ── Helpers ───────────────────────────────────────────────────────


async def _make_project(db, project_id="p1", name="Test"):
    await db.execute(
        "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, 0, 0)",
        (project_id, name),
    )
    await db.commit()


async def _make_room(db, room_id="r1", project_id="p1"):
    await db.execute(
        "INSERT INTO rooms (id, project_id, name, created_at, updated_at) VALUES (?, ?, 'Room', 0, 0)",
        (room_id, project_id),
    )
    await db.commit()


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_get_display_name_none():
    from app.db.database import get_db

    async with get_db() as db:
        assert await get_display_name(db, None) is None


@pytest.mark.anyio
async def test_get_display_name_fallback():
    from app.db.database import get_db

    async with get_db() as db:
        name = await get_display_name(db, "agent:dev:main")
        assert name == "Dev"


@pytest.mark.anyio
async def test_get_display_name_from_db():
    from app.db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO session_display_names (session_key, display_name, updated_at) VALUES (?, ?, 0)",
            ("test:key", "TestUser"),
        )
        await db.commit()
        name = await get_display_name(db, "test:key")
        assert name == "TestUser"


@pytest.mark.anyio
async def test_row_to_task():
    row = {
        "id": "t1",
        "project_id": "p1",
        "room_id": None,
        "title": "Test",
        "description": None,
        "status": "todo",
        "priority": "medium",
        "assigned_session_key": None,
        "created_by": None,
        "created_at": 1000,
        "updated_at": 1000,
    }
    task = row_to_task(row, "Bob")
    assert task.id == "t1"
    assert task.assigned_display_name == "Bob"


@pytest.mark.anyio
async def test_create_task_success():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    task = await create_task(TaskCreate(project_id="p1", title="Do stuff"))
    assert task.title == "Do stuff"
    assert task.status == "todo"
    assert task.id


@pytest.mark.anyio
async def test_create_task_project_not_found():
    with pytest.raises(ValueError, match="project_not_found"):
        await create_task(TaskCreate(project_id="nope", title="X"))


@pytest.mark.anyio
async def test_create_task_room_not_found():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    with pytest.raises(ValueError, match="room_not_found"):
        await create_task(TaskCreate(project_id="p1", room_id="bad_room", title="X"))


@pytest.mark.anyio
async def test_create_task_with_room():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)
        await _make_room(db)

    task = await create_task(TaskCreate(project_id="p1", room_id="r1", title="Room task"))
    assert task.room_id == "r1"


@pytest.mark.anyio
async def test_get_task():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Find me"))
    found = await get_task(created.id)
    assert found is not None
    assert found.title == "Find me"


@pytest.mark.anyio
async def test_get_task_not_found():
    result = await get_task("nonexistent")
    assert result is None


@pytest.mark.anyio
async def test_list_tasks_basic():
    # Demo mode may seed tasks, so just verify the function works
    result = await list_tasks()
    assert result.total >= 0
    assert isinstance(result.tasks, list)


@pytest.mark.anyio
async def test_list_tasks_with_filters():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    await create_task(TaskCreate(project_id="p1", title="A", status="todo"))
    await create_task(TaskCreate(project_id="p1", title="B", status="done"))

    result = await list_tasks(project_id="p1", status="todo")
    assert result.total == 1
    assert result.tasks[0].title == "A"


@pytest.mark.anyio
async def test_list_tasks_assigned_filter():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    await create_task(TaskCreate(project_id="p1", title="Mine", assigned_session_key="me"))
    await create_task(TaskCreate(project_id="p1", title="Yours", assigned_session_key="you"))

    result = await list_tasks(assigned_session_key="me")
    assert result.total == 1


@pytest.mark.anyio
async def test_update_task_success():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Old"))
    updated, changes = await update_task(created.id, TaskUpdate(title="New"))
    assert updated.title == "New"
    assert "title" in changes


@pytest.mark.anyio
async def test_update_task_not_found():
    result, changes = await update_task("nope", TaskUpdate(title="X"))
    assert result is None
    assert changes is None


@pytest.mark.anyio
async def test_update_task_no_changes():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Same"))
    updated, changes = await update_task(created.id, TaskUpdate())
    assert updated.title == "Same"
    assert changes == {}


@pytest.mark.anyio
async def test_update_task_status_change():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="T"))
    updated, changes = await update_task(created.id, TaskUpdate(status="done"))
    assert updated.status == "done"
    assert "status" in changes


@pytest.mark.anyio
async def test_update_task_assign():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="T"))
    updated, changes = await update_task(created.id, TaskUpdate(assigned_session_key="agent:x"))
    assert "assigned_session_key" in changes


@pytest.mark.anyio
async def test_delete_task_success():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Delete me"))
    result = await delete_task(created.id)
    assert result["task_id"] == created.id

    assert await get_task(created.id) is None


@pytest.mark.anyio
async def test_delete_task_not_found():
    result = await delete_task("nonexistent")
    assert result is None


@pytest.mark.anyio
async def test_set_task_running():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Run me"))
    await set_task_running(created.id, "p1", "agent1", "Agent", "sess:key", "do the thing")

    task = await get_task(created.id)
    assert task.status == "in_progress"


@pytest.mark.anyio
async def test_get_task_row():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)

    created = await create_task(TaskCreate(project_id="p1", title="Raw"))
    row = await get_task_row(created.id)
    assert row is not None
    assert row["title"] == "Raw"


@pytest.mark.anyio
async def test_get_task_row_not_found():
    row = await get_task_row("nope")
    assert row is None


@pytest.mark.anyio
async def test_get_agent_row_not_found():
    row = await get_agent_row("nope")
    assert row is None


@pytest.mark.anyio
async def test_add_history_event():
    from app.db.database import get_db

    async with get_db() as db:
        await _make_project(db)
        eid = await add_history_event(db, "p1", "test_event", payload={"key": "val"})
        assert eid
        await db.commit()
