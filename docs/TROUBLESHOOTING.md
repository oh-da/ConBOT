# ConBOT Troubleshooting Guide

Common issues and solutions for ConBOT deployment and operation.

## Table of Contents

1. [Deployment Issues](#deployment-issues)
2. [Email Issues](#email-issues)
3. [Scanning Issues](#scanning-issues)
4. [Performance Issues](#performance-issues)
5. [Data Issues](#data-issues)
6. [LLM Issues](#llm-issues)

---

## Deployment Issues

### Issue: `databricks` command not found

**Symptoms:**
```bash
$ databricks --version
bash: databricks: command not found
```

**Solution:**
```bash
# Install Databricks CLI
pip install databricks-cli

# Verify installation
databricks --version
```

### Issue: Databricks CLI not configured

**Symptoms:**
```bash
$ databricks workspace ls /
Error: INVALID_CONFIGURATION_FILE: Could not parse configuration file
```

**Solution:**
```bash
# Configure with access token
databricks configure --token

# Enter workspace URL: https://your-workspace.cloud.databricks.com
# Generate token: User Settings → Access Tokens → Generate New Token

# Test configuration
databricks workspace ls /
```

### Issue: Wheel build fails

**Symptoms:**
```bash
$ python -m build
ERROR: Could not find a version that satisfies the requirement...
```

**Solution:**
```bash
# Ensure Python 3.9+
python --version

# Upgrade pip and build tools
pip install --upgrade pip build setuptools wheel

# Check pyproject.toml exists
ls pyproject.toml

# Rebuild
python -m build
```

### Issue: Wheel upload fails

**Symptoms:**
```bash
$ databricks fs cp dist/conbot-1.0.0-py3-none-any.whl dbfs:/FileStore/wheels/
Error: PERMISSION_DENIED
```

**Solution:**
```bash
# Check workspace permissions
# You need CAN_MANAGE permissions on the workspace

# Try creating directory first
databricks fs mkdirs dbfs:/FileStore/wheels/

# Retry upload
databricks fs cp dist/conbot-1.0.0-py3-none-any.whl dbfs:/FileStore/wheels/ --overwrite
```

---

## Email Issues

### Issue: Emails not sending

**Symptoms:**
- No emails received after scans
- Log shows `SMTP authentication failed`, `SMTP error`, or `Email send failed`
- Audit log shows `email_sent = false`

**Debug Steps:**

1. **Send a test email**
   ```bash
   conbot test-email -r your@email.com
   ```

2. **Check the connection and login**
   ```python
   from conbot.notification.email_client import SMTPEmailClient

   print(SMTPEmailClient.from_env().verify_connection())
   ```

3. **Check the variables are set**: `SMTP_USERNAME`, `SMTP_PASSWORD`
   (and `SMTP_HOST` / `SMTP_PORT` if not Gmail). In GitHub Actions these are
   repository secrets / variables.

**Common Causes:**

- **Authentication failed**: Gmail needs an app password, not your account password
- **Wrong port**: 587 = STARTTLS, 465 = implicit TLS
- **Provider limits**: Gmail allows roughly 500 messages per day
- **Blocked outbound SMTP**: some networks block ports 25/465/587

### Issue: Emails go to spam

**Solution:**

- Send from an address your SMTP provider is authorised for (set `SENDER_EMAIL`
  to your own address, not an arbitrary one)
- If you use your own domain, set up SPF, DKIM and DMARC with your SMTP provider
- Mark the first message "Not spam" in your mail client

---

## Scanning Issues

### Issue: Scans timing out

**Symptoms:**
```
Error: Request timeout after 120 seconds
```

**Solution:**

1. **Increase timeout in Fetcher**:
   ```python
   # In main.py
   fetcher = Fetcher(timeout=180)  # Default: 120
   ```

2. **Force Playwright** for JS-heavy sites:
   ```python
   html, method = fetcher.fetch(url, force_playwright=True)
   ```

3. **Check network connectivity** from Databricks:
   ```python
   import requests
   response = requests.get("https://conference-url.com", timeout=30)
   print(response.status_code)
   ```

### Issue: No changes detected (false negatives)

**Symptoms:**
- Conference website clearly changed, but ConBOT reports "NO_CHANGE"

**Debug:**

1. **Check fingerprints**:
   ```sql
   SELECT
       conference_id,
       binary_hash,
       filtered_hash,
       simhash_signature
   FROM conbot.conferences_current
   WHERE conference_id = 'uitp_summit';
   ```

2. **Force manual scan** to regenerate fingerprints:
   ```bash
   python -m conbot.main --mode=manual --conference-id=uitp_summit --force
   ```

3. **Lower SimHash threshold** if semantic changes missed:
   ```python
   # In main.py
   orchestrator = ConferenceScanOrchestrator(
       ...,
       simhash_threshold=3  # Default: 5, lower = more sensitive
   )
   ```

### Issue: False positives (spurious change alerts)

**Symptoms:**
- Frequent "Website Updated" emails when content hasn't changed
- Changes triggered by dynamic elements (ads, timestamps)

**Solution:**

1. **Increase SimHash threshold**:
   ```python
   simhash_threshold=7  # Default: 5, higher = less sensitive
   ```

2. **Check filtered content extraction**:
   ```python
   from conbot.extraction.content import ContentExtractor

   extractor = ContentExtractor()
   result = extractor.extract_all(html, url)

   # Filtered content should exclude nav/footer/ads
   print(len(result['filtered_content']))
   ```

3. **Increase consecutive_no_change_count** tolerance before alert

### Issue: Deadlines not extracted

**Symptoms:**
- Conference has published dates, but `deadlines_found = []`

**Debug:**

1. **Check date extraction manually**:
   ```python
   from conbot.extraction.dates import DateExtractor

   extractor = DateExtractor()
   text = "Abstract deadline: March 15, 2026"
   deadlines = extractor.extract_deadlines(text, [])
   print(deadlines)
   ```

2. **Check date format support**:
   ```python
   # Supported formats:
   # - "March 15, 2026"
   # - "15 March 2026"
   # - "2026-03-15"
   # - "03/15/2026"
   # - "15.03.2026"
   ```

3. **Check temporal validation**:
   ```python
   # Dates must be:
   # - In future (>= today)
   # - Within 730 days of today
   # - Not in footer/copyright context
   ```

4. **Add custom keywords** in `config/conferences.yaml`:
   ```yaml
   cfp_keywords:
     - submission deadline
     - call for papers
     - abstract due
   ```

---

## Performance Issues

### Issue: Scans are slow (>60 seconds)

**Debug:**

1. **Check scan durations**:
   ```sql
   SELECT
       conference_id,
       AVG(scan_duration_seconds) as avg_duration,
       MAX(scan_duration_seconds) as max_duration
   FROM conbot.conferences_audit
   GROUP BY conference_id
   ORDER BY avg_duration DESC;
   ```

2. **Check fetch method**:
   ```sql
   SELECT
       conference_id,
       fetch_method,
       COUNT(*) as count
   FROM conbot.conferences_audit
   GROUP BY conference_id, fetch_method;
   ```

**Solutions:**

- **Playwright is slow**: If `fetch_method = 'playwright'` for all scans, site may be JS-heavy
  - Increase `timeout` for Playwright
  - Check if site can be fetched with `requests` instead

- **Network latency**: Databricks cluster may be far from conference servers
  - Consider regional cluster placement

- **Large HTML**: Some conference sites are massive
  - Normal, just ensure timeout is sufficient

### Issue: High LLM costs

**Symptoms:**
- OpenAI bill > $10/month
- Many `llm_api_called = true` in audit log

**Debug:**

```sql
SELECT
    COUNT(*) as total_scans,
    SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) as llm_calls,
    100.0 * SUM(CASE WHEN llm_api_called THEN 1 ELSE 0 END) / COUNT(*) as llm_call_percentage
FROM conbot.conferences_audit
WHERE scan_timestamp >= CURRENT_DATE - INTERVAL 30 DAYS;
```

**Solutions:**

1. **Verify caching is working**:
   ```python
   # Check cache hit rate in logs
   # Should see: "Cache hit for ..."
   ```

2. **Increase monthly limit** (if justified):
   ```python
   # In llm/client.py
   self.monthly_limit = 20.0  # Increase from $10
   ```

3. **Reduce change sensitivity** to call LLM less often:
   ```python
   simhash_threshold=7  # More tolerant = fewer changes = fewer LLM calls
   ```

---

## Data Issues

### Issue: Delta tables not found

**Symptoms:**
```
AnalysisException: Table or view not found: conbot.conferences_current
```

**Solution:**

1. **Check database exists**:
   ```python
   spark.sql("SHOW DATABASES").show()
   ```

2. **Create database**:
   ```python
   spark.sql("CREATE DATABASE IF NOT EXISTS conbot")
   ```

3. **Run initialization script**:
   ```bash
   # Navigate to Databricks UI → /Shared/conbot/setup_tables
   # Run all cells
   ```

### Issue: Conference state not initialized

**Symptoms:**
```sql
SELECT * FROM conbot.conferences_current;
-- Returns 0 rows
```

**Solution:**

```bash
python -m conbot.main --mode=initialize --config=/dbfs/conbot/config/conferences.yaml
```

### Issue: Audit log shows errors

**Symptoms:**
```sql
SELECT * FROM conbot.scan_history WHERE status = 'failed';
-- Returns error rows
```

**Debug:**

```sql
SELECT
    conference_id,
    started_at,
    error_details
FROM conbot.scan_history
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 10;
```

Review `error_details` for specific errors.

---

## LLM Issues

### Issue: LLM API key invalid

**Symptoms:**
```
OpenAI API error: Incorrect API key provided
```

**Solution:**

1. **Verify API key**:
   ```bash
   databricks secrets list --scope llm-credentials
   # Should show: openai-api-key
   ```

2. **Update API key**:
   ```bash
   databricks secrets put --scope llm-credentials --key openai-api-key
   # Enter valid key: sk-...
   ```

3. **Test API key**:
   ```python
   import openai
   openai.api_key = "sk-..."

   response = openai.chat.completions.create(
       model="gpt-4o-mini",
       messages=[{"role": "user", "content": "Test"}],
       max_tokens=10
   )
   print(response.choices[0].message.content)
   ```

### Issue: LLM quota exceeded

**Symptoms:**
```
OpenAI API error: You exceeded your current quota
```

**Solution:**

1. **Check OpenAI usage**: https://platform.openai.com/usage

2. **Add payment method**: OpenAI Console → Billing

3. **Increase quota**: OpenAI Console → Limits

4. **OR disable LLM** (optional):
   ```python
   # In main.py
   self.llm_client = None  # Disable LLM, graceful fallback
   ```

### Issue: LLM responses are poor quality

**Symptoms:**
- Summaries are vague or incorrect
- Classification is wrong

**Solution:**

1. **Check prompts** in `llm/prompts.py`:
   - Ensure keywords are relevant
   - Add more context to prompts

2. **Try different model**:
   ```python
   # In llm/client.py
   self.model = "gpt-4o"  # Upgrade from gpt-4o-mini
   ```

3. **Increase temperature** for more creative summaries:
   ```python
   temperature=0.5  # Default: 0.3
   ```

---

## Getting Help

If you encounter issues not covered here:

1. **Check logs**:
   - Databricks job logs: Workflows → Job → Runs → View Logs
   - Audit log: `SELECT * FROM conbot.conferences_audit ORDER BY scan_timestamp DESC LIMIT 20`

2. **Run monitoring dashboard**:
   ```bash
   # Upload to Databricks
   databricks workspace import scripts/monitoring_dashboard.py /Shared/conbot/monitoring --language PYTHON

   # Run in notebook
   ```

3. **Check GitHub issues**: https://github.com/your-org/conbot/issues

4. **Enable DEBUG logging**:
   ```bash
   python -m conbot.main --log-level=DEBUG ...
   ```

---

Last Updated: 2026-02-14
