import csv
import io
import json
from datetime import datetime
from fastapi import UploadFile
from Repository.documents_repository import AbstractRepository
from Core.unit_of_work import AbstractUnitOfWork
from typing import Any, Generic, Sequence, TypeVar, List, Dict
from MessageBroker.rabbitmq_client import rabbitmq_client
import logging


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

    async def process_document_csv(self, file: UploadFile) -> int:
        """
        Parses a CSV file and saves rows to the PostgreSQL documents table.
        Returns the count of successfully processed rows.
        """
        saved_ids = []
        # Read the file content
        content = await file.read()
        # Use io.StringIO to treat bytes as a file-like object for the CSV reader
        csv_reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        rows_added = 0
        async with self.uow:
            for row in csv_reader:
                # 1. Map CSV columns to DB columns (Handling potential naming mismatches)
                db_data = {
                    "doc_id": row.get("DocID"),
                    "prefix": row.get("Prefix"),
                    "first_name": row.get("First"),
                    "last_name": row.get("Last"),
                    "suffix": row.get("Suffix"),
                    "filing_type": row.get("FillingType"),
                    "state_dst": row.get("StateDst"),
                    "filing_year": int(row.get("Year")) if row.get("Year") else None,
                    "filing_date": row.get("FillingDate"),
                    
                    # 2. Add the metadata fields
                    "processed_date": datetime.now(),
                    "doc_id_parsed": False,
                    "last_updated_date": datetime.now(),
                    "doc_size": 0 # Or calculate per row if needed
                }
                # Save id to array
                saved_ids.append({'doc_id': row.get("DocID"), 'filing_year': int(row.get("Year")) if row.get("Year") else None})            
                # 3. Save to database using the repository's create method
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

    async def process_unprocessed_documents(self)->int:
        try:
            async with self.uow:
                rows = await self.uow.documents.get_table(300, 0, filters={"doc_id_parsed": False})
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
