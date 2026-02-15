import importlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db_session
from src.main import app

web_router_module = importlib.import_module("src.web.router")


async def _override_db_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


@pytest.fixture
def override_db_dependency() -> Iterator[None]:
    app.dependency_overrides[get_db_session] = _override_db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def web_client(override_db_dependency: None) -> AsyncIterator[AsyncClient]:
    _ = override_db_dependency
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.anyio
async def test_web_qa_page_returns_200(
    monkeypatch: pytest.MonkeyPatch, web_client: AsyncClient
) -> None:
    class FakeQAService:
        def __init__(self, _session: AsyncSession) -> None:
            self._session: AsyncSession = _session

        async def get_qa_summary(self) -> dict[str, object]:
            return {
                "snapshots": [
                    {
                        "source": "public_api",
                        "table_name": "real_trades",
                        "total_count": 10,
                        "last_24h_count": 2,
                        "last_updated": "2026-02-13T12:00:00+00:00",
                    }
                ],
                "issues": [],
                "blocker_count": 0,
                "warning_count": 1,
                "total_issues": 1,
                "deployment_ready": True,
            }

    monkeypatch.setattr(web_router_module, "QAService", FakeQAService)

    response = await web_client.get("/web/qa")

    assert response.status_code == 200
    assert "QA 콘솔" in response.text
    assert "최근 24시간 수집 스냅샷" in response.text


@pytest.mark.anyio
async def test_web_crawl_force_false_keeps_duplicate_block(
    monkeypatch: pytest.MonkeyPatch,
    web_client: AsyncClient,
) -> None:
    seen: set[str] = set()
    fingerprints: list[str] = []

    async def fake_enqueue(**kwargs: object) -> dict[str, object]:
        fingerprint = cast(str, kwargs["fingerprint"])
        fingerprints.append(fingerprint)
        if fingerprint in seen:
            return {"enqueued": False, "reason": "duplicate_enqueue"}
        seen.add(fingerprint)
        return {"enqueued": True, "task_id": "task-1"}

    monkeypatch.setattr(web_router_module, "enqueue_crawl_real_trade", fake_enqueue)

    first = await web_client.post(
        "/web/crawl",
        data={"region_code": "11110", "property_type": "apt", "force": "false"},
        follow_redirects=False,
    )
    second = await web_client.post(
        "/web/crawl",
        data={"region_code": "11110", "property_type": "apt", "force": "false"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 303
    assert "crawl_status=enqueued" in first.headers["location"]
    assert "crawl_status=duplicate" in second.headers["location"]
    assert fingerprints == ["manual", "manual"]


@pytest.mark.anyio
async def test_web_crawl_force_true_allows_reenqueue(
    monkeypatch: pytest.MonkeyPatch,
    web_client: AsyncClient,
) -> None:
    seen: set[str] = set()
    fingerprints: list[str] = []

    async def fake_enqueue(**kwargs: object) -> dict[str, object]:
        fingerprint = cast(str, kwargs["fingerprint"])
        fingerprints.append(fingerprint)
        if fingerprint in seen:
            return {"enqueued": False, "reason": "duplicate_enqueue"}
        seen.add(fingerprint)
        return {"enqueued": True, "task_id": "task-1"}

    class FakeDateTime:
        _index: int = 0

        @classmethod
        def now(cls, _tz: object) -> datetime:
            value = datetime(2026, 2, 13, 12, 0, 0, tzinfo=UTC) + timedelta(
                seconds=cls._index
            )
            cls._index += 1
            return value

    monkeypatch.setattr(web_router_module, "enqueue_crawl_real_trade", fake_enqueue)
    monkeypatch.setattr(web_router_module, "datetime", FakeDateTime)

    first = await web_client.post(
        "/web/crawl",
        data={"region_code": "11110", "property_type": "apt", "force": "true"},
        follow_redirects=False,
    )
    second = await web_client.post(
        "/web/crawl",
        data={"region_code": "11110", "property_type": "apt", "force": "true"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 303
    assert "crawl_status=enqueued" in first.headers["location"]
    assert "crawl_status=enqueued" in second.headers["location"]
    assert len(fingerprints) == 2
    assert fingerprints[0].startswith("force-")
    assert fingerprints[1].startswith("force-")
    assert fingerprints[0] != fingerprints[1]


@pytest.mark.anyio
async def test_web_crawl_listings_force_true_allows_reenqueue(
    monkeypatch: pytest.MonkeyPatch,
    web_client: AsyncClient,
) -> None:
    seen: set[str] = set()
    fingerprints: list[str] = []

    async def fake_enqueue_naver(**kwargs: object) -> dict[str, object]:
        fingerprint = cast(str, kwargs["fingerprint"])
        fingerprints.append(fingerprint)
        if fingerprint in seen:
            return {"enqueued": False, "reason": "duplicate_enqueue"}
        seen.add(fingerprint)
        return {"enqueued": True, "task_id": "naver-1"}

    class FakeDateTime:
        _index: int = 0

        @classmethod
        def now(cls, _tz: object) -> datetime:
            value = datetime(2026, 2, 13, 13, 0, 0, tzinfo=UTC) + timedelta(
                seconds=cls._index
            )
            cls._index += 1
            return value

    monkeypatch.setattr(
        web_router_module, "enqueue_crawl_naver_listings", fake_enqueue_naver
    )

    async def fake_enqueue_zigbang(**_kwargs: object) -> dict[str, object]:
        return {"enqueued": False, "reason": "not_called"}

    monkeypatch.setattr(
        web_router_module,
        "enqueue_crawl_zigbang_listings",
        fake_enqueue_zigbang,
    )
    monkeypatch.setattr(web_router_module, "datetime", FakeDateTime)

    first = await web_client.post(
        "/web/crawl-listings",
        data={"source": "naver", "force": "true"},
        follow_redirects=False,
    )
    second = await web_client.post(
        "/web/crawl-listings",
        data={"source": "naver", "force": "true"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 303
    assert "crawl_status=enqueued" in first.headers["location"]
    assert "crawl_status=enqueued" in second.headers["location"]
    assert len(fingerprints) == 2
    assert fingerprints[0] != fingerprints[1]
