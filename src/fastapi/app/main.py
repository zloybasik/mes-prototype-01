from fastapi import FastAPI
from pydantic import BaseModel
import aio_pika


app = FastAPI()


message_history = []


class Message(BaseModel):
    text: str


RABBITMQ_URL = "amqp://guest:guest@rabbitmq/"


@app.get("/")
async def root():
    return {
        "status": "MES Prototype is running!",
        "history": message_history[-10:]
    }


@app.post("/send")
async def send_message(message: Message):
    message_history.append(message.text)

    # Отправка сообщения в RabbitMQ
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(body=message.text.encode()),
            routing_key="messages"
        )

    return {"status": "sent", "text": message.text}


@app.get("/receive")
async def receive_message():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue("messages", durable=True)
        incoming_message = await queue.get(no_ack=True, fail=False)

        if incoming_message is None:
            return {"message": None}

        return {"message": incoming_message.body.decode()}
