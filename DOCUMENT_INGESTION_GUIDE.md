# Document Ingestion Service - Implementation Guide

## Overview

The `ingest_documents` method downloads financial disclosure documents from the House Clerk website, saves them to PostgreSQL, and queues them for processing.

## Method Signature

```python
async def ingest_documents(self, year: Optional[str], count: Optional[int]) -> int:
    """
    Download and ingest financial disclosure documents for a specific year.
    
    Args:
        year: Filing year (e.g., 2024)
        count: Maximum number of documents to process and queue (None = all)
        
    Returns:
        Number of documents successfully ingested and queued
    """
```

## Flow

```
1. Download ZIP file from House Clerk
   └─> https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip
   
2. Extract XML file
   └─> extract_folder/{year}FD.xml
   
3. Parse XML to DataFrame
   └─> pandas.read_xml()
   
4. Insert documents into PostgreSQL
   └─> Check for duplicates
   └─> Insert unique documents
   └─> Limit by count parameter
   
5. Push to RabbitMQ queue
   └─> Queue: 'worker-1'
   └─> Message: {doc_id, filing_year, action}
   
6. Return count of processed documents
```

## Usage Examples

### API Endpoint

```bash
# Ingest up to 100 documents from 2024
curl -X POST "http://localhost:8000/documents/ingest_documents" \
  -H "Content-Type: application/json" \
  -d '{"year": 2024, "count": 100}'

# Response:
{
  "messages_in_queue": 100
}
```

### Ingest All Documents

```bash
# Ingest ALL documents from 2024 (no limit)
curl -X POST "http://localhost:8000/documents/ingest_documents" \
  -H "Content-Type: application/json" \
  -d '{"year": 2024}'

# Response:
{
  "messages_in_queue": 5000  # All documents
}
```

### Python Code

```python
from Service.document_service import DocumentsService
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork

# Initialize service
uow = SqlAlchemyUnitOfWork()
service = DocumentsService(uow)

# Ingest up to 100 documents
count = await service.ingest_documents(year=2024, count=100)
print(f"✓ Processed {count} documents")

# Ingest all documents
count = await service.ingest_documents(year=2024, count=None)
print(f"✓ Processed {count} documents")
```

## How Count Works

### Count Parameter Behavior

| Count Value | Behavior |
|------------|----------|
| `count=100` | Process exactly 100 documents maximum |
| `count=500` | Process exactly 500 documents maximum |
| `count=None` | Process ALL documents (no limit) |
| `count=0` | Process 0 documents (returns 0) |

### Count Flow

```python
# Example: count=100

1. Download all documents for year (e.g., 5000 total)
2. Iterate through documents:
   - Document 1: Insert ✅ (rows_added = 1)
   - Document 2: Insert ✅ (rows_added = 2)
   - ...
   - Document 100: Insert ✅ (rows_added = 100)
   - Document 101: STOP (rows_added >= count)
3. Queue all 100 inserted documents
4. Return 100
```

### Important Notes

1. **Duplicates are skipped**: If a document already exists, it's skipped and doesn't count toward the limit
2. **Queue is separate**: ALL inserted documents are queued, not limited separately
3. **Order matters**: Documents are processed in order from XML file

## Database Schema

```sql
CREATE TABLE oden.documents (
    doc_id VARCHAR(255) PRIMARY KEY,
    prefix VARCHAR(50),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    suffix VARCHAR(50),
    filing_type VARCHAR(100),
    state_dst VARCHAR(50),
    filing_year INTEGER,
    filing_date DATE,
    processed_date TIMESTAMPTZ,
    processed_status VARCHAR(10),
    doc_id_parsed BOOLEAN DEFAULT FALSE,
    last_updated_date TIMESTAMPTZ,
    doc_size INTEGER
);
```

## Queue Message Format

Documents are queued to RabbitMQ with this structure:

```json
{
  "doc_id": "20012345678",
  "filing_year": 2024,
  "action": "process_metadata",
  "timestamp": "2024-01-15T10:30:00.000000"
}
```

**Queue Details**:
- Queue Name: `worker-1`
- Routing Key: `worker-1`
- Content Type: `application/json`
- Expiration: 500000ms (~8 minutes)

## Process Document CSV Method

The `process_document_csv` method handles the actual insertion and queuing:

```python
async def process_document_csv(
    self, 
    file: Optional[UploadFile] = None, 
    df: Optional[pd.DataFrame] = None, 
    count: Optional[int] = None
) -> int:
    """
    Parses CSV or DataFrame and saves to PostgreSQL + queues to RabbitMQ.
    
    Args:
        file: Optional CSV file upload
        df: Optional pandas DataFrame
        count: Maximum documents to process
        
    Returns:
        Number of successfully processed rows
    """
```

### Processing Steps

1. **Parse Input**
   - If file: Read CSV and parse
   - If df: Convert DataFrame to records

2. **Insert into Database**
   - Check for each document:
     - Does it already exist? Skip
     - Is count limit reached? Stop
     - Otherwise: Insert
   
3. **Queue to RabbitMQ**
   - For each inserted document:
     - Create message
     - Publish to queue

4. **Return Count**
   - Number of documents inserted

## Error Handling

### Common Errors

**1. Download Failed**
```
ERROR: [Document download_reports] Download reports: ConnectionError
```
- Check internet connection
- Verify URL is accessible
- Check disk space for ZIP extraction

**2. Database Insert Failed**
```
ERROR: [Document Service] Update failed for doc_id: ...
```
- Check database connection
- Verify schema matches
- Check for constraint violations

**3. Queue Publish Failed**
```
ERROR: Failed to publish to RabbitMQ
```
- Check RabbitMQ is running
- Verify queue exists
- Check connection settings

### Graceful Degradation

- Individual document failures don't stop the batch
- Errors are logged and processing continues
- Partial success is returned

## Monitoring & Logging

### Log Messages

```python
# Start
INFO: Starting document ingestion for year 2024, max count: 100

# Download
INFO: Downloaded 5000 documents for year 2024

# Insert
INFO: Inserted 100 documents into database (skipped 15 duplicates)

# Queue
INFO: Queued 100 documents for processing

# Complete
INFO: Successfully ingested and queued 100 documents for year 2024
```

### Metrics to Track

- Total documents downloaded
- Documents inserted
- Duplicates skipped
- Documents queued
- Processing time
- Error count

## Performance Considerations

### Batch Size Recommendations

| Count | Use Case | Time Estimate |
|-------|----------|---------------|
| 10 | Testing | ~5 seconds |
| 100 | Small batch | ~30 seconds |
| 1000 | Medium batch | ~5 minutes |
| None | Full year | ~30-60 minutes |

### Optimization Tips

1. **Use count for testing**: Start with small batches to verify
2. **Monitor queue**: Ensure workers can keep up
3. **Database cleanup**: Remove old duplicates periodically
4. **Parallel processing**: Workers process in parallel

## Testing

### Test with Count

```bash
# Test with 10 documents
curl -X POST "http://localhost:8000/documents/ingest_documents" \
  -H "Content-Type: application/json" \
  -d '{"year": 2024, "count": 10}'
```

### Verify in Database

```sql
-- Check inserted documents
SELECT COUNT(*) 
FROM oden.documents 
WHERE filing_year = 2024;

-- Check unprocessed
SELECT COUNT(*) 
FROM oden.documents 
WHERE filing_year = 2024 
  AND doc_id_parsed = FALSE;
```

### Verify in Queue

```bash
# Check RabbitMQ queue
rabbitmqctl list_queues name messages

# Should show:
# worker-1  10
```

## Complete Workflow Example

```bash
# 1. Ingest 100 documents
curl -X POST "http://localhost:8000/documents/ingest_documents" \
  -H "Content-Type: application/json" \
  -d '{"year": 2024, "count": 100}'

# Response: {"messages_in_queue": 100}

# 2. Check database
psql -d your_db -c "SELECT COUNT(*) FROM oden.documents WHERE filing_year = 2024;"
# Result: 100

# 3. Monitor queue processing
# Workers will process the 100 queued messages

# 4. Check processed documents
psql -d your_db -c "SELECT COUNT(*) FROM oden.documents WHERE filing_year = 2024 AND doc_id_parsed = TRUE;"
# Result: Increases as workers process
```

## Summary

✅ **Count parameter controls**: Maximum documents to insert and queue
✅ **Duplicates are skipped**: Doesn't count toward limit
✅ **All inserted documents are queued**: Workers process asynchronously
✅ **Returns actual count**: Number of documents processed
✅ **Error resilient**: Individual failures don't stop batch
✅ **Fully logged**: Track progress and issues

The implementation provides fine-grained control over document ingestion with proper error handling and queue integration!
