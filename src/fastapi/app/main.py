import asyncio
import logging
import os
from contextlib import asynccontextmanager

import aio_pika
from aio_pika.exceptions import (
    AMQPConnectionError,
    AMQPError,
    ChannelInvalidStateError,
)
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL",
    "amqp://guest:guest@rabbitmq/",
)
QUEUE_NAME = "messages"
OPERATION_TIMEOUT = 10

logger = logging.getLogger(__name__)
message_history = []


async def connect_rabbitmq():
    for attempt in range(3):
        try:
            return await aio_pika.connect_robust(
                RABBITMQ_URL,
                timeout=10,
                fail_fast=True,
            )
        except (AMQPConnectionError, OSError, asyncio.TimeoutError):
            if attempt == 2:
                raise
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await connect_rabbitmq()

    try:
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        queue = await channel.declare_queue(
            QUEUE_NAME,
            durable=True,
            timeout=10,
        )

        app.state.rabbitmq_connection = connection
        app.state.rabbitmq_channel = channel
        app.state.rabbitmq_queue = queue

        yield
    finally:
        await connection.close()


app = FastAPI(lifespan=lifespan)


class Message(BaseModel):
    text: str


async def run_rabbitmq_operation(operation):
    try:
        return await asyncio.wait_for(
            operation,
            timeout=OPERATION_TIMEOUT,
        )
    except (
        AMQPError,
        ChannelInvalidStateError,
        OSError,
        asyncio.TimeoutError,
    ) as exc:
        logger.warning(
            "RabbitMQ operation failed: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Message service is temporarily unavailable",
        ) from exc


async def read_message(queue):
    incoming_message = await queue.get(
        no_ack=False,
        fail=False,
        timeout=OPERATION_TIMEOUT,
    )

    if incoming_message is None:
        return None

    async with incoming_message.process():
        text = incoming_message.body.decode()

    return text


@app.get("/")
async def root():
    return {
        "status": "MES Prototype is running!",
        "history": message_history[-10:],
    }


@app.post("/send")
async def send_message(message: Message, request: Request):
    channel = request.app.state.rabbitmq_channel
    queue = request.app.state.rabbitmq_queue

    await run_rabbitmq_operation(
        channel.default_exchange.publish(
            aio_pika.Message(
                body=message.text.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue.name,
            mandatory=True,
            timeout=OPERATION_TIMEOUT,
        )
    )

    message_history.append(message.text)
    return {"status": "sent", "text": message.text}


@app.get("/receive")
async def receive_message(request: Request):
    queue = request.app.state.rabbitmq_queue
    text = await run_rabbitmq_operation(read_message(queue))
    return {"message": text}
