import os

import aio_pika
from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()

message_history = []

RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL",
    "amqp://guest:guest@rabbitmq/",
)
QUEUE_NAME = "messages"


class Message(BaseModel):
    text: str


@app.get("/")
async def root():
    return {
        "status": "MES Prototype is running!",
        "history": message_history[-10:],
    }


@app.post("/send")
async def send_message(message: Message):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(QUEUE_NAME, durable=True)

        await channel.default_exchange.publish(
            aio_pika.Message(
                body=message.text.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=QUEUE_NAME,
            mandatory=True,
        )

    message_history.append(message.text)
    return {"status": "sent", "text": message.text}


@app.get("/receive")
async def receive_message():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        incoming_message = await queue.get(no_ack=False, fail=False)

        if incoming_message is None:
            return {"message": None}

        async with incoming_message.process():
            text = incoming_message.body.decode()

        return {"message": text}
