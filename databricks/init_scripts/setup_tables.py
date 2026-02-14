"""
Initialize Delta tables for ConBOT.

Run this script once during initial deployment to create the Delta tables.

Usage (Databricks notebook):
    %run /path/to/setup_tables
"""

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    TimestampType,
    IntegerType,
    FloatType,
    BooleanType,
    ArrayType,
    DoubleType
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_conferences_current_table(spark: SparkSession, table_path: str):
    """
    Create conferences_current Delta table.

    Stores current state of each conference (Type-2 SCD).
    """
    logger.info(f"Creating conferences_current table at {table_path}")

    # Define schema
    deadline_schema = StructType([
        StructField("date", StringType(), False),  # ISO format: YYYY-MM-DD
        StructField("type", StringType(), False),
        StructField("confidence", FloatType(), False),
        StructField("source_text", StringType(), False)
    ])

    tracked_link_schema = StructType([
        StructField("url", StringType(), False),
        StructField("score", FloatType(), False),
        StructField("first_seen", TimestampType(), False)
    ])

    schema = StructType([
        StructField("conference_id", StringType(), False),
        StructField("conference_name", StringType(), False),
        StructField("url", StringType(), False),
        StructField("watch_mode", StringType(), False),
        StructField("next_run_at", TimestampType(), False),
        StructField("last_scan_at", TimestampType(), True),
        StructField("binary_hash", StringType(), True),
        StructField("filtered_hash", StringType(), True),
        StructField("simhash_signature", StringType(), True),
        StructField("current_deadlines", ArrayType(deadline_schema), False),
        StructField("current_summary", StringType(), True),
        StructField("tracked_links", ArrayType(tracked_link_schema), False),
        StructField("consecutive_no_change_count", IntegerType(), False),
        StructField("updated_at", TimestampType(), False)
    ])

    # Create empty DataFrame
    empty_df = spark.createDataFrame([], schema)

    # Write as Delta table
    empty_df.write.format("delta").mode("overwrite").save(table_path)

    # Create table in metastore
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS conbot.conferences_current
        USING DELTA
        LOCATION '{table_path}'
    """)

    logger.info("conferences_current table created successfully")


def create_conferences_audit_table(spark: SparkSession, table_path: str):
    """
    Create conferences_audit Delta table.

    Append-only audit trail of all scans.
    """
    logger.info(f"Creating conferences_audit table at {table_path}")

    deadline_schema = StructType([
        StructField("date", StringType(), False),
        StructField("type", StringType(), False),
        StructField("confidence", FloatType(), False),
        StructField("source_text", StringType(), False)
    ])

    schema = StructType([
        StructField("audit_id", StringType(), False),
        StructField("conference_id", StringType(), False),
        StructField("scan_timestamp", TimestampType(), False),
        StructField("change_detected", BooleanType(), False),
        StructField("change_type", StringType(), False),
        StructField("hamming_distance", IntegerType(), True),
        StructField("deadlines_found", ArrayType(deadline_schema), False),
        StructField("summary", StringType(), True),
        StructField("previous_watch_mode", StringType(), False),
        StructField("new_watch_mode", StringType(), False),
        StructField("transition_reason", StringType(), False),
        StructField("scan_duration_seconds", FloatType(), False),
        StructField("llm_api_called", BooleanType(), False),
        StructField("email_sent", BooleanType(), False)
    ])

    empty_df = spark.createDataFrame([], schema)

    # Write as Delta table with partitioning by conference_id
    empty_df.write.format("delta").mode("overwrite").partitionBy("conference_id").save(table_path)

    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS conbot.conferences_audit
        USING DELTA
        LOCATION '{table_path}'
    """)

    logger.info("conferences_audit table created successfully")


def create_scan_history_table(spark: SparkSession, table_path: str):
    """
    Create scan_history Delta table.

    Performance and error tracking for each scan.
    """
    logger.info(f"Creating scan_history table at {table_path}")

    schema = StructType([
        StructField("run_id", StringType(), False),
        StructField("conference_id", StringType(), False),
        StructField("url", StringType(), False),
        StructField("started_at", TimestampType(), False),
        StructField("completed_at", TimestampType(), True),
        StructField("status", StringType(), False),  # success, failed, timeout
        StructField("fetch_method", StringType(), True),  # requests, playwright
        StructField("fetch_duration_ms", IntegerType(), True),
        StructField("change_detected", BooleanType(), True),
        StructField("deadlines_count", IntegerType(), True),
        StructField("email_type", StringType(), True),
        StructField("error_details", StringType(), True)
    ])

    empty_df = spark.createDataFrame([], schema)

    # Write as Delta table with partitioning by date
    empty_df.write.format("delta").mode("overwrite").save(table_path)

    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS conbot.scan_history
        USING DELTA
        LOCATION '{table_path}'
    """)

    logger.info("scan_history table created successfully")


def setup_database(spark: SparkSession, database_name: str = "conbot"):
    """
    Create ConBOT database if it doesn't exist.
    """
    logger.info(f"Creating database: {database_name}")

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    spark.sql(f"USE {database_name}")

    logger.info(f"Database {database_name} created/selected")


def main():
    """
    Main initialization function.

    Creates database and all three Delta tables.
    """
    logger.info("=" * 80)
    logger.info("ConBOT Delta Table Initialization")
    logger.info("=" * 80)

    # Get Spark session
    spark = SparkSession.builder.appName("ConBOT-Setup").getOrCreate()

    # Base path for Delta tables (update based on your environment)
    base_path = "dbfs:/conbot/delta"

    # Create database
    setup_database(spark, "conbot")

    # Create tables
    create_conferences_current_table(
        spark,
        f"{base_path}/conferences_current"
    )

    create_conferences_audit_table(
        spark,
        f"{base_path}/conferences_audit"
    )

    create_scan_history_table(
        spark,
        f"{base_path}/scan_history"
    )

    # Show created tables
    logger.info("=" * 80)
    logger.info("Listing created tables:")
    spark.sql("SHOW TABLES IN conbot").show()

    # Show table details
    for table_name in ["conferences_current", "conferences_audit", "scan_history"]:
        logger.info(f"\n--- {table_name} schema ---")
        spark.sql(f"DESCRIBE conbot.{table_name}").show(truncate=False)

    logger.info("=" * 80)
    logger.info("Delta table initialization complete!")
    logger.info("=" * 80)
    logger.info("Next steps:")
    logger.info("1. Upload conferences.yaml to DBFS: /dbfs/conbot/config/")
    logger.info("2. Build and upload ConBOT wheel")
    logger.info("3. Run: python -m conbot.main --mode=initialize")
    logger.info("4. Deploy Databricks workflow: databricks/workflows/daily_scan.yaml")


if __name__ == "__main__":
    main()


# For Databricks notebook usage:
# Uncomment the line below to run automatically
# main()
