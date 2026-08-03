# ProcessTransaction Class Usage Guide

## Overview
The `ProcessTransaction` class handles all transaction processing after successful document extraction. It orchestrates parsing transactions, extracting stock data, saving to databases, and ingesting into Neo4j.

## Architecture

### Flow
```
Document Extraction (LLM)
    ↓
ProcessTransaction.process_and_save()
    ↓
┌─────────────────────────────────────┐
│ 1. Parse transactions (YFinance)    │
│ 2. Extract stock data (DB + YF)     │
│ 3. Save new stocks to DB            │
│ 4. Update document status           │
│ 5. Ingest to Neo4j graph            │
└─────────────────────────────────────┘
```

## Usage

### Initialization

```python
from Transaction.ProcessTransaction import ProcessTransaction

# Initialize with service dependencies
transaction_processor = ProcessTransaction(
    document_service=document_service,      # PostgreSQL document operations
    neo4j_service=neo4j_service,           # Neo4j graph operations
    committee_service=committee_service,    # Committee matching
    stock_service=stock_service            # Stock master data operations
)
```

### Processing a Document

```python
# After successful LLM extraction
content = {
    "filing_id": "12345",
    "first_name": "John",
    "last_name": "Doe",
    "state_district": "CA01",
    "bioguide_id": "HCA:JOH:DOE",
    "transactions": [
        {
            "id": "uuid-1",
            "ticker": "AAPL",
            "transaction_date": "01-15-2024",
            "asset_type": "ST",
            "transaction_type": "P",
            "amount_range": "50000"
        },
        # ... more transactions
    ]
}

# Process and save everything
success = await transaction_processor.process_and_save(
    doc_id="doc-123",
    content=content,
    doc_size=5000  # Size of extracted text
)
```

### Marking Failed Extractions

```python
# If extraction fails
await transaction_processor.mark_extraction_failed(doc_id="doc-123")
```

## Methods

### Public Methods

#### `process_and_save(doc_id, content, doc_size=None) -> bool`
Main entry point that orchestrates the entire processing pipeline.

**Returns:** `True` if successful, `False` on failure

---

#### `mark_extraction_failed(doc_id) -> bool`
Marks a document extraction as failed in the database.

**Returns:** `True` if status update successful

---

### Internal Methods

#### `_parse_transactions(content) -> Optional[List[Dict]]`
Uses `ProcessFinancials` to calculate performance metrics for each transaction.

**Returns:** List of transaction data ready for DB insertion

---

#### `_extract_stock_data(content) -> Optional[List[Dict]]`
**Smart stock data extraction with caching:**

1. Extracts unique tickers from transactions
2. Checks if each ticker exists in database
3. For existing stocks: Uses DB data
4. For missing stocks: Fetches from YFinance
5. Returns combined list (DB + YFinance)

**Returns:** List of ALL stock data (both from DB and newly fetched)

**Key Feature:** Only fetches from YFinance what's missing from DB, reducing API calls

---

#### `_save_stock_data(stock_data) -> bool`
Intelligently saves only NEW stocks to database.

**Logic:**
- Checks each stock against DB
- Only inserts stocks not already present
- Skips stocks that came from DB

**Returns:** `True` if successful

---

#### `_update_document_status(doc_id, doc_size, success=True) -> bool`
Updates document processing status in PostgreSQL.

**Fields Updated:**
- `doc_id_parsed`: Boolean success flag
- `processed_status`: "SUCCESS" or "FAILED"
- `last_updated_date`: Current timestamp
- `doc_size`: Document size in characters

---

#### `_ingest_to_graph(content) -> bool`
Ingests filing data into Neo4j graph database.

Creates/updates:
- Person nodes (legislators)
- Transaction relationships
- Stock nodes
- Committee relationships

---

## Error Handling

All methods include comprehensive error handling:
- Exceptions are logged with context
- Failed operations don't crash the worker
- Document status is updated to reflect failures
- Partial failures are handled gracefully

## Integration with main.py

```python
# In process_document_task()
transaction_processor = ProcessTransaction(
    document_service=document_service,
    neo4j_service=neo4j_service,
    committee_service=committee_service,
    stock_service=stock_service
)

# After successful LLM extraction
await transaction_processor.process_and_save(doc_id, content, len(text))

# On extraction failure
await transaction_processor.mark_extraction_failed(doc_id)
```

## Database Operations

### Stock Table Flow
1. **Check existence:** Query by ticker
2. **Fetch if needed:** YFinance API call
3. **Insert new:** Only stocks not in DB
4. **Skip existing:** Avoid duplicate inserts

### Transaction Gains Flow
1. **Calculate metrics:** Price changes, alpha, drawdown
2. **Bulk insert:** All transactions at once

### Document Status Flow
1. **Update status:** Mark as SUCCESS or FAILED
2. **Record metadata:** Size, timestamps

### Neo4j Graph Flow
1. **Ingest filing:** Create nodes and relationships
2. **Link entities:** Person → Transaction → Stock

## Logging

Comprehensive logging at each step:
```
[ProcessTransaction] Starting processing for doc_id: xxx
[ProcessTransaction] Parsed 5 transactions
[ProcessTransaction] Stock AAPL found in DB
[ProcessTransaction] Stock MSFT not in DB, will fetch from YFinance
[ProcessTransaction] Fetched 1 stocks from YFinance
[ProcessTransaction] Total stocks ready: 2
[ProcessTransaction] Will insert stock MSFT
[ProcessTransaction] Stock AAPL already in DB, skipping insert
[ProcessTransaction] Inserted 1 new stocks to database
[ProcessTransaction] Updated document status to SUCCESS for doc_id: xxx
[ProcessTransaction] Successfully ingested filing to Neo4j graph
[ProcessTransaction] Successfully processed doc_id: xxx
```

## Benefits of This Architecture

1. **Separation of Concerns:** Transaction processing logic isolated from main worker
2. **Reusability:** Can be used by multiple workers or batch jobs
3. **Testability:** Easy to unit test with mock services
4. **Maintainability:** Clear method boundaries and responsibilities
5. **Efficiency:** Smart caching reduces YFinance API calls
6. **Robustness:** Comprehensive error handling and logging

## Dependencies

- `YFinance.ProcessFinancials`: Financial calculations
- `Service.document_service`: Document operations
- `Service.graph_service`: Neo4j operations
- `Service.commitee_service`: Committee matching
- `Service.stock_service`: Stock master data
