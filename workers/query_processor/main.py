import io
import asyncio
import logging
import json
import time
import re
from datetime import datetime
import random
from typing import Dict, Optional, Any, List
from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client
from Config.settings import settings
import aio_pika
from Prompts.Builder import PromptBuilder, PromptConfig
from LLM.DocumentValidator import FilingExtraction
from LLM.LocalModel import LocalModel
from Core.dependencies import PostgresDep, Neo4jDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import TransactionRepository
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork
from functools import wraps
from Service.document_service import DocumentsService
from Service.graph_service import BaseService as GraphService
from Database.postgres import postgres_db
from Database.neo4j_ import neo4j_db
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Assuming the class you provided is in a file named rabbit_client.py
# from rabbit_client import rabbitmq_client, RabbitMQConfig
builder = PromptBuilder()


def _postgres_service(session: Any)->DocumentsService:
    uow = SqlAlchemyUnitOfWork(session)
    return DocumentsService(uow)

def _neo4j_service(session: Any) -> GraphService:
    neo4j_repository = TransactionRepository(session)
    return GraphService(neo4j_repository)

def retry(max_retries=3, base_delay=1, exponential_base=2):
    """ Retry decorator with exponential backoff """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff + jitter
                        delay = base_delay * (exponential_base ** attempt) + random.uniform(0, 1)
                        logger.info(f"Retrying in {delay:.2f} seconds...")
                        time.sleep(delay)
            
            logger.error(f"All {max_retries} attempts failed")
            raise last_exception
        return wrapper
    return decorator


async def process_text_llm(text: Optional[str])->Optional[Dict]:
    """Extract LLM content with retry on validation errors"""
    prompt_config = PromptConfig(
        template_name="cypher_system_prompt",
        system_template_name="cypher_system_prompt",
        system_variables={
            "dummy_key": None,
        },
        model="qwen3.5",
        variables={
            "natural_language_query": text,
        },
        max_tokens=80000,
        temperature=0,
    )
    
    prompt_data = builder.build(prompt_config)
    model = LocalModel(FilingExtraction, prompt_data)
    response = model._invoke_model()
    # Add validation check here if needed
    if not response or not isinstance(response, dict):
        raise ValueError(f"Invalid response from secondary model : {response}")
    return response

    
@retry(max_retries=3, base_delay=2)
async def extract_llm_content_with_fallback(text_content: str) -> Optional[dict]:
    """ Try the text model first """
    try:
        if not text_content:
            return None
        response = await process_text_llm(text_content)
        if response and isinstance(response, dict):
            return response
        return None
    except Exception as e:
        logger.warning(f"Local model failed: {e}")
    except Exception as e:
        logger.warning(f"Fallback model failed: {e}")

    raise RuntimeError("Both primary and fallback LLM extraction failed")

async def process_document_task(body, message: aio_pika.IncomingMessage, postgres_session, neo4j_session):
    """ Pika context manager for processing messages ack or non-ack."""
    document_service = _postgres_service(postgres_session)
    neo4j_service = _neo4j_service(neo4j_session)
    try:
        if isinstance(body, dict):
            doc = body
        else:
            doc = json.loads(body)

        question, _id = doc.get("question"), doc.get("id")
        if question:
            content = await extract_llm_content_with_fallback(text_content=question)
            if content:
                data = {'response': content.cypher, 'params': content.params, 'updated_at': datetime.now()}
                await document_service.update_query_request(id, data)
                return True
            else:
                return False

        return False
    except Exception as e:
        logger.error(f"Failed to process document: {e}")
        return False


async def main():
    await postgres_db.connect()
    await neo4j_db.connect()
    
    config = RabbitMQConfig(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        username=settings.RABBITMQ_USER,
        password=settings.RABBITMQ_PASSWORD,
        virtual_host=settings.RABBITMQ_VHOST
    )
    rabbitmq_client.config = config
    
    try:
        await rabbitmq_client.connect()
        async for postgres_session in postgres_db.get_session():
            async for neo4j_session in neo4j_db.get_session():
                try:
                
                    await rabbitmq_client.consume(
                        queue_name="worker-2",
                        callback=process_document_task,
                        prefetch_count=1,
                        auto_ack=False,
                        postgres_session=postgres_session,
                        neo4j_session=neo4j_session
                    )
                    
                    logger.info(" [*] Waiting for messages. To exit press CTRL+C")
                    await asyncio.Future()
                except Exception as e:
                    logger.error(f"[MAIN Error]: Error found: {e}")   
                finally:
                    # Clean up sessions when done
                    await postgres_session.close()
                    await neo4j_session.close()
                break  # Only need one session
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