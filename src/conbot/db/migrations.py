"""
Database migration and backup utilities for ConBOT.

Provides functions for:
- Creating/dropping database schema
- Exporting data to JSON (for backup/migration)
- Importing data from JSON (restore/Databricks migration)
"""

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Dict, Any, List
import os

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from .schema import (
    Base,
    ConferenceCurrentTable,
    ConferencesAuditTable,
    ScanHistoryTable,
    create_tables,
    drop_tables,
)

logger = logging.getLogger(__name__)


def get_engine(db_path: str):
    """
    Create SQLAlchemy engine for SQLite database.

    Args:
        db_path: Path to SQLite database file

    Returns:
        SQLAlchemy engine
    """
    # Expand user home directory
    expanded_path = os.path.expanduser(db_path)

    # Create directory if it doesn't exist
    db_dir = os.path.dirname(expanded_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")

    # Create engine
    engine = create_engine(
        f"sqlite:///{expanded_path}",
        echo=False,  # Set to True for SQL debugging
        connect_args={"check_same_thread": False}  # Allow multi-threading
    )

    logger.info(f"Connected to SQLite database: {expanded_path}")
    return engine


def initialize_database(db_path: str) -> bool:
    """
    Initialize database schema.

    Creates all tables if they don't exist.

    Args:
        db_path: Path to SQLite database file

    Returns:
        True if successful

    Example:
        >>> initialize_database("~/.conbot/conbot.db")
    """
    try:
        engine = get_engine(db_path)

        # Check if tables already exist
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        if existing_tables:
            logger.info(f"Database already initialized ({len(existing_tables)} tables found)")
            return True

        # Create tables
        create_tables(engine)
        logger.info("Database schema created successfully")

        # Verify
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Created tables: {', '.join(tables)}")

        return True

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def reset_database(db_path: str) -> bool:
    """
    Reset database by dropping and recreating all tables.

    WARNING: This will delete all data!

    Args:
        db_path: Path to SQLite database file

    Returns:
        True if successful
    """
    try:
        engine = get_engine(db_path)

        logger.warning("Resetting database (all data will be lost)")

        # Drop all tables
        drop_tables(engine)
        logger.info("Dropped all tables")

        # Recreate tables
        create_tables(engine)
        logger.info("Recreated database schema")

        return True

    except Exception as e:
        logger.error(f"Failed to reset database: {e}")
        raise


def export_to_json(db_path: str, output_dir: str = None) -> Dict[str, str]:
    """
    Export all data to JSON files.

    Creates three JSON files:
    - current.json: conferences_current table
    - audit.json: conferences_audit table
    - history.json: scan_history table

    Args:
        db_path: Path to SQLite database
        output_dir: Directory for JSON files (default: ./backup_TIMESTAMP)

    Returns:
        Dictionary mapping table names to JSON file paths

    Example:
        >>> files = export_to_json("~/.conbot/conbot.db")
        >>> print(files['current'])
        './backup_20260214_103000/current.json'
    """
    try:
        engine = get_engine(db_path)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Create output directory
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = f"./backup_{timestamp}"

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Exporting data to: {output_path}")

        exported_files = {}

        # Export conferences_current
        current_records = session.query(ConferenceCurrentTable).all()
        current_data = []
        for record in current_records:
            row_dict = {
                'conference_id': record.conference_id,
                'url': record.url,
                'watch_mode': record.watch_mode,
                'next_run_at': record.next_run_at.isoformat() if record.next_run_at else None,
                'last_scan_at': record.last_scan_at.isoformat() if record.last_scan_at else None,
                'is_active': record.is_active,
                'binary_hash': record.binary_hash,
                'filtered_hash': record.filtered_hash,
                'simhash_signature': record.simhash_signature,
                'current_deadlines': record.current_deadlines,
                'current_summary': record.current_summary,
                'tracked_links': record.tracked_links,
                'consecutive_no_change_count': record.consecutive_no_change_count,
                'consecutive_error_count': record.consecutive_error_count,
                'total_scans': record.total_scans,
                'last_error': record.last_error,
                'updated_at': record.updated_at.isoformat() if record.updated_at else None,
            }
            current_data.append(row_dict)

        current_file = output_path / "current.json"
        with open(current_file, 'w') as f:
            json.dump(current_data, f, indent=2)
        exported_files['current'] = str(current_file)
        logger.info(f"Exported {len(current_data)} conferences to {current_file}")

        # Export conferences_audit
        audit_records = session.query(ConferencesAuditTable).all()
        audit_data = []
        for record in audit_records:
            row_dict = {
                'audit_id': record.audit_id,
                'conference_id': record.conference_id,
                'scan_timestamp': record.scan_timestamp.isoformat() if record.scan_timestamp else None,
                'change_detected': record.change_detected,
                'change_type': record.change_type,
                'hamming_distance': record.hamming_distance,
                'deadlines_found': record.deadlines_found,
                'summary': record.summary,
                'previous_watch_mode': record.previous_watch_mode,
                'new_watch_mode': record.new_watch_mode,
                'transition_reason': record.transition_reason,
                'fetch_method': record.fetch_method,
                'scan_duration_seconds': record.scan_duration_seconds,
                'llm_api_called': record.llm_api_called,
                'email_sent': record.email_sent,
            }
            audit_data.append(row_dict)

        audit_file = output_path / "audit.json"
        with open(audit_file, 'w') as f:
            json.dump(audit_data, f, indent=2)
        exported_files['audit'] = str(audit_file)
        logger.info(f"Exported {len(audit_data)} audit records to {audit_file}")

        # Export scan_history
        history_records = session.query(ScanHistoryTable).all()
        history_data = []
        for record in history_records:
            row_dict = {
                'run_id': record.run_id,
                'conference_id': record.conference_id,
                'url': record.url,
                'started_at': record.started_at.isoformat() if record.started_at else None,
                'completed_at': record.completed_at.isoformat() if record.completed_at else None,
                'status': record.status,
                'fetch_method': record.fetch_method,
                'fetch_duration_ms': record.fetch_duration_ms,
                'change_detected': record.change_detected,
                'deadlines_count': record.deadlines_count,
                'email_type': record.email_type,
                'error_details': record.error_details,
            }
            history_data.append(row_dict)

        history_file = output_path / "history.json"
        with open(history_file, 'w') as f:
            json.dump(history_data, f, indent=2)
        exported_files['history'] = str(history_file)
        logger.info(f"Exported {len(history_data)} history records to {history_file}")

        session.close()

        logger.info(f"Export complete: {len(current_data)} conferences, "
                   f"{len(audit_data)} audits, {len(history_data)} history")

        return exported_files

    except Exception as e:
        logger.error(f"Failed to export data: {e}")
        raise


def import_from_json(
    db_path: str,
    current_file: str = None,
    audit_file: str = None,
    history_file: str = None
) -> Dict[str, int]:
    """
    Import data from JSON files.

    Args:
        db_path: Path to SQLite database
        current_file: Path to current.json (optional)
        audit_file: Path to audit.json (optional)
        history_file: Path to history.json (optional)

    Returns:
        Dictionary with record counts imported per table

    Example:
        >>> counts = import_from_json(
        ...     "~/.conbot/conbot.db",
        ...     current_file="backup/current.json",
        ...     audit_file="backup/audit.json",
        ...     history_file="backup/history.json"
        ... )
        >>> print(counts)
        {'current': 6, 'audit': 42, 'history': 42}
    """
    try:
        engine = get_engine(db_path)
        Session = sessionmaker(bind=engine)
        session = Session()

        counts = {}

        # Import conferences_current
        if current_file and Path(current_file).exists():
            with open(current_file, 'r') as f:
                current_data = json.load(f)

            for row_dict in current_data:
                # Convert ISO strings back to datetime
                if row_dict.get('next_run_at'):
                    row_dict['next_run_at'] = datetime.fromisoformat(row_dict['next_run_at'])
                if row_dict.get('last_scan_at'):
                    row_dict['last_scan_at'] = datetime.fromisoformat(row_dict['last_scan_at'])
                if row_dict.get('updated_at'):
                    row_dict['updated_at'] = datetime.fromisoformat(row_dict['updated_at'])

                record = ConferenceCurrentTable(**row_dict)
                session.merge(record)  # INSERT OR REPLACE

            session.commit()
            counts['current'] = len(current_data)
            logger.info(f"Imported {counts['current']} conferences")

        # Import conferences_audit
        if audit_file and Path(audit_file).exists():
            with open(audit_file, 'r') as f:
                audit_data = json.load(f)

            for row_dict in audit_data:
                if row_dict.get('scan_timestamp'):
                    row_dict['scan_timestamp'] = datetime.fromisoformat(row_dict['scan_timestamp'])

                record = ConferencesAuditTable(**row_dict)
                session.add(record)

            session.commit()
            counts['audit'] = len(audit_data)
            logger.info(f"Imported {counts['audit']} audit records")

        # Import scan_history
        if history_file and Path(history_file).exists():
            with open(history_file, 'r') as f:
                history_data = json.load(f)

            for row_dict in history_data:
                if row_dict.get('started_at'):
                    row_dict['started_at'] = datetime.fromisoformat(row_dict['started_at'])
                if row_dict.get('completed_at'):
                    row_dict['completed_at'] = datetime.fromisoformat(row_dict['completed_at'])

                record = ScanHistoryTable(**row_dict)
                session.merge(record)  # INSERT OR REPLACE

            session.commit()
            counts['history'] = len(history_data)
            logger.info(f"Imported {counts['history']} history records")

        session.close()

        logger.info(f"Import complete: {counts}")
        return counts

    except Exception as e:
        logger.error(f"Failed to import data: {e}")
        raise


def vacuum_database(db_path: str) -> bool:
    """
    Vacuum database to reclaim space and optimize performance.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if successful

    Example:
        >>> vacuum_database("~/.conbot/conbot.db")
    """
    try:
        engine = get_engine(db_path)

        with engine.connect() as connection:
            connection.execute("VACUUM")
            logger.info("Database vacuumed successfully")

        return True

    except Exception as e:
        logger.error(f"Failed to vacuum database: {e}")
        raise
