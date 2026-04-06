import asyncio
import logging
import json
from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client
from Config.settings import settings
import aio_pika
from aio_pika import Message, ExchangeType, connect_robust
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel, AbstractRobustQueue


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Assuming the class you provided is in a file named rabbit_client.py
# from rabbit_client import rabbitmq_client, RabbitMQConfig

async def process_document_task(body, message: aio_pika.IncomingMessage):
    """
    The logic that executes for every message received from 'worker-1'.
    """
    try:
        # If your client already parsed it as JSON, 'body' is a dict
        doc = json.loads(body)

        
        logger.info(f" [x] Processing Document ID: {doc}")
        
        # --- YOUR LOGIC HERE ---
        # e.g., result = await my_processing_function(doc_id)
        # -----------------------
        
        await asyncio.sleep(1)  # Simulating work
        
        logger.info(f" [v] Successfully finished {doc}")
        
        # Return True to indicate successful processing
        return True 
        
    except Exception as e:
        logger.error(f"Failed to process document: {e}")
        # Return False to nack and requeue the message
        return False

async def main():
    # 1. Configure the client
    # Update these values to match your docker-compose environment
    config = RabbitMQConfig(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        username=settings.RABBITMQ_USER,
        password=settings.RABBITMQ_PASSWORD,
        virtual_host=settings.RABBITMQ_VHOST
    )
    rabbitmq_client.config = config
    
    try:
        # 2. Establish connection
        await rabbitmq_client.connect()
        
        # 3. Start consuming from 'worker-1'
        # prefetch_count=1 ensures the worker only takes one task at a time
        await rabbitmq_client.consume(
            queue_name="worker-1",
            callback=process_document_task,
            prefetch_count=1
        )
        
        logger.info(" [*] Waiting for messages. To exit press CTRL+C")
        
        # 4. Keep the loop running forever
        await asyncio.Future() 
        
    except asyncio.CancelledError:
        logger.info("Worker stopped by user.")
    finally:
        await rabbitmq_client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass