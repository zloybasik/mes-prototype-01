import pytest
import aio_pika

RABBITMQ_URL = "amqp://guest:guest@localhost/"

@pytest.mark.asyncio
async def test_rabbitmq_publish_and_consume():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue("test_queue", auto_delete=True)
        message_body = b"hello, rabbitmq!"

        # Публикуем сообщение
        await channel.default_exchange.publish(
            aio_pika.Message(body=message_body),
            routing_key=queue.name,
        )

        # Получаем сообщение
        incoming_message = await queue.get(timeout=5)
        assert incoming_message.body == message_body
        await incoming_message.ack()
