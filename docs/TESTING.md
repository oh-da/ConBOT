# ConBOT Testing Guide

Guide for testing ConBOT before and after deployment.

## Table of Contents

1. [Local Testing (Before Deployment)](#local-testing-before-deployment)
2. [Databricks Testing (After Deployment)](#databricks-testing-after-deployment)
3. [Integration Testing](#integration-testing)
4. [Production Verification](#production-verification)

---

## Local Testing (Before Deployment)

### Prerequisites

```bash
# Install ConBOT with dev dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

### Run Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/unit/test_fingerprint.py -v
pytest tests/unit/test_dates.py -v
pytest tests/unit/test_state_transitions.py -v
pytest tests/unit/test_link_discovery.py -v

# Run integration tests
pytest tests/integration/ -v

# Run with coverage
pytest tests/ --cov=conbot --cov-report=html
```

**Expected Output:**
```
tests/unit/test_fingerprint.py::test_no_change_detected PASSED
tests/unit/test_fingerprint.py::test_binary_hash_change PASSED
tests/unit/test_dates.py::test_simple_date_extraction PASSED
...
============== 45 passed in 12.34s ==============
```

### Test Individual Components

#### 1. Test Fetcher

```python
from conbot.fetching.fetcher import Fetcher

with Fetcher() as fetcher:
    # Test static site
    html, method = fetcher.fetch("https://www.uitpsummit.org/")
    print(f"Fetched {len(html)} bytes using {method}")

    # Test JS-heavy site
    html, method = fetcher.fetch("https://www.trb.org/AnnualMeeting/AnnualMeeting.aspx")
    print(f"Fetched {len(html)} bytes using {method}")
```

#### 2. Test Content Extraction

```python
from conbot.extraction.content import ContentExtractor

extractor = ContentExtractor()

result = extractor.extract_all(
    html=html,
    url="https://example.com"
)

print(f"Main content: {len(result['main_content'])} chars")
print(f"Snippets: {len(result['relevant_snippets'])}")
print(f"Filtered content: {len(result['filtered_content'])} chars")
```

#### 3. Test Date Extraction

```python
from conbot.extraction.dates import DateExtractor

extractor = DateExtractor()

text = """
Important Dates:
- Abstract submission: March 15, 2026
- Full paper deadline: April 30, 2026
- Early registration: May 1, 2026
"""

deadlines = extractor.extract_deadlines(text, [])

for dl in deadlines:
    print(f"{dl.type}: {dl.date} (confidence: {dl.confidence})")
```

#### 4. Test Change Detection

```python
from conbot.detection.fingerprint import ChangeDetector

detector = ChangeDetector()

html1 = "<html><body><p>Original content</p></body></html>"
html2 = "<html><body><p>Updated content</p></body></html>"

fp1 = detector.generate_fingerprints(html1, html1)
fp2 = detector.generate_fingerprints(html2, html2)

changed, change_type, hamming = detector.detect_change(fp2, fp1)
print(f"Changed: {changed}, Type: {change_type}, Hamming: {hamming}")
```

#### 5. Test State Machine

```python
from conbot.state.transitions import StateTransitionEngine
from conbot.models.conference import WatchMode, ScanResult, ChangeType

engine = StateTransitionEngine()

# Simulate: MONTHLY + deadlines found → URGENT
scan_result = ScanResult(
    conference_id="test",
    url="https://test.com",
    scan_timestamp=datetime.now(),
    main_content="test",
    relevant_snippets=[],
    change_detected=True,
    change_type=ChangeType.FILTERED,
    hamming_distance=None,
    deadlines_found=[...],  # Add mock deadlines
    summary="Deadlines published",
    fetch_method="requests",
    scan_duration_seconds=1.0,
    llm_api_called=False
)

new_mode, reason = engine.determine_new_mode(WatchMode.MONTHLY, scan_result)
print(f"MONTHLY → {new_mode} (reason: {reason})")
```

---

## Databricks Testing (After Deployment)

### Test 1: Verify Tables Created

```python
# Run in Databricks notebook
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# Check database
spark.sql("SHOW DATABASES").show()

# Check tables
spark.sql("SHOW TABLES IN conbot").show()

# Expected tables:
# - conferences_current
# - conferences_audit
# - scan_history
```

### Test 2: Verify Secrets

```python
# In Databricks notebook
sender = dbutils.secrets.get("email-credentials", "sender-email")
recipient = dbutils.secrets.get("email-credentials", "recipient-email")

print(f"Sender: {sender}")
print(f"Recipient: {recipient}")

# Should not throw KeyError
```

### Test 3: Test SES Client

```python
import sys
sys.path.insert(0, '/dbfs/FileStore/wheels/conbot-1.0.0-py3-none-any.whl')

from conbot.notification.email_client import SESEmailClient

sender = dbutils.secrets.get("email-credentials", "sender-email")

client = SESEmailClient(sender_email=sender, aws_region="us-east-1")

# Verify sender
verified = client.verify_sender()
print(f"Sender verified: {verified}")

# Check quota
quota = client.get_send_quota()
print(f"Quota: {quota['sent_last_24_hours']}/{quota['max_24_hour_send']}")
```

### Test 4: Send Test Email

```python
import sys
sys.path.insert(0, '/dbfs/FileStore/wheels/conbot-1.0.0-py3-none-any.whl')

from conbot.main import ConferenceScanOrchestrator

orchestrator = ConferenceScanOrchestrator(
    config_path="/dbfs/conbot/config/conferences.yaml",
    recipient_email=dbutils.secrets.get("email-credentials", "recipient-email"),
    sender_email=dbutils.secrets.get("email-credentials", "sender-email")
)

# Send test email
success = orchestrator.email_formatter.send_test_email()

if success:
    print("✓ Test email sent! Check your inbox.")
else:
    print("✗ Test email failed. Check AWS SES configuration.")
```

### Test 5: Initialize Conferences

```python
count = orchestrator.initialize_conferences()
print(f"Initialized {count} conferences")

# Verify
spark.sql("SELECT conference_id, watch_mode, next_run_at FROM conbot.conferences_current").show()
```

### Test 6: Manual Scan (Single Conference)

```python
# Force scan of one conference
success = orchestrator.scan_single_conference("uitp_summit", force=True)

if success:
    print("✓ Manual scan completed")

    # Check audit log
    spark.sql("""
        SELECT
            conference_id,
            scan_timestamp,
            change_detected,
            array_size(deadlines_found) as deadline_count,
            email_sent
        FROM conbot.conferences_audit
        WHERE conference_id = 'uitp_summit'
        ORDER BY scan_timestamp DESC
        LIMIT 1
    """).show(truncate=False)
else:
    print("✗ Manual scan failed")
```

### Test 7: Full Daily Scan

```python
# Run full daily scan workflow
results = orchestrator.run_daily_scan()

print(f"Scanned: {results['scanned']}")
print(f"Succeeded: {results['succeeded']}")
print(f"Failed: {results['failed']}")

# Check audit log
spark.sql("""
    SELECT
        conference_id,
        change_detected,
        new_watch_mode,
        email_sent
    FROM conbot.conferences_audit
    WHERE scan_timestamp >= CURRENT_TIMESTAMP - INTERVAL 10 MINUTES
    ORDER BY scan_timestamp DESC
""").show()
```

---

## Integration Testing

### Scenario 1: First Scan (No Baseline)

**Objective**: Verify first scan creates fingerprints but doesn't trigger change alert.

```python
# Setup: Conference with no binary_hash
spark.sql("""
    UPDATE conbot.conferences_current
    SET binary_hash = NULL, filtered_hash = NULL, simhash_signature = NULL
    WHERE conference_id = 'test_conference'
""")

# Execute scan
orchestrator.scan_single_conference("test_conference", force=True)

# Verify
result = spark.sql("""
    SELECT binary_hash, filtered_hash, simhash_signature
    FROM conbot.conferences_current
    WHERE conference_id = 'test_conference'
""").collect()[0]

assert result.binary_hash is not None, "Binary hash should be set"
assert result.filtered_hash is not None, "Filtered hash should be set"
assert result.simhash_signature is not None, "SimHash signature should be set"

print("✓ First scan test passed")
```

### Scenario 2: No Change Detected

**Objective**: Scan same content twice, verify no change detected.

```python
# Scan twice in succession
orchestrator.scan_single_conference("uitp_summit", force=True)
orchestrator.scan_single_conference("uitp_summit", force=True)

# Check audit log
audit = spark.sql("""
    SELECT change_detected, change_type
    FROM conbot.conferences_audit
    WHERE conference_id = 'uitp_summit'
    ORDER BY scan_timestamp DESC
    LIMIT 1
""").collect()[0]

assert not audit.change_detected, "Should not detect change on identical content"
print("✓ No change test passed")
```

### Scenario 3: State Transition (MONTHLY → URGENT)

**Objective**: Simulate discovering deadlines, verify state transition.

```python
# Setup: Set to MONTHLY mode
spark.sql("""
    UPDATE conbot.conferences_current
    SET watch_mode = 'MONTHLY', current_deadlines = array()
    WHERE conference_id = 'test_conference'
""")

# Scan conference with deadlines (real or mock)
orchestrator.scan_single_conference("test_conference", force=True)

# Verify transition (if deadlines found)
current_state = spark.sql("""
    SELECT watch_mode, array_size(current_deadlines) as deadline_count
    FROM conbot.conferences_current
    WHERE conference_id = 'test_conference'
""").collect()[0]

if current_state.deadline_count > 0:
    assert current_state.watch_mode == "URGENT", "Should transition to URGENT"
    print("✓ State transition test passed")
else:
    print("⚠ No deadlines found, cannot test transition")
```

---

## Production Verification

### Daily Checklist (First Week)

Run these checks daily after deployment:

#### 1. Check Job Execution

```bash
# Via Databricks UI
# Navigate to: Workflows → ConBOT Daily Conference Scan → Runs
# Verify: Latest run shows "Succeeded"

# Via CLI
databricks runs list --job-id YOUR_JOB_ID --limit 5
```

#### 2. Check Email Delivery

- [ ] Received 6 emails today (one per conference)
- [ ] Emails are well-formatted
- [ ] Subject lines are correct
- [ ] Links in emails work

#### 3. Check Audit Log

```sql
-- Scans from last 24 hours
SELECT
    conference_id,
    scan_timestamp,
    change_detected,
    email_sent,
    scan_duration_seconds
FROM conbot.conferences_audit
WHERE scan_timestamp >= CURRENT_TIMESTAMP - INTERVAL 24 HOURS
ORDER BY scan_timestamp DESC;

-- Should show 6 scans (one per conference)
```

#### 4. Check for Errors

```sql
SELECT
    conference_id,
    started_at,
    status,
    error_details
FROM conbot.scan_history
WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL 24 HOURS
  AND status = 'failed';

-- Should return 0 rows
```

#### 5. Check LLM Usage

```sql
SELECT
    COUNT(*) as total_scans,
    SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) as llm_calls
FROM conbot.conferences_audit
WHERE scan_timestamp >= CURRENT_TIMESTAMP - INTERVAL 24 HOURS;
```

#### 6. Check SES Quota

```python
# In Databricks notebook
from conbot.notification.email_client import SESEmailClient

client = SESEmailClient(sender_email="conbot@yourdomain.com")
quota = client.get_send_quota()

print(f"Sent today: {quota['sent_last_24_hours']}/{quota['max_24_hour_send']}")
print(f"Rate limit: {quota['max_send_rate']}/sec")
```

### Weekly Report

After one week, generate summary:

```sql
-- Weekly summary
SELECT
    COUNT(DISTINCT DATE(scan_timestamp)) as days_active,
    COUNT(*) as total_scans,
    SUM(CASE WHEN change_detected THEN 1 ELSE 0 END) as changes_detected,
    SUM(CASE WHEN array_size(deadlines_found) > 0 THEN 1 ELSE 0 END) as deadlines_discovered,
    SUM(CASE WHEN email_sent THEN 1 ELSE 0 END) as emails_sent,
    ROUND(AVG(scan_duration_seconds), 2) as avg_scan_duration
FROM conbot.conferences_audit
WHERE scan_timestamp >= CURRENT_TIMESTAMP - INTERVAL 7 DAYS;
```

**Expected Values (Week 1):**
- `days_active`: 7
- `total_scans`: ~42 (6 conferences × 7 days)
- `changes_detected`: 0-6 (depends on conference updates)
- `emails_sent`: ~42 (100% delivery rate)
- `avg_scan_duration`: 5-30 seconds

### Performance Benchmarks

**Acceptable ranges:**

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Scan duration | <30s | 30-60s | >60s |
| Email delivery | 100% | >95% | <95% |
| LLM calls/day | 0-2 | 3-5 | >5 |
| Daily cost | <$5 | $5-10 | >$10 |
| Job success rate | 100% | >95% | <95% |

---

## Troubleshooting Test Failures

### Test fails: "Table not found"

**Solution**: Run table initialization script first.

### Test fails: "Secret not found"

**Solution**: Set up secret scopes:
```bash
databricks secrets create-scope --scope email-credentials
databricks secrets put --scope email-credentials --key sender-email
```

### Test fails: "Wheel not found"

**Solution**: Upload wheel to DBFS:
```bash
databricks fs cp dist/conbot-1.0.0-py3-none-any.whl dbfs:/FileStore/wheels/ --overwrite
```

### Test email not received

**Solutions**:
1. Check spam folder
2. Verify sender in AWS SES Console
3. Check SES is not in sandbox mode
4. Verify recipient email is correct in secrets

---

## Success Criteria

Testing is successful when:

- [ ] All unit tests pass (45/45)
- [ ] All integration tests pass
- [ ] Test email received
- [ ] Manual scan of each conference succeeds
- [ ] Daily workflow runs successfully for 3 consecutive days
- [ ] All 6 conferences scanned daily
- [ ] 100% email delivery rate
- [ ] No errors in scan_history table
- [ ] Audit log shows complete scan history

---

Last Updated: 2026-02-14
