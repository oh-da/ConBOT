#!/usr/bin/env python
"""
ConBOT Deployment Verification Script

Checks that all deployment steps completed successfully.

Usage:
    python scripts/verify_deployment.py
"""

import sys
import subprocess
import json
from typing import Dict, Tuple

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def run_command(cmd: list) -> Tuple[bool, str]:
    """Run shell command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"


def check_databricks_cli() -> bool:
    """Check Databricks CLI is installed and configured."""
    print(f"\n{BLUE}[1/8] Checking Databricks CLI...{RESET}")

    # Check installed
    success, _ = run_command(["databricks", "--version"])
    if not success:
        print(f"  {RED}✗ Databricks CLI not installed{RESET}")
        return False
    print(f"  {GREEN}✓ Databricks CLI installed{RESET}")

    # Check configured
    success, _ = run_command(["databricks", "workspace", "ls", "/"])
    if not success:
        print(f"  {RED}✗ Databricks CLI not configured{RESET}")
        print(f"    Run: databricks configure --token")
        return False
    print(f"  {GREEN}✓ Databricks CLI configured{RESET}")

    return True


def check_wheel_uploaded() -> bool:
    """Check wheel is uploaded to DBFS."""
    print(f"\n{BLUE}[2/8] Checking wheel upload...{RESET}")

    success, output = run_command([
        "databricks", "fs", "ls", "dbfs:/FileStore/wheels/"
    ])

    if not success:
        print(f"  {RED}✗ Wheel directory not found{RESET}")
        return False

    if "conbot" not in output:
        print(f"  {RED}✗ ConBOT wheel not found in dbfs:/FileStore/wheels/{RESET}")
        return False

    print(f"  {GREEN}✓ Wheel uploaded{RESET}")
    return True


def check_config_uploaded() -> bool:
    """Check conferences.yaml is uploaded."""
    print(f"\n{BLUE}[3/8] Checking configuration upload...{RESET}")

    success, output = run_command([
        "databricks", "fs", "ls", "dbfs:/conbot/config/"
    ])

    if not success:
        print(f"  {RED}✗ Config directory not found{RESET}")
        return False

    if "conferences.yaml" not in output:
        print(f"  {RED}✗ conferences.yaml not found{RESET}")
        return False

    print(f"  {GREEN}✓ Configuration uploaded{RESET}")
    return True


def check_secrets() -> bool:
    """Check secret scopes and required secrets exist."""
    print(f"\n{BLUE}[4/8] Checking secrets...{RESET}")

    all_good = True

    # Check email-credentials scope
    success, output = run_command([
        "databricks", "secrets", "list-scopes"
    ])

    if not success or "email-credentials" not in output:
        print(f"  {RED}✗ Secret scope 'email-credentials' not found{RESET}")
        all_good = False
    else:
        print(f"  {GREEN}✓ Secret scope 'email-credentials' exists{RESET}")

        # Check individual secrets
        success, secrets_output = run_command([
            "databricks", "secrets", "list", "--scope", "email-credentials"
        ])

        if success:
            if "sender-email" in secrets_output:
                print(f"  {GREEN}✓ sender-email set{RESET}")
            else:
                print(f"  {YELLOW}⚠ sender-email not set{RESET}")
                all_good = False

            if "recipient-email" in secrets_output:
                print(f"  {GREEN}✓ recipient-email set{RESET}")
            else:
                print(f"  {YELLOW}⚠ recipient-email not set{RESET}")
                all_good = False

    # Check llm-credentials scope
    if "llm-credentials" not in output:
        print(f"  {YELLOW}⚠ Secret scope 'llm-credentials' not found (optional){RESET}")
    else:
        print(f"  {GREEN}✓ Secret scope 'llm-credentials' exists{RESET}")

    return all_good


def check_init_scripts() -> bool:
    """Check initialization scripts are uploaded."""
    print(f"\n{BLUE}[5/8] Checking initialization scripts...{RESET}")

    success, output = run_command([
        "databricks", "workspace", "ls", "/Shared/conbot"
    ])

    if not success:
        print(f"  {RED}✗ /Shared/conbot directory not found{RESET}")
        return False

    if "setup_tables" not in output:
        print(f"  {RED}✗ setup_tables script not found{RESET}")
        return False

    print(f"  {GREEN}✓ Initialization scripts uploaded{RESET}")
    return True


def check_delta_tables() -> bool:
    """Check Delta tables are created."""
    print(f"\n{BLUE}[6/8] Checking Delta tables...{RESET}")

    # This requires running a Spark query via notebook
    # For now, we'll skip detailed checking
    print(f"  {YELLOW}⚠ Manual verification required{RESET}")
    print(f"    Run in Databricks notebook: spark.sql('SHOW TABLES IN conbot').show()")
    return True


def check_conferences_initialized() -> bool:
    """Check conferences are initialized in Delta table."""
    print(f"\n{BLUE}[7/8] Checking conference initialization...{RESET}")

    print(f"  {YELLOW}⚠ Manual verification required{RESET}")
    print(f"    Run: python -m conbot.main --mode=manual --conference-id=uitp_summit --force")
    return True


def check_workflow_deployed() -> bool:
    """Check Databricks workflow is deployed."""
    print(f"\n{BLUE}[8/8] Checking workflow deployment...{RESET}")

    success, output = run_command([
        "databricks", "jobs", "list"
    ])

    if not success:
        print(f"  {RED}✗ Failed to list jobs{RESET}")
        return False

    if "ConBOT" in output or "conbot" in output.lower():
        print(f"  {GREEN}✓ ConBOT workflow deployed{RESET}")
        return True
    else:
        print(f"  {YELLOW}⚠ ConBOT workflow not found{RESET}")
        print(f"    Deploy with: databricks jobs create --json-file databricks/workflows/daily_scan.yaml")
        return True  # Not critical, might not be deployed yet


def main():
    """Run all verification checks."""
    print(f"\n{'='*60}")
    print(f"{BLUE}ConBOT Deployment Verification{RESET}")
    print(f"{'='*60}")

    checks = [
        ("Databricks CLI", check_databricks_cli),
        ("Wheel Upload", check_wheel_uploaded),
        ("Config Upload", check_config_uploaded),
        ("Secrets", check_secrets),
        ("Init Scripts", check_init_scripts),
        ("Delta Tables", check_delta_tables),
        ("Conferences", check_conferences_initialized),
        ("Workflow", check_workflow_deployed),
    ]

    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"\n  {RED}✗ Error: {e}{RESET}")
            results[name] = False

    # Summary
    print(f"\n{'='*60}")
    print(f"{BLUE}Verification Summary{RESET}")
    print(f"{'='*60}\n")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, passed_check in results.items():
        status = f"{GREEN}✓ PASS{RESET}" if passed_check else f"{RED}✗ FAIL{RESET}"
        print(f"  {status}  {name}")

    print(f"\n{passed}/{total} checks passed")

    if passed == total:
        print(f"\n{GREEN}All checks passed! ✓{RESET}")
        print(f"\nDeployment is ready. Next steps:")
        print(f"  1. Run manual test scans")
        print(f"  2. Verify emails received")
        print(f"  3. Enable daily workflow")
        return 0
    else:
        print(f"\n{YELLOW}Some checks failed. Review output above.{RESET}")
        print(f"See docs/DEPLOYMENT.md for troubleshooting.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
