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
    processed_status varchar(10) DEFAULT NULL,
    doc_id_parsed BOOLEAN DEFAULT FALSE,
    last_updated_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    doc_size INTEGER,

    -- Optional: Add an index on Year or State for faster queries
    CONSTRAINT check_doc_size CHECK (doc_size >= 0)
);



CREATE SCHEMA IF NOT EXISTS market_data;

-- Table for storing raw and enriched news data
CREATE TABLE IF NOT EXISTS market_data.stock_news (
    news_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT,
    sentiment INTEGER,              -- e.g., -1 (Negative) to 1 (Positive)
    event_type VARCHAR(50),         -- e.g., 'merger', 'bankruptcy', 'vote', 'earnings'
    is_speculative BOOLEAN DEFAULT FALSE,
    source_url TEXT,
    published_date TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- Prevents duplicate entries from multiple API calls
    CONSTRAINT unique_ticker_news UNIQUE (ticker, headline, published_date)
);

-- Index for fast lookups on ticker-specific news sorted by date
CREATE INDEX IF NOT EXISTS idx_news_ticker_date 
ON market_data.stock_news (ticker, published_date DESC);



-- Table to store gains based on document
CREATE TABLE oden.stock_gains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Filing & Entity Tracking
    doc_id VARCHAR(50) NOT NULL,
    filer_name VARCHAR(255) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    asset_type VARCHAR(50),
    
    -- Trade Details
    transaction_type VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    amount_range VARCHAR(100),
    amount_min NUMERIC(14,2),
    amount_max NUMERIC(14,2),
    estimated_cost NUMERIC(14,2),      
    quantity NUMERIC(14,4),            
    
    -- Performance Tracking
    current_price NUMERIC(14,4),       
    price_change_pct NUMERIC(8,2),
    
    -- Audit & Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);


CREATE TABLE oden.natural_language_queries(
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT DEFAULT NULL,
    response TEXT DEFAULT NULL,
    params TEXT DEFAULT NULL,
    status VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);