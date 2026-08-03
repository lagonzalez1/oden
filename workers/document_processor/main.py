import io
import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, Optional, Any, List
from MessageBroker.rabbitmq_client import RabbitMQConfig, rabbitmq_client
from Config.settings import settings
import aio_pika
from Core.dependencies import PostgresDep, Neo4jDep
from Repository.documents_repository import DocumentRepository
from Repository.graph_repository import TransactionRepository
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork
from Service.commitee_service import CommitteeService
from Service.document_service import DocumentsService
from Service.member_service import MemberService
from Service.stock_service import StockService
from Service.graph_service import GraphService as GraphService
from Downloads.DownloadFile import DownloadFile 
from Transaction.ProcessTransaction import ProcessTransaction
from Agents.AgentProcessor import AgentProcessor
from Database.postgres import postgres_db
from Database.neo4j_ import neo4j_db
import uuid


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

agent_processor = AgentProcessor()


def _postgres_service_committee(session: Any)->CommitteeService:
    uow = SqlAlchemyUnitOfWork(session)
    return CommitteeService(uow)


def _postgres_service_stocks(session: Any)->StockService:
    uow = SqlAlchemyUnitOfWork(session)
    return StockService(uow)

def _postgres_service(session: Any)->DocumentsService:
    uow = SqlAlchemyUnitOfWork(session)
    return DocumentsService(uow)

def _neo4j_service(session: Any) -> GraphService:
    neo4j_repository = TransactionRepository(session)
    return GraphService(neo4j_repository)

def _postgres_service_member(session: Any)->MemberService:
    uow = SqlAlchemyUnitOfWork(session)
    return MemberService(uow)


async def process_document_task(body, message: aio_pika.IncomingMessage, postgres_session, neo4j_session) -> bool:
    """ Pika context manager for processing messages ack or non-ack."""
    document_service = _postgres_service(postgres_session)
    neo4j_service = _neo4j_service(neo4j_session)
    committee_service = _postgres_service_committee(postgres_session)
    stock_service = _postgres_service_stocks(postgres_session)
    member_service = _postgres_service_member(postgres_session)
    
    # Initialize transaction processor
    transaction_processor = ProcessTransaction(
        document_service=document_service,
        neo4j_service=neo4j_service,
        committee_service=committee_service,
        stock_service=stock_service,
        member_service=member_service
    )
    
    try:
        if isinstance(body, dict):
            doc = body
        else:
            doc = json.loads(body)

        doc_id = doc.get("doc_id")
        downloader = DownloadFile(body)
        pdf_content = await downloader.get_pdf()
        
        if pdf_content is None:
            await transaction_processor.mark_extraction_failed(doc_id)
            logger.warning(f"[!] File {doc_id} returned no content")
            return True
            
        if pdf_content:
            text = downloader.get_text()
            if text:
                content = await agent_processor.run(text)
                if content:
                    row = content.get("transactions", [])
                    first_name, last_name, state_district = content.get("first_name"), content.get("last_name"), content.get("state_district")
                    txs = [{**trades, "id": str(uuid.uuid4())} for trades in row]
                    content['transactions'] = txs
                
                    await transaction_processor.process_and_save(doc_id, content, len(text))
                    return True

        await transaction_processor.mark_extraction_failed(doc_id)
        return True
        
    except Exception as e:
        logger.error(f"Failed to process document: {e}")
        return False

"""
[ Company Profile ] 
       │
       ▼
 [ Large Language Model ] ──► Extract key industries, keywords, & compliance tags
       │
       ▼
 [ Hybrid Postgres Query ] ──► Search vector embeddings + Match explicit text keywords
       │
       ▼
 [ Ranked Final Results ] ──► Cross-reference against known regulatory frameworks

"""


async def main():
    await postgres_db.connect()
    await neo4j_db.connect()
    
    config = RabbitMQConfig(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        username=settings.RABBITMQ_USER,
        password=settings.RABBITMQ_PASSWORD,
        virtual_host=settings.RABBITMQ_VHOST,
        heartbeat=settings.RABBITMQ_HEARTBEAT
    )
    rabbitmq_client.config = config
    
    try:
        await rabbitmq_client.connect()
        async for postgres_session in postgres_db.get_session():
            async for neo4j_session in neo4j_db.get_session():
                try:
                
                    await rabbitmq_client.consume(
                        queue_name="worker-1",
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