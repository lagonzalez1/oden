import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Repository.documents_repository import AbstractRepository
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, Generic, Sequence, TypeVar, List, Dict, Optional
from MessageBroker.rabbitmq_client import rabbitmq_client
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


    # ── Write ─────────────────────────────────────────────────────────────────

    async def natural_language_query(self, question: str):
        async with self.uow:
            # 1. Prepare data
            data = {
                'question': question, 
                'status': "IN-QUEUE", 
                'created_at': datetime.now()
            }
            
            # 2. Create the record
            user_query = await self.uow.queries.create(data)
            
            # 3. CRITICAL: You must AWAIT the commit
            await self.uow.commit()
            
            # At this point, user_query.id is officially persistent in Postgres
            
        if user_query:
            # 4. Use the instance directly to get the generated ID
            message_payload = {
                "id": str(user_query.id),
                "question": str(user_query.question),
                "status": str(user_query.status)
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

    async def process_document_csv(self, file: Optional[UploadFile] = None, df :Optional[pd.DataFrame] = None) -> int:
        """
        Parses a CSV file and saves rows to the PostgreSQL documents table.
        Returns the count of successfully processed rows.
        """
        saved_ids = []
        if file is not None:
            content = await file.read()
            csv_reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        
        if df is not None:
            csv_reader = df.replace({float('nan'): None}).to_dict('records')
        
        rows_added = 0
        async with self.uow:
            for row in csv_reader:
                doc_id = row.get("DocID")
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
                
                saved_ids.append({
                    'doc_id': str(doc_id) if doc_id is not None else None, 
                    'filing_year': int(year_val) if year_val and str(year_val).isdigit() else None
                })
                
                await self.uow.documents.create(db_data)

                rows_added += 1
            await self.uow.commit()
        # Process ids by pushing to queue, one-unit-of-work.
        for i in range(len(saved_ids)-1):
            item = saved_ids[i]
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
        return rows_added

    async def ingest_documents(self, year: Optional[str])->bool:
        try:
            report_df = await self.download_reports(year=year)
            inserted = await self.process_document_csv(file=None, df=report_df)
            return inserted
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


    async def process_unprocessed_documents(self)->int:
        try:
            async with self.uow:
                rows = await self.uow.documents.get_table( filters={"doc_id_parsed": False, "processed_status": 'FAILED'})
                await self.uow.commit()
                count = 0
                if rows:
                    for i in range(rows):
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

    
    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self.self.uow.documents.delete(record_id)
