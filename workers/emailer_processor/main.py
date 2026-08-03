import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aio_pika

from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client
from Config.settings import settings
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork
from Service.emailer_service import EmailerService
from Database.postgres import postgres_db
from Database.neo4j_ import neo4j_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_NAME = "emailer_service"


def _emailer_service(session: Any) -> EmailerService:
    uow = SqlAlchemyUnitOfWork(session)
    return EmailerService(uow)


async def process_email_task(
    body,
    message: aio_pika.IncomingMessage,
    postgres_session,
    neo4j_session,
) -> bool:
    """Handle inbound email jobs from RabbitMQ."""
    emailer = _emailer_service(postgres_session)
    try:
        if isinstance(body, dict):
            payload = body
        else:
            payload = json.loads(body)

        email = payload.get("email")
        subject = payload.get("subject")
        body_text = payload.get("body")
        html = bool(payload.get("html", False))

        if not email or not subject or body_text is None:
            logger.error(
                "[emailer_service] Missing required fields "
                f"(email={email!r}, subject={subject!r}, body present={body_text is not None})"
            )
            return False

        await emailer.send_email(
            email=email,
            subject=subject,
            body=body_text,
            html=html,
        )
        logger.info(f"[emailer_service] Sent email to {email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"[emailer_service] Failed to process email job: {e}")
        return False


async def main():
    await postgres_db.connect()
    await neo4j_db.connect()

    config = RabbitMQConfig(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        username=settings.RABBITMQ_USER,
        password=settings.RABBITMQ_PASSWORD,
        virtual_host=settings.RABBITMQ_VHOST,
        heartbeat=settings.RABBITMQ_HEARTBEAT,
    )
    rabbitmq_client.config = config

    try:
        await rabbitmq_client.connect()
        await rabbitmq_client.declare_queue(QUEUE_NAME, durable=True)

        async for postgres_session in postgres_db.get_session():
            async for neo4j_session in neo4j_db.get_session():
                try:
                    await rabbitmq_client.consume(
                        queue_name=QUEUE_NAME,
                        callback=process_email_task,
                        prefetch_count=1,
                        auto_ack=False,
                        postgres_session=postgres_session,
                        neo4j_session=neo4j_session,
                    )

                    logger.info(" [*] Waiting for messages on emailer_service. To exit press CTRL+C")
                    await asyncio.Future()
                except Exception as e:
                    logger.error(f"[MAIN Error]: Error found: {e}")
                finally:
                    await postgres_session.close()
                    await neo4j_session.close()
                break
            break

    except asyncio.CancelledError:
        logger.info("Worker stopped by user.")
    finally:
        await rabbitmq_client.close()
        await postgres_db.disconnect()
        await neo4j_db.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
