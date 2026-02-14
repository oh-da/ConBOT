#!/bin/bash
#
# ConBOT Local Installation Script
#
# Installs ConBOT for local deployment (no Databricks required).
#
# Usage:
#   ./scripts/install_local.sh
#
# Requirements:
#   - Python 3.9+
#   - pip
#   - Playwright (installed automatically)

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       ConBOT Local Installation Script                    ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo ""

# ============================================================================
# Pre-flight Checks
# ============================================================================

echo -e "${BLUE}Step 1: Pre-flight checks${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

# Check Python version
echo -n "Checking Python version... "
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found${NC}"
    echo "Install Python 3.9+ from https://www.python.org/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo -e "${RED}✗ Python 3.9+ required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python $PYTHON_VERSION${NC}"

# Check pip
echo -n "Checking pip... "
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}✗ pip not found${NC}"
    echo "Install pip: python3 -m ensurepip --upgrade"
    exit 1
fi
echo -e "${GREEN}✓ pip installed${NC}"

echo ""

# ============================================================================
# Create Directory Structure
# ============================================================================

echo -e "${BLUE}Step 2: Create directory structure${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

CONBOT_DIR="$HOME/.conbot"

echo "Creating directories in: $CONBOT_DIR"

mkdir -p "$CONBOT_DIR/config"
mkdir -p "$CONBOT_DIR/logs"
mkdir -p "$CONBOT_DIR/backups"

echo -e "${GREEN}✓ Created directory structure${NC}"
echo ""

# ============================================================================
# Copy Configuration Template
# ============================================================================

echo -e "${BLUE}Step 3: Copy configuration files${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

# Copy conferences.yaml if it exists
if [ -f "config/conferences.yaml" ]; then
    cp config/conferences.yaml "$CONBOT_DIR/config/"
    echo -e "${GREEN}✓ Copied conferences.yaml${NC}"
else
    echo -e "${YELLOW}⚠ config/conferences.yaml not found (you'll need to create it manually)${NC}"
fi

# Create .env template
cat > "$CONBOT_DIR/.env" << 'EOF'
# ConBOT Environment Variables
#
# Copy this file and edit with your actual values
# Required for local deployment

# ============================================================================
# AWS SES Configuration (REQUIRED)
# ============================================================================

# Verified sender email address in AWS SES
# Must be verified in AWS SES Console before use
SES_SENDER_EMAIL=conbot@yourdomain.com

# Recipient email for notifications
SES_RECIPIENT_EMAIL=your-email@example.com

# AWS region for SES (default: us-east-1)
AWS_REGION=us-east-1

# AWS credentials (optional if using IAM role)
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=your-secret-key

# ============================================================================
# OpenAI LLM Configuration (OPTIONAL)
# ============================================================================

# OpenAI API key for GPT-4o-mini
# Get from: https://platform.openai.com/api-keys
# If not set, system will use fallback summaries (no LLM)
# OPENAI_API_KEY=sk-...

# ============================================================================
# ConBOT Configuration (OPTIONAL)
# ============================================================================

# Path to conferences.yaml config file
# CONBOT_CONFIG_PATH=$HOME/.conbot/config/conferences.yaml

# Path to SQLite database
# CONBOT_DB_PATH=$HOME/.conbot/conbot.db

# SimHash threshold for semantic change detection (default: 5)
# Higher = less sensitive, fewer false positives
# SIMHASH_THRESHOLD=5

# Log level (DEBUG, INFO, WARNING, ERROR)
# LOG_LEVEL=INFO
EOF

echo -e "${GREEN}✓ Created .env template${NC}"
echo ""

# ============================================================================
# Install ConBOT Package
# ============================================================================

echo -e "${BLUE}Step 4: Install ConBOT package${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

echo "Installing ConBOT in editable mode..."
pip3 install -e . --quiet

echo -e "${GREEN}✓ ConBOT package installed${NC}"
echo ""

# ============================================================================
# Install Playwright Browsers
# ============================================================================

echo -e "${BLUE}Step 5: Install Playwright browsers${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

echo "Installing Chromium browser for Playwright..."
playwright install chromium --quiet

echo -e "${GREEN}✓ Playwright browsers installed${NC}"
echo ""

# ============================================================================
# Initialize Database
# ============================================================================

echo -e "${BLUE}Step 6: Initialize database${NC}"
echo "══════════════════════════════════════════════════════════════"
echo ""

echo "Creating SQLite database schema..."
conbot db init

echo -e "${GREEN}✓ Database initialized${NC}"
echo ""

# ============================================================================
# Initialize Conferences (if config exists)
# ============================================================================

if [ -f "$CONBOT_DIR/config/conferences.yaml" ]; then
    echo -e "${BLUE}Step 7: Initialize conferences${NC}"
    echo "══════════════════════════════════════════════════════════════"
    echo ""

    echo "Loading conferences from YAML..."
    conbot config init-conferences

    echo -e "${GREEN}✓ Conferences initialized${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Skipping conference initialization (no config file)${NC}"
    echo ""
fi

# ============================================================================
# Installation Complete
# ============================================================================

echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Installation Complete!                               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Edit configuration file with your credentials:"
echo -e "   ${BLUE}nano $CONBOT_DIR/.env${NC}"
echo ""
echo "   Required settings:"
echo "   - SES_SENDER_EMAIL (must be verified in AWS SES)"
echo "   - SES_RECIPIENT_EMAIL (your email address)"
echo "   - AWS credentials (if not using IAM role)"
echo ""
echo "2. Verify AWS SES sender email in AWS Console:"
echo -e "   ${BLUE}https://console.aws.amazon.com/ses/home#/verified-identities${NC}"
echo ""
echo "3. Test email configuration:"
echo -e "   ${BLUE}conbot test-email -r your-email@example.com${NC}"
echo ""
echo "4. Start the daemon:"
echo -e "   ${BLUE}conbot daemon start -r your-email@example.com${NC}"
echo ""
echo "5. Check daemon status:"
echo -e "   ${BLUE}conbot daemon status${NC}"
echo ""
echo "6. View logs:"
echo -e "   ${BLUE}conbot daemon logs${NC}"
echo ""
echo -e "${YELLOW}Documentation:${NC}"
echo "  - Local deployment guide: docs/LOCAL_DEPLOYMENT.md"
echo "  - CLI reference: conbot --help"
echo "  - Troubleshooting: docs/TROUBLESHOOTING.md"
echo ""
echo -e "${YELLOW}Installed directories:${NC}"
echo "  - Config:  $CONBOT_DIR/config/"
echo "  - Database: $CONBOT_DIR/conbot.db"
echo "  - Logs:    $CONBOT_DIR/logs/"
echo "  - Backups: $CONBOT_DIR/backups/"
echo ""
echo -e "${GREEN}Happy deadline tracking! 🎯${NC}"
echo ""
