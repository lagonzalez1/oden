import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
from Extract_external.main import ExtractWikiContent
from Extract_external.main2 import HouseCommitteeParser
from Embeddings.main import EmbeddingService
import logging
import zipfile
import requests
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T")


class DocumentsService:
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    # ── Read ──────────────────────────────────────────────────────────────────


    async def get_document_by_id(self, doc_id: str) -> bool:
        """
            Get a document by its ID.
            Returns True if the document has been parsed, False otherwise.
            """
        try:
            async with self.uow:
                document = await self.uow.documents.get_by_id(doc_id)
                await self.uow.commit()
            if document:
                return document['doc_id_parsed']
            return False
        except Exception as e:
            logger.error(f"[Document Service] Failed to get document by id: {e}")

    # ── Write ─────────────────────────────────────────────────────────────────

    async def natural_language_query(self, question: str):
        async with self.uow:
            # 1. Prepare data
            data = {
                'question': question, 
                'status': "IN-QUEUE", 
                'created_at': datetime.now()
            }
            print(f"Data: {data}")
            # 2. Create the record
            user_query = await self.uow.queries.create(data)
            
            # 3. CRITICAL: You must AWAIT the commit
            await self.uow.commit()
            
            # At this point, user_query.id is officially persistent in Postgres
            
        if user_query:
            # 4. Use the instance directly to get the generated ID
            message_payload = {
                "id": str(user_query['id']),
                "question": str(user_query['question']),
                "status": str(user_query['status'])
            }
            
            await rabbitmq_client.publish(
                queue_name='worker-2',
                message=json.dumps(message_payload),
                routing_key='worker-2',
                message_type='application/json',
                expiration=500000
            )
            return user_query
            
        return None

    async def get_natural_language_query(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a natural_language_queries row by id."""
        try:
            async with self.uow:
                row = await self.uow.queries.get_by_id(query_id)
                await self.uow.commit()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[Document Service] Failed to get NL query {query_id}: {e}")
            raise e

    async def update_query_request(self, id, data):
        try:
            # 1. Open the transaction boundary
            async with self.uow:
                # 2. Perform the update via the repo attached to the UoW
                updated_record = await self.uow.queries.update(id, data)
                
                if updated_record:
                    # 3. Explicitly commit if the update was successful
                    await self.uow.commit()
                    return updated_record
                
                return None
        except Exception as e:
            # The UoW __aexit__ will handle the rollback, 
            # but we log the error here for the Service context.
            logger.error(f"[Document Service] Update failed for {id}: {e}")
            raise e

    async def process_document_csv(self, 
    file: Optional[UploadFile] = None, 
    df :Optional[pd.DataFrame] = None, 
    count: Optional[int] = None) -> int:
        """
        Parses a CSV file or DataFrame and saves rows to the PostgreSQL documents table,
        then pushes them to RabbitMQ queue for processing.          
        Returns:
            Number of successfully processed rows
        """
        saved_ids = []
        
        # Parse input data
        if file is not None:
            content = await file.read()
            csv_reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        
        if df is not None:
            csv_reader = df.replace({float('nan'): None}).to_dict('records')
        
        rows_added = 0
        skipped_count = 0
        
        async with self.uow:
            for row in csv_reader:
                # Check if we've reached the count limit
                if count is not None and rows_added >= count:
                    logger.info(f"Reached document limit: {count}")
                    break
                
                doc_id = row.get("DocID")
                
                # Check if document already exists
                found = await self.uow.documents.get_by_id(str(doc_id))
                await self.uow.commit()
                
                if found:
                    skipped_count += 1
                    continue
                
                year_val = row.get("Year")
                
                db_data = {
                    "doc_id": str(doc_id) if doc_id is not None else None,
                    "prefix": row.get("Prefix"),
                    "first_name": row.get("First"),
                    "last_name": row.get("Last"),
                    "suffix": row.get("Suffix"),
                    "filing_type": row.get("FillingType"),
                    "state_dst": row.get("StateDst"),
                    "filing_year": int(year_val) if year_val and str(year_val).isdigit() else None,
                    "filing_date": row.get("FillingDate"),
                    "processed_date": datetime.now(),
                    "doc_id_parsed": False,
                    "last_updated_date": datetime.now(),
                    "doc_size": 0
                }
                
                # Save document ID for queue processing
                saved_ids.append({
                    'doc_id': str(doc_id) if doc_id is not None else None, 
                    'filing_year': int(year_val) if year_val and str(year_val).isdigit() else None
                })
                
                # Insert into database
                await self.uow.documents.create(db_data)
                rows_added += 1
                
            # Commit all database inserts
            await self.uow.commit()
        
        logger.info(f"Inserted {rows_added} documents into database (skipped {skipped_count} duplicates)")
        
        # Push all saved documents to RabbitMQ queue
        queued_count = 0
        for item in saved_ids:
            message = {
                "doc_id": item['doc_id'],
                "filing_year": item['filing_year'],
                "action": "process_metadata",
                "timestamp": datetime.now().isoformat()
            }
            
            await rabbitmq_client.publish(
                queue_name='worker-1',
                message=json.dumps(message),
                routing_key='worker-1',
                message_type='application/json',
                expiration=500000
            )
            queued_count += 1
        
        logger.info(f"Queued {queued_count} documents for processing")
        
        return rows_added

    async def ingest_documents(self, year: Optional[str], count: Optional[int]) -> int:
        """
        Download and ingest financial disclosure documents for a specific year.
        
        Args:
            year: Filing year (e.g., 2024)
            count: Maximum number of documents to process and queue (None = all)
            
        Returns:
            Number of documents successfully ingested and queued
        """
        try:
            logger.info(f"Starting document ingestion for year {year}, max count: {count or 'unlimited'}")
            
            # Download the disclosure reports
            report_df = await self.download_reports(year=year)
            
            if report_df is None or report_df.empty:
                logger.warning(f"No documents found for year {year}")
                return 0
            
            logger.info(f"Downloaded {len(report_df)} documents for year {year}")
            
            # Process and insert documents into database, then queue them
            inserted_count = await self.process_document_csv(file=None, df=report_df, count=count)
            
            logger.info(f"Successfully ingested and queued {inserted_count} documents for year {year}")
            
            return inserted_count
            
        except Exception as e:
            logger.error(f"[Document ingest_documents] Download reports: {e}")
            raise e

    async def download_reports(self, year: Optional[str])->Optional[pd.DataFrame]:
        try:
            file = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
            logger.info(f"[download_reports] file url : {file}")
            async with httpx.AsyncClient() as client:
                r = await client.get(file)
                open('file.zip', 'wb').write(r.content)
                zipfile.ZipFile('file.zip').extractall("extract_folder")
                df = pd.read_xml(f"extract_folder/{year}FD.xml")
                return df
        except Exception as e:
            logger.error(f"[Document download_reports] Download reports: {e}")
            raise e


    async def process_unprocessed_documents(self, year: int)->int:
        try:
            async with self.uow:
                rows = await self.uow.documents.get_table(
                    filters={"doc_id_parsed": False, 'filing_year': year}
                )
                await self.uow.commit()
                count = 0
                if rows:
                    for i in range(len(rows)):
                        item = rows[i]
                        message = {
                            "doc_id": item['doc_id'],
                            "filing_year": item['filing_year'],
                            "action": "process_metadata",
                            "timestamp": datetime.now().isoformat()
                        }
                        await rabbitmq_client.publish(
                            queue_name='worker-1',
                            message=json.dumps(message),
                            routing_key='worker-1',
                            message_type='application/json',
                            expiration=500000
                        )
                        count += 1
                    return count
                return None
        except Exception as e:
            # The UoW __aexit__ will handle the rollback, 
            # but we log the error here for the Service context.
            logger.error(f"[Document Service] process_unprocessed_documents: {e}")
            raise e

    async def update_extractions(self, record_id: str, data: Dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        try:
            # 1. Open the transaction boundary
            async with self.uow:
                # 2. Perform the update via the repo attached to the UoW
                updated_record = await self.uow.documents.update(record_id, data)
                
                if updated_record:
                    # 3. Explicitly commit if the update was successful
                    await self.uow.commit()
                    return updated_record
                
                return None
        except Exception as e:
            # The UoW __aexit__ will handle the rollback, 
            # but we log the error here for the Service context.
            logger.error(f"[Document Service] Update failed for {record_id}: {e}")
            raise e
    
    
    async def create_transaction_gains(self, data: List[Dict[str, Any]]) -> int | None:
        """Insert transaction gain rows and return the count of successful inserts."""
        try:
            update_count = 0

            async with self.uow:
                for row in data:
                    updated_record = await self.uow.stocks.create(row)

                    if updated_record is not None:
                        await self.uow.commit()
                        update_count += 1

            return update_count if update_count > 0 else None

        except Exception as e:
            logger.error(f"[Document Service] create_transaction_gains: {e}")
            raise

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self.self.uow.documents.delete(record_id)
