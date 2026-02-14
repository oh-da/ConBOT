#!/bin/bash
#
# Setup Databricks Secrets for ConBOT
#
# Interactive script to create secret scopes and set required secrets.
#
# Usage:
#   ./scripts/setup_secrets.sh
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}ConBOT Secrets Setup${NC}"
echo "=================================="
echo ""

# Check Databricks CLI
if ! command -v databricks &> /dev/null; then
    echo -e "${RED}Error: Databricks CLI not installed${NC}"
    echo "Install with: pip install databricks-cli"
    exit 1
fi

# Check Databricks CLI configured
if ! databricks workspace ls / &> /dev/null; then
    echo -e "${RED}Error: Databricks CLI not configured${NC}"
    echo "Run: databricks configure --token"
    exit 1
fi

echo -e "${GREEN}✓ Databricks CLI configured${NC}"
echo ""

# ============================================================================
# Create Secret Scopes
# ============================================================================

echo -e "${BLUE}Step 1: Create Secret Scopes${NC}"
echo "=================================="
echo ""

# Email credentials scope
if databricks secrets list-scopes | grep -q "email-credentials"; then
    echo -e "${YELLOW}Secret scope 'email-credentials' already exists${NC}"
else
    echo "Creating secret scope: email-credentials"
    databricks secrets create-scope --scope email-credentials
    echo -e "${GREEN}✓ Created scope: email-credentials${NC}"
fi

# LLM credentials scope
if databricks secrets list-scopes | grep -q "llm-credentials"; then
    echo -e "${YELLOW}Secret scope 'llm-credentials' already exists${NC}"
else
    echo "Creating secret scope: llm-credentials"
    databricks secrets create-scope --scope llm-credentials
    echo -e "${GREEN}✓ Created scope: llm-credentials${NC}"
fi

echo ""

# ============================================================================
# Set Email Secrets
# ============================================================================

echo -e "${BLUE}Step 2: Configure Email Credentials${NC}"
echo "=================================="
echo ""

# Sender email
if databricks secrets list --scope email-credentials | grep -q "sender-email"; then
    echo -e "${YELLOW}Secret 'sender-email' already set${NC}"
    read -p "Update it? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Setting sender-email..."
        databricks secrets put --scope email-credentials --key sender-email
        echo -e "${GREEN}✓ Updated sender-email${NC}"
    fi
else
    echo "Setting sender-email..."
    echo "Enter the verified SES sender email (e.g., conbot@yourdomain.com):"
    databricks secrets put --scope email-credentials --key sender-email
    echo -e "${GREEN}✓ Set sender-email${NC}"
fi

# Recipient email
if databricks secrets list --scope email-credentials | grep -q "recipient-email"; then
    echo -e "${YELLOW}Secret 'recipient-email' already set${NC}"
    read -p "Update it? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Setting recipient-email..."
        databricks secrets put --scope email-credentials --key recipient-email
        echo -e "${GREEN}✓ Updated recipient-email${NC}"
    fi
else
    echo "Setting recipient-email..."
    echo "Enter your email address for notifications:"
    databricks secrets put --scope email-credentials --key recipient-email
    echo -e "${GREEN}✓ Set recipient-email${NC}"
fi

# AWS credentials (optional)
echo ""
echo -e "${YELLOW}AWS Credentials (optional if using IAM instance profile)${NC}"
read -p "Set AWS access keys? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Setting aws-access-key-id..."
    databricks secrets put --scope email-credentials --key aws-access-key-id

    echo "Setting aws-secret-access-key..."
    databricks secrets put --scope email-credentials --key aws-secret-access-key

    echo -e "${GREEN}✓ Set AWS credentials${NC}"
else
    echo "Skipping AWS credentials (will use IAM instance profile)"
fi

echo ""

# ============================================================================
# Set LLM Secrets
# ============================================================================

echo -e "${BLUE}Step 3: Configure LLM Credentials (Optional)${NC}"
echo "=================================="
echo ""

read -p "Configure OpenAI API key? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if databricks secrets list --scope llm-credentials | grep -q "openai-api-key"; then
        echo -e "${YELLOW}Secret 'openai-api-key' already set${NC}"
        read -p "Update it? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Setting openai-api-key..."
            databricks secrets put --scope llm-credentials --key openai-api-key
            echo -e "${GREEN}✓ Updated openai-api-key${NC}"
        fi
    else
        echo "Setting openai-api-key..."
        echo "Enter your OpenAI API key (starts with sk-):"
        databricks secrets put --scope llm-credentials --key openai-api-key
        echo -e "${GREEN}✓ Set openai-api-key${NC}"
    fi
else
    echo "Skipping LLM configuration (system will use fallback summaries)"
fi

echo ""

# ============================================================================
# Summary
# ============================================================================

echo -e "${GREEN}=================================="
echo "Secrets Setup Complete!"
echo "==================================${NC}"
echo ""

echo "Configured secrets:"
databricks secrets list --scope email-credentials
echo ""
databricks secrets list --scope llm-credentials
echo ""

echo "Next steps:"
echo "  1. Verify sender email in AWS SES Console"
echo "  2. Run: ./scripts/deploy.sh"
echo "  3. Test email: python -m conbot.main --mode=test-email"
echo ""
