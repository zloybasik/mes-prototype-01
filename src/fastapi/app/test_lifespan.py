from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def broker(monkeypatch):
    queue = SimpleNamespace(
        name="test-unit",
        get=AsyncMock(return_value=None),
    )
    channel = SimpleNamespace(
        declare_queue=AsyncMock(return_value=queue),
        default_exchange=SimpleNamespace(publish=AsyncMock()),
    )
    connection = SimpleNamespace(
        channel=AsyncMock(return_value=channel),
        close=AsyncMock(),
    )
    connect = AsyncMock(return_value=connection)

    monkeypatch.setattr(main.aio_pika, "connect_robust", connect)
    monkeypatch.setattr(main, "message_history", [])

    return SimpleNamespace(
        connection=connection,
        channel=channel,
        connect=connect,
    )


def test_connection_is_reused_and_closed(broker):
    with TestClient(main.app) as client:
        for text in ("first", "second"):
            response = client.post("/send", json={"text": text})
            assert response.status_code == 200

        response = client.get("/receive")
        assert response.status_code == 200
        assert response.json() == {"message": None}
        assert client.get("/").json()["history"] == [
            "first",
            "second",
        ]

        broker.connect.assert_awaited_once()
        assert broker.channel.default_exchange.publish.await_count == 2
        broker.connection.close.assert_not_awaited()

    broker.connection.close.assert_awaited_once()


@pytest.mark.parametrize("stage", ["channel", "queue"])
def test_connection_is_closed_when_startup_fails(broker, stage):
    if stage == "channel":
        broker.connection.channel.side_effect = RuntimeError("setup failed")
    else:
        broker.channel.declare_queue.side_effect = RuntimeError(
            "setup failed",
        )

    with pytest.raises(RuntimeError, match="setup failed"):
        with TestClient(main.app):
            pass

    broker.connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_initial_connection_is_retried(broker, monkeypatch):
    broker.connect.side_effect = [
        OSError("broker unavailable"),
        broker.connection,
    ]
    sleep = AsyncMock()
    monkeypatch.setattr(main.asyncio, "sleep", sleep)

    connection = await main.connect_rabbitmq()

    assert connection is broker.connection
    assert broker.connect.await_count == 2
    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_initial_connection_stops_after_three_attempts(
    broker,
    monkeypatch,
):
    broker.connect.side_effect = OSError("broker unavailable")
    sleep = AsyncMock()
    monkeypatch.setattr(main.asyncio, "sleep", sleep)

    with pytest.raises(OSError, match="broker unavailable"):
        await main.connect_rabbitmq()

    assert broker.connect.await_count == 3
    assert sleep.await_count == 2
