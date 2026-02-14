"""
SQLite storage interface for conference state management.

Drop-in replacement for DeltaStore that uses SQLite instead of Delta Lake.

Provides identical CRUD operations for:
- conferences_current (current state)
- conferences_audit (append-only history)
- scan_history (performance tracking)
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from ..models.conference import ConferenceState, WatchMode
from ..db.schema import (
    ConferenceCurrentTable,
    ConferencesAuditTable,
    ScanHistoryTable,
    serialize_deadlines,
    serialize_tracked_links,
    deserialize_deadlines,
    deserialize_tracked_links,
)
from ..db.migrations import initialize_database

logger = logging.getLogger(__name__)


class SQLiteStoreError(Exception):
    """Raised when SQLite store operations fail."""
    pass


class SQLiteStore:
    """
    SQLite implementation of the storage interface.

    Compatible with DeltaStore API but uses local SQLite database.
    Thread-safe with connection pooling.

    Example:
        >>> store = SQLiteStore(db_path="~/.conbot/conbot.db")
        >>> state = store.get_conference_state("uitp_summit", "https://...")
        >>> store.upsert_conference(state)
        >>> store.insert_audit_record(audit_data)
    """

    def __init__(self, db_path: str):
        """
        Initialize SQLite store.

        Creates database and tables if they don't exist.

        Args:
            db_path: Path to SQLite database file (e.g., "~/.conbot/conbot.db")
        """
        self.db_path = db_path

        # Initialize database (creates tables if needed)
        initialize_database(db_path)

        # Create engine with connection pooling
        import os
        expanded_path = os.path.expanduser(db_path)
        self.engine = create_engine(
            f"sqlite:///{expanded_path}",
            echo=False,  # Set to True for SQL debugging
            connect_args={"check_same_thread": False},  # Allow multi-threading
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Verify connections before use
        )

        # Create session factory
        self.Session = sessionmaker(bind=self.engine)

        logger.info(f"SQLiteStore initialized: {db_path}")

    def get_conference_state(
        self,
        conference_id: str,
        url: str
    ) -> Optional[ConferenceState]:
        """
        Retrieve current state for a conference.

        Args:
            conference_id: Conference identifier
            url: Primary URL being monitored

        Returns:
            ConferenceState object or None if not found

        Example:
            >>> state = store.get_conference_state("uitp_summit", "https://...")
            >>> if state:
            ...     print(f"Watch mode: {state.watch_mode}")
        """
        session = self.Session()

        try:
            # Query for conference
            record = session.query(ConferenceCurrentTable).filter_by(
                conference_id=conference_id,
            ).first()

            if not record:
                logger.debug(f"No state found for {conference_id}")
                return None

            # Convert to ConferenceState
            state = record.to_conference_state()

            logger.debug(f"Retrieved state for {conference_id}: {state.watch_mode.value}")
            return state

        except Exception as e:
            raise SQLiteStoreError(f"Failed to get conference state: {e}") from e

        finally:
            session.close()

    def upsert_conference(self, state: ConferenceState) -> bool:
        """
        Insert or update conference state.

        Uses INSERT OR REPLACE for upsert operation.

        Args:
            state: ConferenceState to persist

        Returns:
            True if successful

        Example:
            >>> state = ConferenceState(...)
            >>> store.upsert_conference(state)
        """
        session = self.Session()

        try:
            # Check if conference exists
            existing = session.query(ConferenceCurrentTable).filter_by(
                conference_id=state.conference_id
            ).first()

            if existing:
                # Update existing record
                existing.url = str(state.url)
                existing.watch_mode = state.watch_mode.value
                existing.next_run_at = state.next_run_at
                existing.last_scan_at = state.last_scan_at
                existing.binary_hash = state.binary_hash
                existing.filtered_hash = state.filtered_hash
                existing.simhash_signature = state.simhash_signature
                existing.current_deadlines = serialize_deadlines(state.current_deadlines)
                existing.current_summary = state.current_summary
                existing.tracked_links = serialize_tracked_links(state.tracked_links)
                existing.consecutive_no_change_count = state.consecutive_no_change_count
                existing.consecutive_error_count = state.consecutive_error_count
                existing.is_active = state.is_active
                existing.updated_at = datetime.now()

                logger.info(f"Updated conference state for {state.conference_id}")
            else:
                # Insert new record
                new_record = ConferenceCurrentTable.from_conference_state(state)
                session.add(new_record)

                logger.info(f"Inserted new conference state for {state.conference_id}")

            session.commit()
            return True

        except Exception as e:
            session.rollback()
            raise SQLiteStoreError(f"Failed to upsert conference: {e}") from e

        finally:
            session.close()

    def update_conference(
        self,
        conference_id: str,
        url: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update specific fields for a conference.

        Args:
            conference_id: Conference identifier
            url: URL (not used in SQLite, kept for API compatibility)
            updates: Dictionary of field names to new values

        Returns:
            True if successful

        Example:
            >>> store.update_conference(
            ...     "uitp_summit",
            ...     "https://...",
            ...     {'watch_mode': 'URGENT', 'consecutive_error_count': 0}
            ... )
        """
        session = self.Session()

        try:
            # Get conference
            record = session.query(ConferenceCurrentTable).filter_by(
                conference_id=conference_id
            ).first()

            if not record:
                raise SQLiteStoreError(f"Conference not found: {conference_id}")

            # Apply updates
            for field, value in updates.items():
                if hasattr(record, field):
                    setattr(record, field, value)
                else:
                    logger.warning(f"Unknown field in update: {field}")

            # Update timestamp
            record.updated_at = datetime.now()

            session.commit()
            logger.info(f"Updated conference {conference_id}: {list(updates.keys())}")
            return True

        except Exception as e:
            session.rollback()
            raise SQLiteStoreError(f"Failed to update conference: {e}") from e

        finally:
            session.close()

    def insert_audit_record(self, audit_data: Dict[str, Any]) -> bool:
        """
        Insert audit record into conferences_audit table.

        Args:
            audit_data: Dictionary with audit fields

        Returns:
            True if successful

        Example:
            >>> audit_data = {
            ...     'conference_id': 'uitp_summit',
            ...     'scan_timestamp': datetime.now(),
            ...     'change_detected': True,
            ...     'deadlines_found': [...]  # List of Deadline objects
            ...     ...
            ... }
            >>> store.insert_audit_record(audit_data)
        """
        session = self.Session()

        try:
            # Serialize deadlines if present
            if 'deadlines_found' in audit_data:
                deadlines = audit_data['deadlines_found']
                audit_data['deadlines_found'] = serialize_deadlines(deadlines)

            # Create audit record
            record = ConferencesAuditTable(**audit_data)
            session.add(record)
            session.commit()

            logger.debug(f"Inserted audit record for {audit_data.get('conference_id')}")
            return True

        except Exception as e:
            session.rollback()
            raise SQLiteStoreError(f"Failed to insert audit record: {e}") from e

        finally:
            session.close()

    def insert_scan_history(self, history_data: Dict[str, Any]) -> bool:
        """
        Insert scan history record.

        Args:
            history_data: Dictionary with scan history fields

        Returns:
            True if successful

        Example:
            >>> history_data = {
            ...     'run_id': str(uuid.uuid4()),
            ...     'conference_id': 'uitp_summit',
            ...     'url': 'https://...',
            ...     'started_at': datetime.now(),
            ...     'status': 'succeeded',
            ...     ...
            ... }
            >>> store.insert_scan_history(history_data)
        """
        session = self.Session()

        try:
            # Create history record
            record = ScanHistoryTable(**history_data)
            session.add(record)
            session.commit()

            logger.debug(f"Inserted scan history: {history_data.get('run_id')}")
            return True

        except Exception as e:
            session.rollback()
            raise SQLiteStoreError(f"Failed to insert scan history: {e}") from e

        finally:
            session.close()

    def get_conferences_due_for_scan(self, current_time: datetime = None) -> List[ConferenceState]:
        """
        Get conferences that are due for scanning.

        Args:
            current_time: Current timestamp (default: now)

        Returns:
            List of ConferenceState objects

        Example:
            >>> conferences = store.get_conferences_due_for_scan()
            >>> for conf in conferences:
            ...     print(f"Scan {conf.conference_id}")
        """
        if current_time is None:
            current_time = datetime.now()

        session = self.Session()

        try:
            # Query conferences due for scan
            records = session.query(ConferenceCurrentTable).filter(
                ConferenceCurrentTable.is_active == True,
                ConferenceCurrentTable.next_run_at <= current_time
            ).order_by(
                # Priority order: URGENT > BIWEEKLY > MONTHLY
                ConferenceCurrentTable.watch_mode.desc(),
                ConferenceCurrentTable.next_run_at.asc()
            ).all()

            # Convert to ConferenceState objects
            conferences = [record.to_conference_state() for record in records]

            logger.info(f"Found {len(conferences)} conferences due for scan")
            return conferences

        except Exception as e:
            raise SQLiteStoreError(f"Failed to get conferences due for scan: {e}") from e

        finally:
            session.close()

    def query(self, sql: str):
        """
        Execute arbitrary SQL query.

        Args:
            sql: SQL query string

        Returns:
            SQLAlchemy result

        Example:
            >>> result = store.query("SELECT * FROM conferences_current WHERE is_active = 1")
            >>> for row in result:
            ...     print(row)
        """
        session = self.Session()

        try:
            result = session.execute(sql)
            return result

        except Exception as e:
            raise SQLiteStoreError(f"Query failed: {e}") from e

        finally:
            session.close()

    def get_all_conferences(self) -> List[ConferenceState]:
        """
        Get all conferences (active and inactive).

        Returns:
            List of ConferenceState objects

        Example:
            >>> all_conferences = store.get_all_conferences()
            >>> active = [c for c in all_conferences if c.is_active]
        """
        session = self.Session()

        try:
            records = session.query(ConferenceCurrentTable).all()
            conferences = [record.to_conference_state() for record in records]

            logger.info(f"Retrieved {len(conferences)} total conferences")
            return conferences

        except Exception as e:
            raise SQLiteStoreError(f"Failed to get all conferences: {e}") from e

        finally:
            session.close()

    def close(self):
        """
        Close database connections.

        Cleanup method for graceful shutdown.
        """
        self.engine.dispose()
        logger.info("SQLiteStore connections closed")
