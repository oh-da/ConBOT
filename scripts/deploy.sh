#!/bin/bash
#
# ConBOT Deployment Script
#
# Automates deployment of ConBOT to Databricks.
# Prerequisites: Databricks CLI configured, AWS SES verified
#
# Usage:
#   ./scripts/deploy.sh [--skip-build] [--skip-upload] [--skip-secrets]
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
WHEEL_NAME="conbot-1.0.0-py3-none-any.whl"
DBFS_WHEEL_PATH="dbfs:/FileStore/wheels/${WHEEL_NAME}"
DBFS_CONFIG_PATH="dbfs:/conbot/config/conferences.yaml"

# Parse arguments
SKIP_BUILD=false
SKIP_UPLOAD=false
SKIP_SECRETS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-upload)
            SKIP_UPLOAD=true
            shift
            ;;
        --skip-secrets)
            SKIP_SECRETS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-build] [--skip-upload] [--skip-secrets]"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is not installed. Please install it first."
        exit 1
    fi
}

# Pre-flight checks
log_info "Running pre-flight checks..."

check_command python
check_command databricks
check_command jq

# Check Python version
PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if [[ $(echo "$PYTHON_VERSION < 3.9" | bc) -eq 1 ]]; then
    log_error "Python 3.9+ required (found $PYTHON_VERSION)"
    exit 1
fi
log_info "Python version: $PYTHON_VERSION ✓"

# Check Databricks CLI configured
if ! databricks workspace ls / &> /dev/null; then
    log_error "Databricks CLI not configured. Run: databricks configure --token"
    exit 1
fi
log_info "Databricks CLI configured ✓"

# Step 1: Build wheel
if [ "$SKIP_BUILD" = false ]; then
    log_info "Building Python wheel..."

    if [ ! -f "pyproject.toml" ]; then
        log_error "pyproject.toml not found. Run from project root."
        exit 1
    fi

    # Install build if needed
    if ! python -c "import build" 2>/dev/null; then
        log_info "Installing build package..."
        pip install build -q
    fi

    # Clean old builds
    rm -rf dist/ build/

    # Build
    python -m build

    if [ ! -f "dist/${WHEEL_NAME}" ]; then
        log_error "Wheel build failed. Expected dist/${WHEEL_NAME}"
        exit 1
    fi

    log_info "Wheel built successfully: dist/${WHEEL_NAME} ✓"
else
    log_warn "Skipping build (--skip-build)"
fi

# Step 2: Upload wheel and config
if [ "$SKIP_UPLOAD" = false ]; then
    log_info "Uploading wheel to Databricks..."

    # Create directory if needed
    databricks fs mkdirs dbfs:/FileStore/wheels 2>/dev/null || true

    # Upload wheel
    databricks fs cp "dist/${WHEEL_NAME}" "${DBFS_WHEEL_PATH}" --overwrite
    log_info "Wheel uploaded to ${DBFS_WHEEL_PATH} ✓"

    # Upload config
    log_info "Uploading configuration..."
    databricks fs mkdirs dbfs:/conbot/config 2>/dev/null || true
    databricks fs cp config/conferences.yaml "${DBFS_CONFIG_PATH}" --overwrite
    log_info "Config uploaded to ${DBFS_CONFIG_PATH} ✓"

    # Verify uploads
    log_info "Verifying uploads..."
    if ! databricks fs ls dbfs:/FileStore/wheels/ | grep -q "${WHEEL_NAME}"; then
        log_error "Wheel verification failed"
        exit 1
    fi
    if ! databricks fs ls dbfs:/conbot/config/ | grep -q "conferences.yaml"; then
        log_error "Config verification failed"
        exit 1
    fi
    log_info "Upload verification passed ✓"
else
    log_warn "Skipping upload (--skip-upload)"
fi

# Step 3: Set up secrets
if [ "$SKIP_SECRETS" = false ]; then
    log_info "Setting up Databricks secrets..."

    # Check if scopes exist
    if ! databricks secrets list-scopes | grep -q "email-credentials"; then
        log_warn "Secret scope 'email-credentials' not found"
        read -p "Create it now? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            databricks secrets create-scope --scope email-credentials
            log_info "Created scope: email-credentials"
        fi
    else
        log_info "Secret scope 'email-credentials' exists ✓"
    fi

    if ! databricks secrets list-scopes | grep -q "llm-credentials"; then
        log_warn "Secret scope 'llm-credentials' not found"
        read -p "Create it now? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            databricks secrets create-scope --scope llm-credentials
            log_info "Created scope: llm-credentials"
        fi
    else
        log_info "Secret scope 'llm-credentials' exists ✓"
    fi

    # Prompt for secrets if missing
    log_info "Checking required secrets..."

    if ! databricks secrets list --scope email-credentials | grep -q "sender-email"; then
        log_warn "Secret 'sender-email' not set"
        echo "Set it with: databricks secrets put --scope email-credentials --key sender-email"
    fi

    if ! databricks secrets list --scope email-credentials | grep -q "recipient-email"; then
        log_warn "Secret 'recipient-email' not set"
        echo "Set it with: databricks secrets put --scope email-credentials --key recipient-email"
    fi

    if ! databricks secrets list --scope llm-credentials | grep -q "openai-api-key"; then
        log_warn "Secret 'openai-api-key' not set (optional)"
        echo "Set it with: databricks secrets put --scope llm-credentials --key openai-api-key"
    fi

else
    log_warn "Skipping secrets setup (--skip-secrets)"
fi

# Step 4: Upload initialization scripts
log_info "Uploading initialization scripts..."

databricks workspace mkdirs /Shared/conbot 2>/dev/null || true

databricks workspace import \
    databricks/init_scripts/setup_tables.py \
    /Shared/conbot/setup_tables \
    --language PYTHON \
    --overwrite

log_info "Initialization scripts uploaded ✓"

# Step 5: Summary
echo ""
log_info "=================================="
log_info "Deployment Complete!"
log_info "=================================="
echo ""
echo "Next steps:"
echo "  1. Run table initialization:"
echo "     - Navigate to Workspace → /Shared/conbot/setup_tables"
echo "     - Attach to cluster (Runtime 13.3+, i3.xlarge)"
echo "     - Run all cells"
echo ""
echo "  2. Initialize conference states:"
echo "     - Run: python -m conbot.main --mode=initialize"
echo ""
echo "  3. Test email configuration:"
echo "     - Run: python -m conbot.main --mode=test-email"
echo ""
echo "  4. Deploy workflow:"
echo "     - Update databricks/workflows/daily_scan.yaml (email, IAM role)"
echo "     - Run: databricks jobs create --json-file databricks/workflows/daily_scan.yaml"
echo ""
echo "See docs/DEPLOYMENT.md for detailed instructions."
echo ""
