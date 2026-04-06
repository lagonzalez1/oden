CREATE SCHEMA IF NOT EXISTS oden;

-- Create a table for storing document information
CREATE TABLE IF NOT EXISTS oden.documents (
    -- Primary Key: Assuming DocID is unique per document
    doc_id VARCHAR(255) PRIMARY KEY,
    
    -- Name Information
    prefix VARCHAR(50),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    suffix VARCHAR(50),
    
    -- Filing Details
    filing_type VARCHAR(100),
    state_dst VARCHAR(50),
    filing_year INTEGER,
    filing_date DATE,
    
    -- Metadata Fields (Your additional requirements)
    processed_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    doc_id_parsed BOOLEAN DEFAULT FALSE,
    last_updated_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    doc_size INTEGER,

    -- Optional: Add an index on Year or State for faster queries
    CONSTRAINT check_doc_size CHECK (doc_size >= 0)
);