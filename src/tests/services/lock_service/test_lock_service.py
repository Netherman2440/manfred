import pytest

from app.services.lock_service import LockService


@pytest.mark.asyncio
async def test_same_key_returns_same_lock() -> None:
    service = LockService()

    lock_a = await service.get("user-1", "manfred")
    lock_b = await service.get("user-1", "manfred")

    assert lock_a is lock_b


@pytest.mark.asyncio
async def test_different_users_get_distinct_locks() -> None:
    service = LockService()

    lock_a = await service.get("user-1", "manfred")
    lock_b = await service.get("user-2", "manfred")

    assert lock_a is not lock_b


@pytest.mark.asyncio
async def test_different_agents_get_distinct_locks() -> None:
    service = LockService()

    lock_a = await service.get("user-1", "manfred")
    lock_b = await service.get("user-1", "researcher")

    assert lock_a is not lock_b
