"""
ConBOT Monitoring Dashboard

Run this in a Databricks notebook to monitor system health.

Upload to Databricks:
    databricks workspace import scripts/monitoring_dashboard.py /Shared/conbot/monitoring --language PYTHON
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, sum as _sum, avg, max as _max, min as _min, date_format
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Spark
spark = SparkSession.builder.appName("ConBOT-Monitoring").getOrCreate()

print("="*80)
print("ConBOT Monitoring Dashboard")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)

# ============================================================================
# 1. CURRENT STATE OVERVIEW
# ============================================================================

print("\n" + "="*80)
print("1. CURRENT STATE OVERVIEW")
print("="*80 + "\n")

current_state = spark.sql("""
SELECT
    conference_id,
    conference_name,
    watch_mode,
    next_run_at,
    last_scan_at,
    DATEDIFF(current_timestamp(), last_scan_at) as days_since_scan,
    array_size(current_deadlines) as deadline_count,
    consecutive_no_change_count,
    CASE
        WHEN binary_hash IS NULL THEN 'Not Scanned'
        WHEN array_size(current_deadlines) > 0 THEN 'Has Deadlines'
        ELSE 'No Deadlines'
    END as status
FROM conbot.conferences_current
ORDER BY watch_mode DESC, next_run_at
""")

current_state.show(truncate=False)

# ============================================================================
# 2. WATCH MODE DISTRIBUTION
# ============================================================================

print("\n" + "="*80)
print("2. WATCH MODE DISTRIBUTION")
print("="*80 + "\n")

mode_distribution = spark.sql("""
SELECT
    watch_mode,
    COUNT(*) as conference_count,
    ROUND(AVG(consecutive_no_change_count), 1) as avg_no_change_count
FROM conbot.conferences_current
GROUP BY watch_mode
ORDER BY
    CASE watch_mode
        WHEN 'URGENT' THEN 1
        WHEN 'BIWEEKLY' THEN 2
        WHEN 'MONTHLY' THEN 3
    END
""")

mode_distribution.show()

# ============================================================================
# 3. DEADLINES FOUND
# ============================================================================

print("\n" + "="*80)
print("3. DEADLINES FOUND (ALL CONFERENCES)")
print("="*80 + "\n")

deadlines = spark.sql("""
SELECT
    conference_id,
    conference_name,
    deadline.date as deadline_date,
    deadline.type as deadline_type,
    deadline.confidence,
    DATEDIFF(deadline.date, current_date()) as days_until_deadline
FROM conbot.conferences_current
LATERAL VIEW explode(current_deadlines) t AS deadline
ORDER BY deadline.date
""")

if deadlines.count() > 0:
    deadlines.show(truncate=False)
else:
    print("No deadlines found yet.")

# ============================================================================
# 4. SCAN ACTIVITY (LAST 7 DAYS)
# ============================================================================

print("\n" + "="*80)
print("4. SCAN ACTIVITY (LAST 7 DAYS)")
print("="*80 + "\n")

seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

scan_activity = spark.sql(f"""
SELECT
    DATE(scan_timestamp) as scan_date,
    COUNT(*) as total_scans,
    SUM(CASE WHEN change_detected THEN 1 ELSE 0 END) as changes_detected,
    SUM(CASE WHEN array_size(deadlines_found) > 0 THEN 1 ELSE 0 END) as deadlines_found,
    SUM(CASE WHEN email_sent THEN 1 ELSE 0 END) as emails_sent,
    SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) as llm_calls,
    ROUND(AVG(scan_duration_seconds), 2) as avg_duration_sec
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{seven_days_ago}'
GROUP BY DATE(scan_timestamp)
ORDER BY scan_date DESC
""")

if scan_activity.count() > 0:
    scan_activity.show()
else:
    print("No scans in last 7 days.")

# ============================================================================
# 5. PER-CONFERENCE SCAN SUMMARY
# ============================================================================

print("\n" + "="*80)
print("5. PER-CONFERENCE SCAN SUMMARY (LAST 30 DAYS)")
print("="*80 + "\n")

thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

per_conference = spark.sql(f"""
SELECT
    conference_id,
    COUNT(*) as total_scans,
    SUM(CASE WHEN change_detected THEN 1 ELSE 0 END) as changes_detected,
    SUM(CASE WHEN array_size(deadlines_found) > 0 THEN 1 ELSE 0 END) as scans_with_deadlines,
    MAX(scan_timestamp) as last_scan,
    ROUND(AVG(scan_duration_seconds), 2) as avg_duration_sec
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{thirty_days_ago}'
GROUP BY conference_id
ORDER BY conference_id
""")

per_conference.show(truncate=False)

# ============================================================================
# 6. STATE TRANSITIONS (LAST 30 DAYS)
# ============================================================================

print("\n" + "="*80)
print("6. STATE TRANSITIONS (LAST 30 DAYS)")
print("="*80 + "\n")

transitions = spark.sql(f"""
SELECT
    conference_id,
    scan_timestamp,
    previous_watch_mode,
    new_watch_mode,
    transition_reason,
    change_type,
    array_size(deadlines_found) as deadlines_count
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{thirty_days_ago}'
  AND previous_watch_mode != new_watch_mode
ORDER BY scan_timestamp DESC
""")

if transitions.count() > 0:
    transitions.show(truncate=False)
else:
    print("No state transitions in last 30 days.")

# ============================================================================
# 7. CHANGE DETECTION BREAKDOWN
# ============================================================================

print("\n" + "="*80)
print("7. CHANGE DETECTION BREAKDOWN (LAST 30 DAYS)")
print("="*80 + "\n")

change_breakdown = spark.sql(f"""
SELECT
    change_type,
    COUNT(*) as count,
    ROUND(AVG(hamming_distance), 1) as avg_hamming_distance
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{thirty_days_ago}'
GROUP BY change_type
ORDER BY count DESC
""")

change_breakdown.show()

# ============================================================================
# 8. LLM API USAGE & COST ESTIMATE
# ============================================================================

print("\n" + "="*80)
print("8. LLM API USAGE & COST ESTIMATE (LAST 30 DAYS)")
print("="*80 + "\n")

llm_usage = spark.sql(f"""
SELECT
    COUNT(*) as total_scans,
    SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) as llm_calls,
    ROUND(100.0 * SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) / COUNT(*), 1) as llm_call_percentage
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{thirty_days_ago}'
""")

llm_usage.show()

llm_calls_count = llm_usage.collect()[0]["llm_calls"]
estimated_cost = llm_calls_count * 0.02  # $0.02 per call (rough estimate)

print(f"\nEstimated LLM cost (last 30 days): ${estimated_cost:.2f}")
print(f"Monthly projection: ${estimated_cost:.2f}")

# ============================================================================
# 9. EMAIL DELIVERY SUCCESS RATE
# ============================================================================

print("\n" + "="*80)
print("9. EMAIL DELIVERY SUCCESS RATE (LAST 30 DAYS)")
print("="*80 + "\n")

email_stats = spark.sql(f"""
SELECT
    COUNT(*) as total_scans,
    SUM(CASE WHEN email_sent THEN 1 ELSE 0 END) as emails_sent,
    ROUND(100.0 * SUM(CASE WHEN email_sent THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{thirty_days_ago}'
""")

email_stats.show()

# ============================================================================
# 10. RECENT ERRORS (IF ANY)
# ============================================================================

print("\n" + "="*80)
print("10. RECENT ERRORS (LAST 7 DAYS)")
print("="*80 + "\n")

errors = spark.sql(f"""
SELECT
    run_id,
    conference_id,
    started_at,
    status,
    error_details
FROM conbot.scan_history
WHERE started_at >= '{seven_days_ago}'
  AND status = 'failed'
ORDER BY started_at DESC
LIMIT 10
""")

if errors.count() > 0:
    errors.show(truncate=False)
    print("\n⚠️ WARNING: Errors detected! Review error_details above.")
else:
    print("✓ No errors in last 7 days.")

# ============================================================================
# 11. PERFORMANCE METRICS
# ============================================================================

print("\n" + "="*80)
print("11. PERFORMANCE METRICS (LAST 7 DAYS)")
print("="*80 + "\n")

performance = spark.sql(f"""
SELECT
    conference_id,
    COUNT(*) as scan_count,
    ROUND(AVG(scan_duration_seconds), 2) as avg_duration,
    ROUND(MIN(scan_duration_seconds), 2) as min_duration,
    ROUND(MAX(scan_duration_seconds), 2) as max_duration,
    MAX(CASE
        WHEN fetch_method = 'playwright' THEN 'Yes'
        ELSE 'No'
    END) as used_playwright
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{seven_days_ago}'
GROUP BY conference_id
ORDER BY avg_duration DESC
""")

performance.show(truncate=False)

# ============================================================================
# 12. ALERTS & RECOMMENDATIONS
# ============================================================================

print("\n" + "="*80)
print("12. ALERTS & RECOMMENDATIONS")
print("="*80 + "\n")

# Check for conferences not scanned recently
stale_conferences = spark.sql(f"""
SELECT conference_id, last_scan_at, DATEDIFF(current_timestamp(), last_scan_at) as days_stale
FROM conbot.conferences_current
WHERE last_scan_at IS NOT NULL
  AND DATEDIFF(current_timestamp(), last_scan_at) > 35
""")

if stale_conferences.count() > 0:
    print("⚠️ ALERT: Conferences not scanned in > 35 days:")
    stale_conferences.show()
else:
    print("✓ All conferences scanned recently")

# Check for conferences stuck in URGENT mode
urgent_conferences = spark.sql("""
SELECT conference_id, consecutive_no_change_count
FROM conbot.conferences_current
WHERE watch_mode = 'URGENT'
  AND consecutive_no_change_count > 10
""")

if urgent_conferences.count() > 0:
    print("\n⚠️ ALERT: Conferences stuck in URGENT mode (>10 no-change scans):")
    urgent_conferences.show()
    print("   Consider manually downgrading to BIWEEKLY if deadlines have passed.")
else:
    print("\n✓ No conferences stuck in URGENT mode")

# Check email delivery failures
email_failures = spark.sql(f"""
SELECT COUNT(*) as failure_count
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{seven_days_ago}'
  AND email_sent = false
""")

failure_count = email_failures.collect()[0]["failure_count"]
if failure_count > 5:
    print(f"\n⚠️ ALERT: {failure_count} email delivery failures in last 7 days")
    print("   Check AWS SES quota and sender verification")
else:
    print("\n✓ Email delivery healthy")

# ============================================================================
# DASHBOARD COMPLETE
# ============================================================================

print("\n" + "="*80)
print("Dashboard Complete")
print("="*80)
print(f"\nFor more details, query the following tables:")
print("  - conbot.conferences_current")
print("  - conbot.conferences_audit")
print("  - conbot.scan_history")
print("\nRefresh this dashboard daily to monitor system health.")
print("="*80 + "\n")
