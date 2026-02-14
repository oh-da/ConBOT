"""
Delta table interface for conference state management.

Provides CRUD operations for:
- conferences_current (current state)
- conferences_audit (append-only history)
- scan_history (performance tracking)
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
from ..models.conference import ConferenceState, ScanResult, WatchMode
import json

logger = logging.getLogger(__name__)


class DeltaStoreError(Exception):
    """Raised when Delta store operations fail."""
    pass


class DeltaStore:
    """
    Interface for Delta table operations.

    Handles all database interactions for conference tracking.
    Works with both real Delta tables (Databricks) and mocks (testing).

    Example:
        >>> store = DeltaStore()
        >>> state = store.get_conference_state("uitp_summit", "https://...")
        >>> store.update_conference(state.conference_id, state.url, updates)
        >>> store.insert_audit_record(audit_data)
    """

    def __init__(self, catalog: str = "conbot", schema: str = "default"):
        """
        Initialize Delta store.

        Args:
            catalog: Delta catalog name (default: "conbot")
            schema: Delta schema name (default: "default")
        """
        self.catalog = catalog
        self.schema = schema
        self._spark = None

    @property
    def spark(self):
        """Lazy-load Spark session."""
        if self._spark is None:
            try:
                from pyspark.sql import SparkSession
                self._spark = SparkSession.builder.getOrCreate()
                logger.info(f"Connected to Spark session: {self._spark.version}")
            except ImportError:
                raise ImportError(
                    "PySpark not installed. "
                    "Install with: pip install pyspark delta-spark"
                )
        return self._spark

    def _table_name(self, table: str) -> str:
        """Get fully qualified table name."""
        return f"{self.catalog}.{self.schema}.{table}"

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
        query = f"""
        SELECT *
        FROM {self._table_name('conferences_current')}
        WHERE conference_id = '{conference_id}'
          AND url = '{url}'
        """

        try:
            df = self.spark.sql(query)
            rows = df.collect()

            if not rows:
                logger.debug(f"No state found for {conference_id} @ {url}")
                return None

            row = rows[0]

            # Convert row to ConferenceState
            state = ConferenceState(
                conference_id=row.conference_id,
                url=row.url,
                watch_mode=WatchMode(row.watch_mode),
                next_run_at=row.next_run_at,
                last_scan_at=row.last_scan_at,
                binary_hash=row.binary_hash,
                filtered_hash=row.filtered_hash,
                simhash_signature=row.simhash_signature,
                current_deadlines=row.current_deadlines or [],
                current_summary=row.current_summary,
                tracked_links=row.tracked_links or [],
                consecutive_no_change_count=row.consecutive_no_change_count,
                consecutive_error_count=row.consecutive_error_count,
                is_active=row.is_active,
                updated_at=row.updated_at,
            )

            logger.debug(f"Retrieved state for {conference_id}: {state.watch_mode.value}")
            return state

        except Exception as e:
            raise DeltaStoreError(f"Failed to get conference state: {e}") from e

    def upsert_conference(self, state: ConferenceState) -> bool:
        """
        Insert or update conference state.

        Uses Delta MERGE for upsert operation.

        Args:
            state: ConferenceState to persist

        Returns:
            True if successful

        Example:
            >>> state = ConferenceState(...)
            >>> store.upsert_conference(state)
        """
        table = self._table_name('conferences_current')

        # Convert state to dict for SQL
        state_dict = {
            'conference_id': state.conference_id,
            'url': str(state.url),
            'watch_mode': state.watch_mode.value,
            'next_run_at': state.next_run_at.isoformat(),
            'last_scan_at': state.last_scan_at.isoformat() if state.last_scan_at else None,
            'binary_hash': state.binary_hash,
            'filtered_hash': state.filtered_hash,
            'simhash_signature': state.simhash_signature,
            'current_deadlines': [d.dict() for d in state.current_deadlines],
            'current_summary': state.current_summary,
            'tracked_links': [l.dict() for l in state.tracked_links],
            'consecutive_no_change_count': state.consecutive_no_change_count,
            'consecutive_error_count': state.consecutive_error_count,
            'is_active': state.is_active,
            'updated_at': datetime.now().isoformat(),
        }

        try:
            # Create temporary view from state
            from pyspark.sql import Row
            df = self.spark.createDataFrame([Row(**state_dict)])
            df.createOrReplaceTempView("temp_state")

            # MERGE operation
            merge_sql = f"""
            MERGE INTO {table} AS target
            USING temp_state AS source
            ON target.conference_id = source.conference_id
               AND target.url = source.url
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
            """

            self.spark.sql(merge_sql)
            logger.info(f"Upserted conference state for {state.conference_id}")
            return True

        except Exception as e:
            raise DeltaStoreError(f"Failed to upsert conference: {e}") from e

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
            url: URL
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
        table = self._table_name('conferences_current')

        # Build SET clause
        set_clauses = []
        for field, value in updates.items():
            if isinstance(value, str):
                set_clauses.append(f"{field} = '{value}'")
            elif value is None:
                set_clauses.append(f"{field} = NULL")
            else:
                set_clauses.append(f"{field} = {value}")

        # Add updated_at
        set_clauses.append(f"updated_at = '{datetime.now().isoformat()}'")

        set_clause = ", ".join(set_clauses)

        update_sql = f"""
        UPDATE {table}
        SET {set_clause}
        WHERE conference_id = '{conference_id}'
          AND url = '{url}'
        """

        try:
            self.spark.sql(update_sql)
            logger.info(f"Updated conference {conference_id}: {list(updates.keys())}")
            return True

        except Exception as e:
            raise DeltaStoreError(f"Failed to update conference: {e}") from e

    def insert_audit_record(self, audit_data: Dict[str, Any]) -> bool:
        """
        Insert audit record into conferences_audit table.

        Args:
            audit_data: Dictionary with audit fields

        Returns:
            True if successful

        Example:
            >>> audit_data = {
            ...     'audit_id': str(uuid.uuid4()),
            ...     'conference_id': 'uitp_summit',
            ...     'scan_timestamp': datetime.now(),
            ...     'change_detected': True,
            ...     ...
            ... }
            >>> store.insert_audit_record(audit_data)
        """
        table = self._table_name('conferences_audit')

        try:
            from pyspark.sql import Row
            df = self.spark.createDataFrame([Row(**audit_data)])
            df.write.format("delta").mode("append").saveAsTable(table)

            logger.debug(f"Inserted audit record: {audit_data['audit_id']}")
            return True

        except Exception as e:
            raise DeltaStoreError(f"Failed to insert audit record: {e}") from e

    def insert_scan_history(self, history_data: Dict[str, Any]) -> bool:
        """
        Insert scan history record.

        Args:
            history_data: Dictionary with scan history fields

        Returns:
            True if successful
        """
        table = self._table_name('scan_history')

        try:
            from pyspark.sql import Row
            df = self.spark.createDataFrame([Row(**history_data)])
            df.write.format("delta").mode("append").saveAsTable(table)

            logger.debug(f"Inserted scan history: {history_data['run_id']}")
            return True

        except Exception as e:
            raise DeltaStoreError(f"Failed to insert scan history: {e}") from e

    def query(self, sql: str):
        """
        Execute arbitrary SQL query.

        Args:
            sql: SQL query string

        Returns:
            Spark DataFrame with results

        Example:
            >>> df = store.query("SELECT * FROM conferences_current WHERE is_active = TRUE")
            >>> conferences = df.collect()
        """
        try:
            return self.spark.sql(sql)
        except Exception as e:
            raise DeltaStoreError(f"Query failed: {e}") from e

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

        query = f"""
        SELECT *
        FROM {self._table_name('conferences_current')}
        WHERE is_active = TRUE
          AND next_run_at <= '{current_time.isoformat()}'
        ORDER BY watch_mode DESC, next_run_at ASC
        """

        try:
            df = self.spark.sql(query)
            rows = df.collect()

            conferences = []
            for row in rows:
                state = ConferenceState(
                    conference_id=row.conference_id,
                    url=row.url,
                    watch_mode=WatchMode(row.watch_mode),
                    next_run_at=row.next_run_at,
                    last_scan_at=row.last_scan_at,
                    binary_hash=row.binary_hash,
                    filtered_hash=row.filtered_hash,
                    simhash_signature=row.simhash_signature,
                    current_deadlines=row.current_deadlines or [],
                    current_summary=row.current_summary,
                    tracked_links=row.tracked_links or [],
                    consecutive_no_change_count=row.consecutive_no_change_count,
                    consecutive_error_count=row.consecutive_error_count,
                    is_active=row.is_active,
                    updated_at=row.updated_at,
                )
                conferences.append(state)

            logger.info(f"Found {len(conferences)} conferences due for scan")
            return conferences

        except Exception as e:
            raise DeltaStoreError(f"Failed to get conferences due for scan: {e}") from e
