# ConBOT Local Deployment Guide

Complete guide for running ConBOT on your personal computer (Linux, macOS, or Windows).

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [System Service Setup](#system-service-setup)
7. [Maintenance](#maintenance)
8. [Troubleshooting](#troubleshooting)
9. [Uninstallation](#uninstallation)

---

## Overview

ConBOT local deployment runs entirely on your personal computer with:
- **SQLite database** (~/.conbot/conbot.db) - single file, zero configuration
- **APScheduler daemon** - background process for daily scans
- **Simple CLI** - `conbot` command for all operations
- **No cloud costs** - runs 24/7 on your machine

**Cost**: ~$0.50-4/month (AWS SES + optional OpenAI)
**vs Databricks**: Save ~$96-120/month

---

## Prerequisites

### Required

1. **Python 3.9+**
   ```bash
   python3 --version  # Should be 3.9 or higher
   ```

2. **pip** (Python package installer)
   ```bash
   pip3 --version
   ```

3. **AWS SES** (for email notifications)
   - AWS account
   - Verified sender email in SES Console
   - AWS credentials (access key + secret) OR IAM role

### Optional

4. **OpenAI API key** (for LLM summaries)
   - Get from: https://platform.openai.com/api-keys
   - Not required - graceful fallback without it

---

## Installation

### Quick Install

```bash
# Clone repository
git checkout feature/local-deployment

# Run installation script
./scripts/install_local.sh
```

The script will:
1. Check Python version (3.9+ required)
2. Create directory structure (~/.conbot/)
3. Copy configuration templates
4. Install ConBOT package
5. Install Playwright browsers
6. Initialize SQLite database
7. Load conferences from YAML

### Manual Install

If you prefer manual installation:

```bash
# 1. Create directories
mkdir -p ~/.conbot/{config,logs,backups}

# 2. Copy configuration
cp config/conferences.yaml ~/.conbot/config/

# 3. Install package
pip install -e .

# 4. Install Playwright
playwright install chromium

# 5. Initialize database
conbot db init

# 6. Load conferences
conbot config init-conferences
```

---

## Configuration

### 1. Edit Environment Variables

Edit `~/.conbot/.env` with your credentials:

```bash
nano ~/.conbot/.env
```

**Required settings:**

```bash
# AWS SES (REQUIRED)
SES_SENDER_EMAIL=conbot@yourdomain.com
SES_RECIPIENT_EMAIL=your-email@example.com
AWS_REGION=us-east-1

# AWS Credentials (if not using IAM role)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=your-secret-key
```

**Optional settings:**

```bash
# OpenAI (optional - graceful fallback without it)
OPENAI_API_KEY=sk-...

# Custom paths
CONBOT_CONFIG_PATH=$HOME/.conbot/config/conferences.yaml
CONBOT_DB_PATH=$HOME/.conbot/conbot.db

# Advanced settings
SIMHASH_THRESHOLD=5  # Change detection sensitivity
LOG_LEVEL=INFO       # DEBUG, INFO, WARNING, ERROR
```

### 2. Verify AWS SES Sender

Before ConBOT can send emails, verify your sender email in AWS SES:

1. Go to: https://console.aws.amazon.com/ses/home#/verified-identities
2. Click "Create identity"
3. Select "Email address"
4. Enter your sender email (e.g., conbot@yourdomain.com)
5. Click "Create identity"
6. Check your email and click verification link

**Note**: In SES Sandbox mode, you must also verify recipient email.

To request production access (no recipient verification):
1. AWS SES Console → Account dashboard
2. Click "Request production access"
3. Fill out form (usually approved in 24 hours)

### 3. Test Configuration

```bash
# Test email sending
conbot test-email -r your-email@example.com

# Should see: ✓ Test email sent successfully!
# Check your inbox (and spam folder)
```

### 4. Verify Database

```bash
# Show database statistics
conbot db stats

# Should show:
# Total conferences: 6
# Active conferences: 6
# Database size: ~0.01 MB
```

---

## Usage

### Starting the Daemon

**Start in background** (recommended for daily use):

```bash
conbot daemon start -r your-email@example.com
```

**Start in foreground** (useful for testing/debugging):

```bash
conbot daemon start -r your-email@example.com --foreground
```

**Custom schedule** (default: 09:00 AM daily):

```bash
conbot daemon start -r your-email@example.com --scan-hour 14 --scan-minute 30
# Scans daily at 14:30 (2:30 PM)
```

### Checking Status

```bash
conbot daemon status

# Output:
# ✓ Daemon is running
#   PID: 12345
#   PID file: ~/.conbot/conbot.pid
#   Next scan: 2026-02-15 09:00:00
```

### Viewing Logs

```bash
# View last 50 lines
conbot daemon logs

# View last 100 lines
conbot daemon logs --lines 100

# Follow logs (like tail -f)
conbot daemon logs --follow
```

### Stopping the Daemon

```bash
conbot daemon stop

# Output:
# ✓ Daemon stopped successfully
```

### Restarting the Daemon

```bash
conbot daemon restart -r your-email@example.com
```

### Manual Scanning

**Scan all conferences** (ignores schedule):

```bash
conbot scan --all -r your-email@example.com
```

**Scan specific conference**:

```bash
conbot scan --id=uitp_summit -r your-email@example.com
```

**Force scan** (ignore next_run_at):

```bash
conbot scan --all --force -r your-email@example.com
```

### Database Management

**Backup database**:

```bash
conbot db backup

# Output:
# ✓ Backup complete:
#   current: ./backup_20260214_103000/current.json
#   audit: ./backup_20260214_103000/audit.json
#   history: ./backup_20260214_103000/history.json
```

**Restore from backup**:

```bash
conbot db restore \
  --current=backup/current.json \
  --audit=backup/audit.json \
  --history=backup/history.json
```

**Vacuum database** (reclaim space):

```bash
conbot db vacuum
```

**Show statistics**:

```bash
conbot db stats
```

---

## System Service Setup

For automatic startup on system boot, configure as a system service:

### Linux (systemd)

1. Create service file:

```bash
sudo nano /etc/systemd/system/conbot.service
```

2. Add content (replace `USERNAME` and `EMAIL`):

```ini
[Unit]
Description=ConBOT Conference Deadline Monitor
After=network.target

[Service]
Type=simple
User=USERNAME
WorkingDirectory=/home/USERNAME
ExecStart=/usr/local/bin/conbot daemon start -r EMAIL --foreground
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

3. Enable and start:

```bash
sudo systemctl enable conbot
sudo systemctl start conbot
sudo systemctl status conbot
```

### macOS (launchd)

1. Create plist file:

```bash
nano ~/Library/LaunchAgents/com.conbot.daemon.plist
```

2. Add content (replace `USERNAME` and `EMAIL`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.conbot.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/conbot</string>
        <string>daemon</string>
        <string>start</string>
        <string>-r</string>
        <string>EMAIL</string>
        <string>--foreground</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/USERNAME/.conbot/logs/conbot.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/USERNAME/.conbot/logs/conbot-error.log</string>
</dict>
</plist>
```

3. Load and start:

```bash
launchctl load ~/Library/LaunchAgents/com.conbot.daemon.plist
launchctl start com.conbot.daemon
launchctl list | grep conbot
```

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create new task:
   - Name: "ConBOT Daemon"
   - Trigger: At startup
   - Action: Start a program
     - Program: `C:\Python39\Scripts\conbot.exe`
     - Arguments: `daemon start -r your@email.com --foreground`
   - Settings:
     - ✓ Run whether user is logged on or not
     - ✓ Do not start if on battery power

---

## Maintenance

### Daily Monitoring

Check daemon status and logs daily for the first week:

```bash
# Check status
conbot daemon status

# Check logs
conbot daemon logs --lines 100
```

### Weekly Backup

Backup database weekly:

```bash
# Create backup
conbot db backup -o ~/conbot-backups/

# Keep last 4 backups (monthly retention)
```

### Monthly Review

Check statistics monthly:

```bash
conbot db stats

# Expected values:
# Total scans: ~180 (6 conferences × 30 days)
# Database size: <10 MB
```

### Log Rotation

Logs are automatically rotated when they reach 10MB. Old logs are compressed.

Manual cleanup:

```bash
# Remove old logs (keep last 30 days)
find ~/.conbot/logs -name "*.log.*" -mtime +30 -delete
```

---

## Troubleshooting

### Daemon Won't Start

**Error: "Daemon already running"**

```bash
# Check if really running
conbot daemon status

# If stale PID file, remove it
rm ~/.conbot/conbot.pid

# Start again
conbot daemon start -r your@email.com
```

**Error: "Permission denied"**

```bash
# Check file permissions
ls -la ~/.conbot/

# Fix permissions
chmod 755 ~/.conbot
chmod 644 ~/.conbot/.env
```

### Emails Not Sending

**Check SES verification**:

```bash
# Send test email
conbot test-email -r your@email.com
```

**Common issues**:
1. Sender email not verified in AWS SES
2. AWS credentials incorrect
3. SES in sandbox mode (recipient must be verified)
4. Wrong AWS region in .env file

### Database Issues

**Database locked**:

```bash
# Stop daemon first
conbot daemon stop

# Then run operation
conbot db backup
```

**Corrupted database**:

```bash
# Restore from backup
conbot db restore --current=backup/current.json

# Or reset (WARNING: deletes all data)
rm ~/.conbot/conbot.db
conbot db init
conbot config init-conferences
```

### High Memory Usage

```bash
# Check daemon process
ps aux | grep conbot

# If > 500MB, restart
conbot daemon restart -r your@email.com
```

### Logs Not Appearing

```bash
# Check log file exists
ls -la ~/.conbot/logs/

# Check permissions
chmod 755 ~/.conbot/logs
touch ~/.conbot/logs/conbot.log
chmod 644 ~/.conbot/logs/conbot.log
```

---

## Uninstallation

### Stop Daemon

```bash
conbot daemon stop
```

### Remove System Service

**Linux**:
```bash
sudo systemctl stop conbot
sudo systemctl disable conbot
sudo rm /etc/systemd/system/conbot.service
```

**macOS**:
```bash
launchctl unload ~/Library/LaunchAgents/com.conbot.daemon.plist
rm ~/Library/LaunchAgents/com.conbot.daemon.plist
```

**Windows**:
- Open Task Scheduler
- Delete "ConBOT Daemon" task

### Backup Data (Optional)

```bash
conbot db backup -o ~/conbot-final-backup/
```

### Remove Files

```bash
# Remove ConBOT directory
rm -rf ~/.conbot

# Uninstall package
pip uninstall conbot -y
```

---

## File Locations

### Configuration

- Config dir: `~/.conbot/`
- Config file: `~/.conbot/config/conferences.yaml`
- Environment: `~/.conbot/.env`

### Data

- Database: `~/.conbot/conbot.db`
- Backups: `~/.conbot/backups/`

### Logs

- Daemon log: `~/.conbot/logs/conbot.log`
- PID file: `~/.conbot/conbot.pid`

---

## Next Steps

After successful installation:

1. ✅ **Test email** - Verify AWS SES works
2. ✅ **Manual scan** - Test conference scanning
3. ✅ **Start daemon** - Begin daily monitoring
4. ✅ **Check logs** - Verify everything works
5. ✅ **Setup autostart** - Configure system service
6. ✅ **Monitor first week** - Daily status checks

---

## Getting Help

- **Documentation**: `/docs` folder
- **Troubleshooting**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **CLI help**: `conbot --help`
- **Command help**: `conbot <command> --help`

---

Last Updated: 2026-02-14
