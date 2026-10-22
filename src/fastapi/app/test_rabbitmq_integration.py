import aio_pika
import pytest

from app.main import RABBITMQ_URL


@pytest.mark.asyncio
async def test_rabbitmq_publish_and_consume():
    connection = await aio_pika.connect_robust(
        RABBITMQ_URL,
        timeout=10,
    )

    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(
            "",
            exclusive=True,
            auto_delete=True,
        )
        message_body = b"hello, rabbitmq!"

        await channel.default_exchange.publish(
            aio_pika.Message(body=message_body),
            routing_key=queue.name,
            mandatory=True,
            timeout=5,
        )

        incoming_message = await queue.get(timeout=5)
        async with incoming_message.process():
            assert incoming_message.body == message_body
