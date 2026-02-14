# ConBOT Deployment Guide

Complete step-by-step guide for deploying ConBOT to Databricks on AWS.

## Prerequisites

### Required Access & Credentials

- [ ] Databricks workspace with admin access
- [ ] AWS account with SES enabled
- [ ] OpenAI API account (optional but recommended)
- [ ] Email addresses verified in AWS SES
- [ ] Databricks CLI installed locally
- [ ] Python 3.9+ installed locally

### AWS SES Setup

1. **Verify Sender Email**
   ```bash
   # Navigate to AWS SES Console → Email Addresses
   # Click "Verify a New Email Address"
   # Enter your sender email (e.g., conbot@yourdomain.com)
   # Check inbox and click verification link
   ```

2. **Request Production Access** (if needed)
   ```
   If your AWS SES is in sandbox mode (50,000 emails/day limit):
   - Navigate to SES → Account Dashboard → Request Production Access
   - Fill out the form (typical approval: 24 hours)
   - Sandbox mode is sufficient for testing (6 conferences = ~180 emails/month)
   ```

3. **Create IAM Role for Databricks**
   ```bash
   # Create IAM policy for SES send permissions
   # Policy JSON:
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "ses:SendEmail",
           "ses:SendRawEmail",
           "ses:GetSendQuota",
           "ses:GetIdentityVerificationAttributes"
         ],
         "Resource": "*"
       }
     ]
   }

   # Attach to Databricks instance profile
   # Note the ARN: arn:aws:iam::YOUR_ACCOUNT:instance-profile/databricks-conbot-role
   ```

### Databricks CLI Setup

1. **Install Databricks CLI**
   ```bash
   pip install databricks-cli
   ```

2. **Configure Authentication**
   ```bash
   databricks configure --token
   # Enter:
   # - Databricks Host: https://your-workspace.cloud.databricks.com
   # - Token: (generate from User Settings → Access Tokens)
   ```

3. **Verify Connection**
   ```bash
   databricks workspace ls /
   ```

---

## Step 1: Set Up Databricks Secrets

Databricks Secrets provide secure storage for API keys and credentials.

### Create Secret Scopes

```bash
# Create scope for email credentials
databricks secrets create-scope --scope email-credentials

# Create scope for LLM credentials
databricks secrets create-scope --scope llm-credentials
```

### Add Secrets

```bash
# Email configuration
databricks secrets put --scope email-credentials --key sender-email
# Enter: conbot@yourdomain.com

databricks secrets put --scope email-credentials --key recipient-email
# Enter: your-email@example.com

# OpenAI API key (optional)
databricks secrets put --scope llm-credentials --key openai-api-key
# Enter: sk-...your-api-key...

# AWS credentials (if not using instance profile)
databricks secrets put --scope email-credentials --key aws-access-key-id
# Enter: AKIA...

databricks secrets put --scope email-credentials --key aws-secret-access-key
# Enter: your-secret-key
```

### Verify Secrets

```bash
databricks secrets list --scope email-credentials
databricks secrets list --scope llm-credentials
```

**Expected Output:**
```
Scope: email-credentials
  - sender-email
  - recipient-email
  - aws-access-key-id (optional)
  - aws-secret-access-key (optional)

Scope: llm-credentials
  - openai-api-key
```

---

## Step 2: Build and Upload ConBOT Package

### Build Python Wheel

```bash
# From ConBOT project root
cd /path/to/ConBOT

# Install build dependencies
pip install build

# Build wheel
python -m build

# Verify wheel created
ls dist/
# Should show: conbot-1.0.0-py3-none-any.whl
```

### Upload to Databricks

```bash
# Create directory for wheels
databricks fs mkdirs dbfs:/FileStore/wheels

# Upload wheel
databricks fs cp dist/conbot-1.0.0-py3-none-any.whl dbfs:/FileStore/wheels/conbot-1.0.0-py3-none-any.whl --overwrite

# Verify upload
databricks fs ls dbfs:/FileStore/wheels/
```

### Upload Configuration

```bash
# Create config directory
databricks fs mkdirs dbfs:/conbot/config

# Upload conferences.yaml
databricks fs cp config/conferences.yaml dbfs:/conbot/config/conferences.yaml --overwrite

# Verify upload
databricks fs cat dbfs:/conbot/config/conferences.yaml | head -20
```

---

## Step 3: Create Delta Tables

### Upload Initialization Script

```bash
# Create Databricks notebooks directory
databricks workspace mkdirs /Shared/conbot

# Upload as notebook
databricks workspace import databricks/init_scripts/setup_tables.py /Shared/conbot/setup_tables --language PYTHON
```

### Run Initialization

**Option A: Via Databricks UI**
1. Navigate to Workspace → Shared → conbot → setup_tables
2. Attach to cluster (or create new cluster: Runtime 13.3+, i3.xlarge)
3. Run all cells
4. Verify output shows 3 tables created

**Option B: Via CLI**
```bash
# Create temporary cluster for setup
databricks clusters create --json '{
  "cluster_name": "conbot-setup",
  "spark_version": "13.3.x-scala2.12",
  "node_type_id": "i3.xlarge",
  "num_workers": 0,
  "autotermination_minutes": 15
}'

# Note the cluster_id from output, then run:
databricks clusters get --cluster-id YOUR_CLUSTER_ID

# Wait for cluster to start (status: RUNNING)
# Then execute setup script
databricks workspace export /Shared/conbot/setup_tables --format SOURCE | python
```

### Verify Tables Created

```bash
# Check tables exist
databricks workspace export /Shared/conbot/verify_tables --format SOURCE
```

Create verification notebook:
```python
# verify_tables.py
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("VerifyTables").getOrCreate()

# Check database
databases = spark.sql("SHOW DATABASES").collect()
print("Databases:", [db.databaseName for db in databases])

# Check tables
tables = spark.sql("SHOW TABLES IN conbot").collect()
print("Tables in conbot:")
for table in tables:
    print(f"  - {table.tableName}")

# Check schemas
for table_name in ["conferences_current", "conferences_audit", "scan_history"]:
    print(f"\n{table_name} schema:")
    spark.sql(f"DESCRIBE conbot.{table_name}").show(truncate=False)
```

**Expected Output:**
```
Databases: ['conbot', 'default']
Tables in conbot:
  - conferences_audit
  - conferences_current
  - scan_history
```

---

## Step 4: Initialize Conference States

### Manual Initialization

```bash
# Create initialization notebook
cat > init_conferences.py << 'EOF'
import sys
sys.path.insert(0, '/dbfs/FileStore/wheels/conbot-1.0.0-py3-none-any.whl')

from conbot.main import ConferenceScanOrchestrator

# Initialize orchestrator
orchestrator = ConferenceScanOrchestrator(
    config_path="/dbfs/conbot/config/conferences.yaml",
    recipient_email=dbutils.secrets.get("email-credentials", "recipient-email"),
    sender_email=dbutils.secrets.get("email-credentials", "sender-email")
)

# Initialize conferences from config
count = orchestrator.initialize_conferences()
print(f"Initialized {count} conferences in MONTHLY mode")

# Verify
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
spark.sql("SELECT conference_id, watch_mode, next_run_at FROM conbot.conferences_current").show()
EOF

# Upload and run
databricks workspace import init_conferences.py /Shared/conbot/init_conferences --language PYTHON
```

### Verify Initialization

Query Delta table:
```python
spark.sql("""
SELECT
    conference_id,
    conference_name,
    watch_mode,
    next_run_at,
    binary_hash IS NULL as is_first_scan
FROM conbot.conferences_current
ORDER BY conference_id
""").show(truncate=False)
```

**Expected Output:**
```
+----------------+---------------------------+----------+-------------------+--------------+
|conference_id   |conference_name            |watch_mode|next_run_at        |is_first_scan|
+----------------+---------------------------+----------+-------------------+--------------+
|itdp            |ITDP Conference            |MONTHLY   |2026-02-14 09:00:00|true         |
|itf_summit      |ITF Transport Summit       |MONTHLY   |2026-02-14 09:00:00|true         |
|its_world       |ITS World Congress         |MONTHLY   |2026-02-14 09:00:00|true         |
|tra_conference  |TRA Conference             |MONTHLY   |2026-02-14 09:00:00|true         |
|trb_annual      |TRB Annual Meeting         |MONTHLY   |2026-02-14 09:00:00|true         |
|uitp_summit     |UITP Global Summit         |MONTHLY   |2026-02-14 09:00:00|true         |
+----------------+---------------------------+----------+-------------------+--------------+
```

---

## Step 5: Test Email Configuration

### Send Test Email

```python
# test_email.py
import sys
sys.path.insert(0, '/dbfs/FileStore/wheels/conbot-1.0.0-py3-none-any.whl')

from conbot.notification.email_client import SESEmailClient
from conbot.notification.formatter import EmailFormatter

# Initialize SES client
sender = dbutils.secrets.get("email-credentials", "sender-email")
recipient = dbutils.secrets.get("email-credentials", "recipient-email")

ses_client = SESEmailClient(
    sender_email=sender,
    aws_region="us-east-1"
)

# Verify sender
if ses_client.verify_sender():
    print(f"✓ Sender verified: {sender}")
else:
    print(f"✗ Sender NOT verified: {sender}")
    print("Please verify sender in AWS SES Console")

# Get quota
quota = ses_client.get_send_quota()
print(f"SES Quota: {quota['sent_last_24_hours']}/{quota['max_24_hour_send']} (rate: {quota['max_send_rate']}/sec)")

# Send test email
formatter = EmailFormatter(ses_client=ses_client, recipient_email=recipient)
success = formatter.send_test_email()

if success:
    print(f"✓ Test email sent to {recipient}")
    print("Check your inbox!")
else:
    print("✗ Test email failed")
```

### Upload and Run

```bash
databricks workspace import test_email.py /Shared/conbot/test_email --language PYTHON
# Run in Databricks UI, check email inbox
```

---

## Step 6: Manual Test Scans

Before enabling the daily workflow, manually test each conference.

### Create Test Scan Notebook

```python
# manual_scan.py
import sys
sys.path.insert(0, '/dbfs/FileStore/wheels/conbot-1.0.0-py3-none-any.whl')

from conbot.main import ConferenceScanOrchestrator
import logging

logging.basicConfig(level=logging.INFO)

# Initialize orchestrator
orchestrator = ConferenceScanOrchestrator(
    config_path="/dbfs/conbot/config/conferences.yaml",
    recipient_email=dbutils.secrets.get("email-credentials", "recipient-email"),
    sender_email=dbutils.secrets.get("email-credentials", "sender-email"),
    aws_region="us-east-1"
)

# List of conferences to test
test_conferences = [
    "uitp_summit",
    "trb_annual",
    "itf_summit",
    "tra_conference",
    "its_world",
    "itdp"
]

# Scan each conference
results = {}
for conf_id in test_conferences:
    print(f"\n{'='*80}")
    print(f"Scanning: {conf_id}")
    print('='*80)

    success = orchestrator.scan_single_conference(conf_id, force=True)
    results[conf_id] = "✓ SUCCESS" if success else "✗ FAILED"

    print(f"Result: {results[conf_id]}")

# Summary
print(f"\n{'='*80}")
print("SCAN SUMMARY")
print('='*80)
for conf_id, result in results.items():
    print(f"{conf_id:20} {result}")
```

### Run Test Scans

```bash
databricks workspace import manual_scan.py /Shared/conbot/manual_scan --language PYTHON
# Run in UI, monitor output
```

### Verify Results

```python
# Check audit log
spark.sql("""
SELECT
    conference_id,
    scan_timestamp,
    change_detected,
    change_type,
    new_watch_mode,
    email_sent,
    scan_duration_seconds
FROM conbot.conferences_audit
ORDER BY scan_timestamp DESC
LIMIT 10
""").show(truncate=False)

# Check updated states
spark.sql("""
SELECT
    conference_id,
    watch_mode,
    last_scan_at,
    binary_hash IS NOT NULL as has_baseline,
    array_size(current_deadlines) as deadline_count
FROM conbot.conferences_current
ORDER BY conference_id
""").show(truncate=False)
```

---

## Step 7: Deploy Databricks Workflow

### Update Workflow Configuration

Edit `databricks/workflows/daily_scan.yaml`:

1. **Update email notification**:
   ```yaml
   email_notifications:
     on_failure:
       - "your-actual-email@example.com"  # Replace!
   ```

2. **Update IAM instance profile**:
   ```yaml
   aws_attributes:
     instance_profile_arn: "arn:aws:iam::YOUR_ACCOUNT_ID:instance-profile/databricks-conbot-role"
   ```

3. **Update access control**:
   ```yaml
   access_control_list:
     - user_name: "your-email@example.com"
       permission_level: "IS_OWNER"
   ```

### Create Workflow

```bash
# Create job
databricks jobs create --json-file databricks/workflows/daily_scan.yaml

# Note the job_id from output (e.g., 12345)
```

### Verify Workflow Created

```bash
# List jobs
databricks jobs list | grep "ConBOT"

# Get job details
databricks jobs get --job-id JOB_ID
```

### Run Manual Test

```bash
# Trigger one-time run
databricks jobs run-now --job-id JOB_ID

# Get run ID from output, then monitor
databricks runs get --run-id RUN_ID

# View output
databricks runs get-output --run-id RUN_ID
```

---

## Step 8: Enable Daily Schedule

### Verify Schedule

```bash
databricks jobs get --job-id JOB_ID | jq '.settings.schedule'
```

**Expected Output:**
```json
{
  "quartz_cron_expression": "0 0 9 * * ?",
  "timezone_id": "UTC",
  "pause_status": "UNPAUSED"
}
```

### Monitor First Week

**Daily Checklist:**
1. Check email for notifications (6 conferences = 6 emails/day)
2. Verify job runs in Databricks UI (Workflows → ConBOT Daily Conference Scan)
3. Query audit log for errors
4. Check SES send quota

**Audit Log Query:**
```python
from pyspark.sql.functions import col, count, sum as _sum, avg, max as _max
from datetime import datetime, timedelta

# Last 7 days summary
seven_days_ago = datetime.now() - timedelta(days=7)

spark.sql(f"""
SELECT
    DATE(scan_timestamp) as scan_date,
    COUNT(*) as total_scans,
    SUM(CASE WHEN change_detected THEN 1 ELSE 0 END) as changes_detected,
    SUM(CASE WHEN email_sent THEN 1 ELSE 0 END) as emails_sent,
    SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) as llm_calls,
    AVG(scan_duration_seconds) as avg_duration
FROM conbot.conferences_audit
WHERE scan_timestamp >= '{seven_days_ago.strftime('%Y-%m-%d')}'
GROUP BY DATE(scan_timestamp)
ORDER BY scan_date DESC
""").show()
```

---

## Step 9: Tune Thresholds (After First Week)

Based on monitoring, you may need to adjust:

### SimHash Threshold

If too many false positives (spurious change alerts):
```python
# Increase threshold in main.py or pass via CLI
orchestrator = ConferenceScanOrchestrator(
    ...,
    simhash_threshold=7  # Default: 5, try 7-10 for less sensitivity
)
```

### Date Validation Range

If valid deadlines are being rejected:
```python
# In extraction/dates.py, adjust max_days
self.max_days_in_future = 730  # Default, increase if needed for far-future conferences
```

### LLM Cost Limit

If hitting $10/month limit:
```python
# In llm/client.py
self.monthly_limit = 20.0  # Increase from $10
```

---

## Troubleshooting

### Email Not Sending

**Check:**
1. Sender verified in AWS SES: `databricks workspace import verify_ses.py`
2. IAM role has SES permissions
3. Recipient email not bouncing
4. SES not in sandbox mode (for non-verified recipients)

**Debug:**
```python
ses_client.verify_sender()  # Should return True
quota = ses_client.get_send_quota()
print(quota)  # Check remaining quota
```

### Job Failing

**Check Databricks job logs:**
```bash
databricks runs get --run-id RUN_ID
databricks runs get-output --run-id RUN_ID
```

**Common issues:**
- Wheel not found: Re-upload wheel
- Import errors: Check Python version (must be 3.9+)
- Playwright timeout: Some conferences may need longer wait

### No Changes Detected

**Normal for first month** - conferences may not update frequently.

**Verify change detection works:**
```python
# Manually edit a conference website URL in Delta table to test
spark.sql("""
UPDATE conbot.conferences_current
SET binary_hash = 'old_hash_123'
WHERE conference_id = 'uitp_summit'
""")

# Run manual scan - should detect change
orchestrator.scan_single_conference("uitp_summit", force=True)
```

---

## Rollback Plan

If deployment fails:

1. **Pause workflow**:
   ```bash
   databricks jobs update --job-id JOB_ID --json '{"schedule": {"pause_status": "PAUSED"}}'
   ```

2. **Delete tables**:
   ```python
   spark.sql("DROP DATABASE conbot CASCADE")
   ```

3. **Remove secrets**:
   ```bash
   databricks secrets delete-scope --scope email-credentials
   databricks secrets delete-scope --scope llm-credentials
   ```

4. **Delete job**:
   ```bash
   databricks jobs delete --job-id JOB_ID
   ```

---

## Success Criteria

Deployment is successful when:

- [x] All 6 conferences initialized in Delta table
- [x] First manual scan completes for each conference
- [x] Test email received successfully
- [x] Daily workflow runs without errors for 3 consecutive days
- [x] Email received after each daily run (6 per day)
- [x] Audit log shows all scans tracked
- [x] No LLM errors (or graceful fallback)
- [x] SES quota not exceeded

---

## Next Steps

After successful deployment:

1. **Monitor for 1 week**: Check emails, logs, costs daily
2. **Tune thresholds**: Adjust SimHash, date ranges if needed
3. **Set up alerting**: Databricks job failure notifications
4. **Document learnings**: Update this guide with any issues encountered
5. **Plan expansion**: Add more conferences as needed

---

## Cost Monitoring

**Expected Monthly Costs:**
- Databricks compute: $30-100 (depends on spot vs on-demand)
- AWS SES: $0.02 (well within free tier)
- OpenAI LLM: $0.50-3.60 (only called on changes)
- Total: ~$30-105/month

**Track costs:**
- Databricks: Account Console → Usage → Cost Analysis
- AWS SES: CloudWatch → Metrics → SES
- OpenAI: https://platform.openai.com/usage

---

Last Updated: 2026-02-14
