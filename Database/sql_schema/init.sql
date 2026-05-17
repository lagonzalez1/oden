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
    amount_range NUMERIC(14,2),
    amount_min NUMERIC(14,2),
    amount_max NUMERIC(14,2),
    estimated_cost NUMERIC(14,2),      
    quantity NUMERIC(14,4),            
    
    -- Performance Tracking
    purchase_price NUMERIC(14,4),
    current_price NUMERIC(14,4),       
    price_change_pct NUMERIC(8,2),

    benchmark_return_pct NUMERIC(8,2),
    alpha_vs_benchmark NUMERIC(8,2),    
    
    -- Risk & Timing
    max_drawdown_pct NUMERIC(8,2),      
    days_to_peak INTEGER,               
    
    -- Conviction
    is_initial_entry BOOLEAN,           
    percent_of_total_holdings NUMERIC(5,2),
    
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


CREATE TABLE IF NOT EXISTS oden.committee (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_id VARCHAR(10) UNIQUE, -- e.g., 'SSAF'
    parent_committee_id UUID REFERENCES oden.committee(id), -- For subcommittees
    congress_num SMALLINT, -- e.g., 119
    chamber VARCHAR(50), -- house, senate, joint
    committee_type VARCHAR(50), -- standing, select, special, joint
    title VARCHAR(255) NOT NULL,
    url VARCHAR(255),
    office VARCHAR(100),
    is_subcommittee BOOLEAN DEFAULT FALSE,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE IF NOT EXISTS oden.legislator (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bioguide_id VARCHAR(10) UNIQUE NOT NULL, -- Standard U.S. Congress ID
    prefix VARCHAR(50),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    party VARCHAR(50), -- Democrat, Republican, Independent
    state CHAR(2), -- e.g., 'NY', 'TX'
    district VARCHAR(10), -- '00' for At-Large, or '01', '02', etc.
    chamber VARCHAR(20), -- House or Senate
    leadership_role VARCHAR(250), -- e.g., 'Speaker', 'Majority Leader'
    twitter_handle VARCHAR(100),
    official_url VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS oden.committee_membership (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legislator_id UUID REFERENCES oden.legislator(id) ON DELETE CASCADE,
    committee_id UUID REFERENCES oden.committee(id) ON DELETE CASCADE,
    
    -- Specific assignment details
    role VARCHAR(100) DEFAULT 'Member', -- 'Chair', 'Ranking Member', 'Vice Chair'
    rank_in_party INT, -- Seniority rank within their party on the committee
    is_ex_officio BOOLEAN DEFAULT FALSE, -- Some leaders serve automatically
    assignment_date DATE,
    
    -- Ensure a legislator isn't added to the same committee twice in one session
    UNIQUE(legislator_id, committee_id)
);
