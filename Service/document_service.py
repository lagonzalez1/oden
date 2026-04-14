import csv
import io
import json
from datetime import datetime
from typing import Any
from fastapi import UploadFile
from Repository.documents_repository import AbstractRepository
from typing import Any, Generic, Sequence, TypeVar
from MessageBroker.rabbitmq_client import rabbitmq_client

T = TypeVar("T")


class BaseService(Generic[T]):
    """
    Generic service layer.

    Inject a repository at construction time so the service stays
    database-agnostic — swap Postgres for Neo4j without touching this class.
    """

    def __init__(self, repository: AbstractRepository[T]):
        self._repo = repository

    # ── Read ──────────────────────────────────────────────────────────────────


    # ── Write ─────────────────────────────────────────────────────────────────

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
        
        for row in csv_reader:
            # 1. Map CSV columns to DB columns (Handling potential naming mismatches)
            # Note: Your CSV headers must match these keys exactly or be mapped here.
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
            await self._repo.create(db_data)
            rows_added += 1
        # Process ids by pushing to queue, one-unit-of-work.
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
                message_type='application/json'
            )
        return rows_added

    async def update(self, record_id: Any, data: dict[str, Any]) -> T | None:
        """Update and return an existing record, or None if not found."""
        return await self._repo.update(record_id, data)

    async def delete(self, record_id: Any) -> bool:
        """Delete a record; returns True if it existed."""
        return await self._repo.delete(record_id)
