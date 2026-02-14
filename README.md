# ConBOT - Conference Tracking Bot

Automated system for monitoring academic and industry conference websites, detecting changes, extracting submission deadlines, and sending email alerts.

## Overview

ConBOT monitors 6 conference websites (UITP Summit, ITDP, TRB, ITF, TRA, ITS World Congress) for Call for Papers announcements and submission deadlines. It:

- **Detects changes** using three-tier fingerprinting (binary hash → filtered hash → semantic SimHash)
- **Extracts deadlines** with validated date parsing (abstract, paper, registration dates)
- **Adapts monitoring frequency** via state machine (MONTHLY → BIWEEKLY → URGENT)
- **Sends email alerts** with three templates (NO_CHANGE, CHANGE_NO_DATES, CHANGE_WITH_DATES)
- **Discovers links** for dynamic conference pages (TRB, ITF)
- **Provides audit trail** via Delta tables for full traceability

## Architecture

**Platform**: Databricks Workflows on AWS
**Storage**: Delta Lake tables on S3
**Notifications**: AWS SES
**Optional LLM**: OpenAI GPT-4o-mini (for change summaries)

### Core Components

1. **Fetcher**: HTTP requests with Playwright fallback for JavaScript sites
2. **Content Extractor**: Trafilatura (F1: 0.958) + keyword-based snippet extraction
3. **Change Detector**: Three-tier fingerprinting for reliable change detection
4. **Date Extractor**: Hybrid dateparser + regex with validation
5. **State Machine**: Automatic frequency adjustment based on findings
6. **Email Generator**: Jinja2 templates for structured notifications

## Project Structure

```
ConBOT/
├── config/
│   └── conferences.yaml        # Conference definitions
├── src/conbot/
│   ├── models/                 # Pydantic data models
│   ├── fetching/               # Web scraping
│   ├── extraction/             # Content and date extraction
│   ├── detection/              # Change detection
│   ├── discovery/              # Link discovery (TRB/ITF)
│   ├── llm/                    # OpenAI integration
│   ├── state/                  # Delta table operations
│   ├── scheduling/             # Workflow scheduling
│   ├── notification/           # Email generation
│   ├── utils/                  # Config, logging, secrets
│   └── main.py                 # Entry point
├── tests/                      # Unit and integration tests
└── databricks/                 # Databricks workflow configs
```

## Installation

### Local Development

```bash
# Clone repository
git clone https://github.com/ohad/ConBOT.git
cd ConBOT

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers (for JS rendering)
playwright install chromium

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables (Local Development)

Create `.env` file:

```bash
# AWS SES
EMAIL_CREDENTIALS_AWS_ACCESS_KEY_ID=your_access_key
EMAIL_CREDENTIALS_AWS_SECRET_ACCESS_KEY=your_secret_key
EMAIL_CREDENTIALS_SES_REGION=us-east-1
EMAIL_CREDENTIALS_SENDER_EMAIL=conbot@yourdomain.com

# OpenAI (optional)
LLM_CREDENTIALS_OPENAI_API_KEY=sk-...
```

## Configuration

Edit `config/conferences.yaml` to add or modify conferences:

```yaml
defaults:
  watch_mode: MONTHLY
  throttle_seconds: 1.5
  keyword_groups:
    cfp: ["call for papers", "abstracts", "deadlines"]
    no_dates: ["upcoming", "tba", "coming soon"]

conferences:
  - id: uitp_summit
    name: "UITP Global Public Transport Summit"
    urls:
      - "https://www.uitpsummit.org/"
    secondary_urls:
      - "https://www.uitpsummit.org/call-for-papers/"
```

## Running Locally

```bash
# Run tests
pytest tests/

# Run manual scan for one conference
python -m conbot.main --mode=manual --conference-id=uitp_summit

# Run daily scan (checks which conferences are due)
python -m conbot.main --mode=daily
```

## Deployment to Databricks

### 1. Set Up Secrets

```bash
# Create secret scopes
databricks secrets create-scope --scope email-credentials
databricks secrets create-scope --scope llm-credentials

# Add AWS SES credentials
databricks secrets put --scope email-credentials --key aws_access_key_id
databricks secrets put --scope email-credentials --key aws_secret_access_key
databricks secrets put --scope email-credentials --key ses_region
databricks secrets put --scope email-credentials --key sender_email

# Add OpenAI API key (optional)
databricks secrets put --scope llm-credentials --key openai_api_key
```

### 2. Build and Upload Package

```bash
# Build wheel
python -m build

# Upload to Databricks workspace
databricks fs cp dist/conbot-1.0.0-py3-none-any.whl dbfs:/FileStore/conbot/

# Upload config
databricks fs cp config/conferences.yaml dbfs:/FileStore/conbot/config/
```

### 3. Create Delta Tables

```bash
# Run initialization script
databricks runs submit --json @databricks/workflows/init_tables.json
```

### 4. Deploy Workflow

```bash
# Create daily scan job
databricks jobs create --json @databricks/workflows/daily_scan.yaml
```

## Delta Table Schema

### conferences_current
Current state of each monitored conference (one row per conference/URL).

| Column | Type | Description |
|--------|------|-------------|
| conference_id | STRING | Unique identifier (e.g., uitp_summit) |
| url | STRING | Primary URL being monitored |
| watch_mode | STRING | MONTHLY, BIWEEKLY, or URGENT |
| next_run_at | TIMESTAMP | Next scheduled scan time |
| binary_hash | STRING | SHA-256 of raw HTML |
| simhash_signature | BIGINT | SimHash for semantic similarity |
| current_deadlines | ARRAY<STRUCT> | Extracted deadlines with dates/types |
| tracked_links | ARRAY<STRUCT> | Discovered links (TRB/ITF) |

### conferences_audit
Append-only audit trail of all scans.

| Column | Type | Description |
|--------|------|-------------|
| audit_id | STRING | UUID for this scan |
| conference_id | STRING | Conference scanned |
| scan_timestamp | TIMESTAMP | When scan occurred |
| change_detected | BOOLEAN | Whether change was found |
| change_type | STRING | BINARY, FILTERED, SEMANTIC, NONE |
| deadlines_found | ARRAY<STRUCT> | Deadlines extracted |
| previous_watch_mode | STRING | Mode before scan |
| new_watch_mode | STRING | Mode after scan |

## Testing

```bash
# Run all tests
pytest tests/

# Run unit tests only
pytest tests/unit/ -v

# Run with coverage
pytest tests/ --cov=src/conbot --cov-report=html

# View coverage report
open htmlcov/index.html
```

## State Machine

```
MONTHLY (check every 30 days)
  ↓ content changed, no dates
BIWEEKLY (check every 14 days)
  ↓ deadlines found
URGENT (check daily)
```

Once in URGENT mode, system stays there until conference passes.

## Cost Estimates

- **Databricks**: ~$30-100/month (single-node cluster, 1 hour/day)
- **Storage (S3)**: <$1/month (Delta tables + HTML snapshots)
- **LLM (OpenAI)**: $0-4/month (only called on changes)
- **Email (SES)**: ~$0/month (first 62,000 emails free)

**Total**: ~$30-100/month

## Troubleshooting

### Email not received
- Check AWS SES sandbox mode (verify recipient emails)
- Check Databricks job logs for errors
- Verify secrets are set: `databricks secrets list --scope email-credentials`

### False positives (spurious alerts)
- Tune `SIMHASH_THRESHOLD` in `src/conbot/detection/fingerprint.py`
- Add noise patterns to exclude in `src/conbot/extraction/content.py`

### Missed deadlines
- Check `conferences_audit` table for scan history
- Verify date extraction patterns in `src/conbot/extraction/dates.py`
- Run manual scan: `python -m conbot.main --mode=manual --conference-id=<ID>`

## License

MIT License - see [LICENSE](LICENSE) file.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest tests/`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review plan document: `.claude/plans/breezy-dancing-hoare.md`
