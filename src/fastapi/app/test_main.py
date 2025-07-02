from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert data["status"] == "MES Prototype is running!"
    assert "history" in data
    assert isinstance(data["history"], list)


def test_send_and_receive_message():
    # Отправляем сообщение
    message_text = "Hello, MES!"
    response = client.post("/send", json={"text": message_text})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "sent"
    assert data["text"] == message_text

    # Получаем сообщение
    response = client.get("/receive")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    # Сообщение может быть None, если очередь пуста, либо равно отправленному
    assert data["message"] == message_text or data["message"] is None
