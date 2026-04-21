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
from LLM.LamaModel import LamaModel
from LLM.VisonModel import VisionModel
from Core.dependencies import PostgresDep, Neo4jDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import TransactionRepository
from functools import wraps
from Service.document_service import BaseService as DocumentService
from Service.graph_service import BaseService as GraphService
from Database.postgres import postgres_db
from Database.neo4j_ import neo4j_db
import io
from PIL import Image
import base64


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
        temperature=0.1,
    )
    
    prompt_data = builder.build(prompt_config)
    model = LocalModel(FilingExtraction, prompt_data)
    response = model._invoke_model()
    # Add validation check here if needed
    if not response or not isinstance(response, dict):
        raise ValueError(f"Invalid response from secondary model : {response}")
    return response


async def process_text_vision(image: bytes)->Optional[Dict]:
    """Extract LLM content with retry on validation errors"""
    image_b64 = base64.b64encode(image).decode("utf-8")
    prompt_config = PromptConfig(
        template_name="reader_identity",
        system_template_name="system",
        system_variables={
            "dummy_key": None,
        },
        model="llama3.2-vision",
        variables={
            "text": "",
        },
        images=[image_b64],
        max_tokens=80000,
        temperature=0.1,
    )
    
    prompt_data = builder.build(prompt_config)
    model = VisionModel(FilingExtraction, prompt_data)
    response = model._invoke_model()
    # Add validation check here if needed
    if not response or not isinstance(response, dict):
        raise ValueError(f"Invalid response from secondary model : {response}")
    return response

    
@retry(max_retries=3, base_delay=2)
async def extract_llm_content_with_fallback(content: bytes, text_content: str) -> dict:
    """ Try the text model first """

    try:
        if not text_content:
            return None
        response = await process_text_llm(text_content)
        if response and isinstance(response, dict):
            return response
    except Exception as e:
        logger.warning(f"Local model failed: {e}")
    except Exception as e:
        logger.warning(f"Fallback model failed: {e}")
    try:
        if not content:
            return None
        response = await process_text_vision(content)
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
                        pdf_bytes = await response.read()

                        # Render the text only to process into LLM.
                        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                            text = "".join([page.get_text() for page in doc])
                            logger.info(f"[HTTP RESPONSE] {text.count}")
                            content = await extract_llm_content_with_fallback(content=None, text_content=text)
                            if content is None:
                                await failed_extraction(doc_id)
                                return False
                            await successfull_extraction_save(doc_id, content)
                            return True
                        
                        # Render each PDF page to an image and stitch vertically
                        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
                            page_images = []
                            for page in pdf_doc:
                                # 2x scale (144 DPI) for better LLM readability
                                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                                page_images.append(
                                    Image.open(io.BytesIO(pixmap.tobytes("png")))
                                )

                            # Stitch all pages into a single tall image
                            total_height = sum(img.height for img in page_images)
                            max_width = max(img.width for img in page_images)
                            stitched = Image.new("RGB", (max_width, total_height), color=(255, 255, 255))
                            y_offset = 0
                            for img in page_images:
                                stitched.paste(img, (0, y_offset))
                                y_offset += img.height

                            # Serialize final image to PNG bytes
                            buffer = io.BytesIO()
                            stitched.save(buffer, format="PNG")
                            image_bytes = buffer.getvalue()

                            logger.info(f"[PDF->IMAGE] {len(page_images)} page(s), final size: {stitched.size}")

                            content = await extract_llm_content_with_fallback(content=image_bytes, text_content=None)
                            if content is None:
                                await failed_extraction(doc_id)
                                return False
                            await successfull_extraction_save(doc_id, content)
                            return True
                    else:
                        failed_extraction(doc_id)
                        logger.warning(f"[!] File {doc_id} returned status {response.status}")
                        return False
            
            return False 
        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            raise e
        

async def successfull_extraction_save(doc_id: str, content: dict):
    update = { 'doc_id_parsed': True, 'processed_status': "SUCCESS", 
            "last_updated_date": datetime.now(), "last_updated_date": datetime.now()}
    await document_repository.update(doc_id, update)
    await neo4j_repository.ingest_filing(content)

async def failed_extraction(doc_id: str):
    update = { 'doc_id_parsed': False, 'processed_status': "FAILED", 
            "last_updated_date": datetime.now(), "last_updated_date": datetime.now()}
    await document_repository.update(doc_id, update)

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
                        prefetch_count=1,
                        auto_ack=False,
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