import asyncio
from uuid import uuid4

import aio_pika
import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def isolated_client(monkeypatch):
    queue_name = f"test-api-{uuid4().hex}"
    monkeypatch.setattr(main, "QUEUE_NAME", queue_name)
    monkeypatch.setattr(main, "message_history", [])

    async def cleanup():
        connection = await aio_pika.connect_robust(
            main.RABBITMQ_URL,
            timeout=10,
        )
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(
                queue_name,
                durable=True,
            )
            await queue.delete(if_unused=False, if_empty=False)

    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        asyncio.run(cleanup())


def test_root():
    with TestClient(main.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "MES Prototype is running!"
    assert isinstance(data["history"], list)


def test_send_and_receive_message(isolated_client):
    message_text = f"Hello, MES! {uuid4().hex}"

    # До отправки тест не создаёт очередь и не вызывает /receive.
    response = isolated_client.post(
        "/send",
        json={"text": message_text},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "sent",
        "text": message_text,
    }

    response = isolated_client.get("/receive")
    assert response.status_code == 200
    assert response.json() == {"message": message_text}

    # Полученное и подтверждённое сообщение не выдаётся повторно.
    response = isolated_client.get("/receive")
    assert response.status_code == 200
    assert response.json() == {"message": None}
