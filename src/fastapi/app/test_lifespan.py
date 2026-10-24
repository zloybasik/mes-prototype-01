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


def operation_mock(broker, operation):
    if operation == "send":
        return broker.channel.default_exchange.publish
    return broker.channel.declare_queue.return_value.get


def request_operation(client, operation):
    if operation == "send":
        return client.post("/send", json={"text": "test message"})
    return client.get("/receive")


@pytest.mark.parametrize("operation", ["send", "receive"])
@pytest.mark.parametrize(
    "error_type",
    [
        OSError,
        main.AMQPConnectionError,
        main.ChannelInvalidStateError,
        main.asyncio.TimeoutError,
    ],
    ids=["network", "amqp", "channel", "timeout"],
)
def test_broker_error_returns_503(broker, operation, error_type):
    operation_mock(broker, operation).side_effect = error_type(
        "broker unavailable",
    )

    with TestClient(main.app) as client:
        response = request_operation(client, operation)

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Message service is temporarily unavailable",
        }
        assert client.get("/").json()["history"] == []


@pytest.mark.parametrize("operation", ["send", "receive"])
def test_stalled_operation_times_out(broker, monkeypatch, operation):
    cancelled = []

    async def stalled(*args, **kwargs):
        try:
            await main.asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(main, "OPERATION_TIMEOUT", 0.05)
    operation_mock(broker, operation).side_effect = stalled

    with TestClient(main.app) as client:
        response = request_operation(client, operation)

        assert response.status_code == 503
        assert cancelled == [True]
        assert client.get("/").json()["history"] == []


def test_ack_failure_returns_503(broker):
    processing = AsyncMock()
    processing.__aexit__.side_effect = OSError("ack unavailable")
    incoming_message = SimpleNamespace(
        body=b"test message",
        process=lambda: processing,
    )
    queue = broker.channel.declare_queue.return_value
    queue.get.return_value = incoming_message

    with TestClient(main.app) as client:
        response = client.get("/receive")

    assert response.status_code == 503
    processing.__aexit__.assert_awaited_once()


@pytest.fixture
def health_client(broker):
    broker.channel.ready = AsyncMock()
    probe = SimpleNamespace(
        declare_queue=AsyncMock(),
        close=AsyncMock(),
    )

    with TestClient(main.app) as client:
        broker.connection.channel.return_value = probe
        yield client, probe, broker


def test_liveness_does_not_require_broker(health_client):
    client, probe, broker = health_client
    broker.channel.ready.side_effect = OSError("broker unavailable")

    response = client.get("/health/ready")
    assert response.status_code == 503

    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    probe.declare_queue.assert_not_awaited()


def test_readiness_checks_queue_and_closes_probe(health_client):
    client, probe, broker = health_client

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    broker.channel.ready.assert_awaited_once()
    probe.declare_queue.assert_awaited_once_with(
        "test-unit",
        passive=True,
        timeout=main.READINESS_TIMEOUT,
    )
    probe.close.assert_awaited_once()
    broker.channel.declare_queue.return_value.get.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type",
    [
        OSError,
        main.AMQPConnectionError,
        main.ChannelInvalidStateError,
    ],
)
def test_readiness_failure_closes_probe(health_client, error_type):
    client, probe, broker = health_client
    probe.declare_queue.side_effect = error_type("probe failed")

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "RabbitMQ is not ready"}
    probe.close.assert_awaited_once()


def test_readiness_timeout_closes_probe(health_client, monkeypatch):
    client, probe, broker = health_client
    cancelled = []

    async def stalled(*args, **kwargs):
        try:
            await main.asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(main, "READINESS_TIMEOUT", 0.05)
    probe.declare_queue.side_effect = stalled

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert cancelled == [True]
    probe.close.assert_awaited_once()
