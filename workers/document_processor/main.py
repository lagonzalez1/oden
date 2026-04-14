import io
import asyncio
import logging
import json
import time
from datetime import datetime
import random
from typing import Dict, Optional, Any
from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client
from Config.settings import settings
import aio_pika
import aiohttp
import fitz  # PyMuPDF
from Prompts.Builder import PromptBuilder, PromptConfig
from LLM.DocumentValidator import FilingExtraction
from LLM.LocalModel import LocalModel
from Core.dependencies import PostgresDep, Neo4jDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import TransactionRepository
from functools import wraps
from Service.document_service import BaseService as DocumentService
from Service.graph_service import BaseService as GraphService
from Database.postgres import postgres_db
from Database.neo4j_ import neo4j_db


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Assuming the class you provided is in a file named rabbit_client.py
# from rabbit_client import rabbitmq_client, RabbitMQConfig
builder = PromptBuilder()

document_repository: Optional[DocumentRepository] = None
neo4j_repository: Optional[TransactionRepository] = None

def _postgres_service(session: Any, schema_name: str, table: str, pk_name: str) -> DocumentService:
    global document_repository
    if document_repository is None:
        document_repository = DocumentRepository(session)
        document_repository.table_name = table
        document_repository.schema_name = schema_name
        document_repository.pk_name = pk_name
    return DocumentService(document_repository)


def _neo4j_service(session: Any) -> GraphService:
    global neo4j_repository
    if neo4j_repository is None:
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
        template_name="reader_identity",
        system_template_name="system",
        system_variables={
            "dummy_key": None,
        },
        model="qwen3.5",
        variables={
            "text": text,
        },
        max_tokens=80000,
        temperature=0.2,
    )
    
    prompt_data = builder.build(prompt_config)
    model = LocalModel(FilingExtraction, prompt_data)
    response = model._invoke_model()
    # Add validation check here if needed
    if not response or not isinstance(response, dict):
        raise ValueError(f"Invalid response from secondary model : {response}")
    return response

    
@retry(max_retries=3, base_delay=2)
async def extract_llm_content_with_fallback(extracted_text: str) -> dict:
    """
    Try Gemini first, fallback to OpenAI if Gemini fails.
    If both fail, raise error so retry decorator triggers.
    """
    try:
        response = await process_text_llm(extracted_text)
        if response and isinstance(response, dict):
            return response
    except Exception as e:
        logger.warning(f"Local model failed: {e}")
    except Exception as e:
        logger.warning(f"Fallback model failed: {e}")

    raise RuntimeError("Both primary and fallback LLM extraction failed")

async def process_document_task(body, message: aio_pika.IncomingMessage):
    """ Pika context manager for processing messages ack or non-ack."""
    async with message.process(requeue=True):
        
        try:
            if isinstance(body, dict):
                doc = body
            else:
                doc = json.loads(body)
            doc_id, filing_year = doc.get('doc_id'), doc.get('filing_year')
            url = f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{filing_year}/{doc_id}.pdf"
            
            logger.info(f" [x] Processing: {doc_id}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200 or response.status == 304:
                        content = await response.read()
                        with fitz.open(stream=content, filetype="pdf") as doc:
                            text = "".join([page.get_text() for page in doc])
                            logger.info(f"[HTTP RESPONSE] {text.count}")
                            content = await extract_llm_content_with_fallback(text)
                            if not content:
                                ##update = { 'processed_status': "FAILED-LLM-PARSE", "last_updated_date": datetime.now(), "last_updated_date": datetime.now()}
                                ##await document_repository.update(doc_id, update)
                                return True
                            ##update = { 'processed_status': "SUCCESS", "last_updated_date": datetime.now(), "last_updated_date": datetime.now()}
                            ##await document_repository.update(doc_id, update)
                            await neo4j_repository.ingest_filing(content)
                    else:
                        ##update = { 'processed_status': "FAILED-DOC-INVALID", "last_updated_date": datetime.now(), "last_updated_date": datetime.now()}
                        ##await document_repository.update(doc_id, update)
                        logger.warning(f"[!] File {doc_id} returned status {response.status}")
                        return False
            
            return True 
        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            raise e

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
                    _neo4j_service(neo4j_session)
                    _postgres_service(postgres_session, "oden", "documents", "doc_id")
                    
                    await rabbitmq_client.consume(
                        queue_name="worker-1",
                        callback=process_document_task,
                        prefetch_count=1
                    )
                    
                    logger.info(" [*] Waiting for messages. To exit press CTRL+C")
                    await asyncio.Future()
                    
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