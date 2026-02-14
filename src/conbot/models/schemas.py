"""
Delta table schema definitions for conference tracking system.

Defines DDL strings for creating three main tables:
1. conferences_current: Current state of each monitored conference
2. conferences_audit: Append-only audit trail of all scans
3. scan_history: Performance and error tracking

These schemas are used by databricks/init_scripts/setup_tables.py
"""

# Current state table - one row per (conference_id, url)
CONFERENCES_CURRENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS conferences_current (
    conference_id STRING NOT NULL COMMENT 'Unique identifier for the conference (e.g., uitp_summit)',
    url STRING NOT NULL COMMENT 'Primary URL being monitored',

    -- Watch mode and scheduling
    watch_mode STRING NOT NULL COMMENT 'Monitoring frequency: MONTHLY, BIWEEKLY, or URGENT',
    next_run_at TIMESTAMP NOT NULL COMMENT 'Next scheduled scan time',
    last_scan_at TIMESTAMP COMMENT 'Most recent scan timestamp',

    -- Three-tier fingerprints for change detection
    binary_hash STRING COMMENT 'SHA-256 hash of raw HTML (tier 1)',
    filtered_hash STRING COMMENT 'SHA-256 hash of filtered content (tier 2)',
    simhash_signature BIGINT COMMENT 'SimHash signature for semantic similarity (tier 3)',

    -- Extracted data
    current_deadlines ARRAY<STRUCT<
        date: DATE,
        type: STRING,           -- abstract, paper, registration, camera-ready, general
        confidence: DOUBLE,
        source_text: STRING
    >> COMMENT 'Most recently extracted deadlines',
    current_summary STRING COMMENT 'Latest LLM-generated summary',

    -- Link discovery (for TRB/ITF)
    tracked_links ARRAY<STRUCT<
        url: STRING,
        score: DOUBLE,
        first_seen: TIMESTAMP
    >> COMMENT 'Discovered links being monitored',

    -- Counters and metadata
    consecutive_no_change_count INT DEFAULT 0 COMMENT 'Number of scans with no change',
    consecutive_error_count INT DEFAULT 0 COMMENT 'Number of consecutive failed scans',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Whether monitoring is enabled',
    updated_at TIMESTAMP NOT NULL COMMENT 'Last update timestamp',

    CONSTRAINT pk_conferences_current PRIMARY KEY (conference_id, url)
) USING DELTA
PARTITIONED BY (watch_mode)
COMMENT 'Current state of monitored conferences (Type-2 SCD)'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
"""

# Audit trail table - append-only history
CONFERENCES_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS conferences_audit (
    audit_id STRING NOT NULL COMMENT 'UUID for this audit record',
    conference_id STRING NOT NULL COMMENT 'Conference being scanned',
    url STRING NOT NULL COMMENT 'URL that was scanned',
    scan_timestamp TIMESTAMP NOT NULL COMMENT 'When the scan occurred',

    -- Change detection results
    change_detected BOOLEAN NOT NULL COMMENT 'Whether any change was found',
    change_type STRING NOT NULL COMMENT 'Type: BINARY, FILTERED, SEMANTIC, NONE',
    previous_hash STRING COMMENT 'Previous fingerprint value',
    new_hash STRING COMMENT 'New fingerprint value',
    hamming_distance INT COMMENT 'Hamming distance for SimHash comparison',

    -- Extracted data
    deadlines_found ARRAY<STRUCT<
        date: DATE,
        type: STRING,
        confidence: DOUBLE,
        source_text: STRING
    >> COMMENT 'Deadlines extracted during this scan',
    summary STRING COMMENT 'LLM-generated summary if content changed',

    -- State transition
    previous_watch_mode STRING COMMENT 'Watch mode before scan',
    new_watch_mode STRING COMMENT 'Watch mode after scan',
    transition_reason STRING COMMENT 'Why mode changed (NO_CHANGE, DEADLINES_PUBLISHED, etc.)',

    -- Performance and LLM usage
    scan_duration_seconds DOUBLE COMMENT 'Total scan time in seconds',
    llm_api_called BOOLEAN DEFAULT FALSE COMMENT 'Whether OpenAI API was invoked',
    email_sent BOOLEAN DEFAULT FALSE COMMENT 'Whether email notification was sent',

    -- Error handling
    error_message STRING COMMENT 'Error message if scan failed',

    CONSTRAINT pk_conferences_audit PRIMARY KEY (audit_id)
) USING DELTA
PARTITIONED BY (DATE(scan_timestamp))
COMMENT 'Append-only audit trail of all conference scans'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'false',
    'delta.logRetentionDuration' = 'interval 90 days',
    'delta.deletedFileRetentionDuration' = 'interval 30 days'
)
"""

# Performance tracking table
SCAN_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_history (
    run_id STRING NOT NULL COMMENT 'UUID for workflow run (same for all conferences in one run)',
    conference_id STRING NOT NULL COMMENT 'Conference being scanned',
    url STRING NOT NULL COMMENT 'URL that was scanned',

    -- Timing
    started_at TIMESTAMP NOT NULL COMMENT 'Scan start time',
    completed_at TIMESTAMP COMMENT 'Scan completion time (NULL if failed)',
    status STRING NOT NULL COMMENT 'RUNNING, SUCCESS, FAILED',

    -- Performance breakdown
    fetch_method STRING COMMENT 'requests or playwright',
    fetch_duration_ms INT COMMENT 'Time to fetch HTML in milliseconds',
    extraction_duration_ms INT COMMENT 'Time to extract content in milliseconds',
    llm_duration_ms INT COMMENT 'Time for LLM call in milliseconds',
    total_duration_ms INT COMMENT 'Total scan time in milliseconds',

    -- Results summary
    change_detected BOOLEAN COMMENT 'Whether change was found',
    deadlines_count INT DEFAULT 0 COMMENT 'Number of deadlines extracted',
    email_type STRING COMMENT 'NO_CHANGE, CHANGE_NO_DATES, CHANGE_WITH_DATES',

    -- Error details
    error_details STRING COMMENT 'Full error traceback if failed',

    CONSTRAINT pk_scan_history PRIMARY KEY (run_id, conference_id, url)
) USING DELTA
PARTITIONED BY (DATE(started_at))
COMMENT 'Performance and error tracking for scans'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'false',
    'delta.logRetentionDuration' = 'interval 30 days',
    'delta.deletedFileRetentionDuration' = 'interval 7 days'
)
"""

# All schemas for easy iteration
ALL_SCHEMAS = {
    "conferences_current": CONFERENCES_CURRENT_SCHEMA,
    "conferences_audit": CONFERENCES_AUDIT_SCHEMA,
    "scan_history": SCAN_HISTORY_SCHEMA,
}


def get_schema(table_name: str) -> str:
    """
    Get DDL for a specific table.

    Args:
        table_name: Name of the table (conferences_current, conferences_audit, scan_history)

    Returns:
        DDL string for creating the table

    Raises:
        KeyError: If table_name is not recognized
    """
    if table_name not in ALL_SCHEMAS:
        raise KeyError(
            f"Unknown table '{table_name}'. "
            f"Valid tables: {', '.join(ALL_SCHEMAS.keys())}"
        )
    return ALL_SCHEMAS[table_name]


def get_all_schemas() -> dict:
    """
    Get all table schemas.

    Returns:
        Dictionary mapping table names to DDL strings
    """
    return ALL_SCHEMAS.copy()
