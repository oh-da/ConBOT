"""
Secrets management for ConBOT.

Provides unified interface for retrieving secrets from:
- Environment variables
- .env files (loaded via python-dotenv)

For local deployment only. Databricks version uses secret scopes.
"""

import os
from typing import Optional
from pathlib import Path


class SecretsError(Exception):
    """Raised when a required secret cannot be retrieved."""
    pass


# Load .env file if it exists (supports local development)
try:
    from dotenv import load_dotenv

    # Try multiple locations for .env file
    env_locations = [
        Path.home() / ".conbot" / ".env",  # User-specific config
        Path.cwd() / ".env",  # Current directory
        Path(__file__).parent.parent.parent / ".env",  # Project root
    ]

    for env_path in env_locations:
        if env_path.exists():
            load_dotenv(env_path)
            break

except ImportError:
    # python-dotenv not installed, env vars only
    pass


def get_secret(scope: str, key: str, default: Optional[str] = None) -> str:
    """
    Retrieve a secret from environment variables.

    Tries in order:
    1. Environment variable with format: SCOPE_KEY (e.g., EMAIL_CREDENTIALS_SENDER_EMAIL)
    2. Environment variable with just key (e.g., SENDER_EMAIL)
    3. Default value (if provided)

    Args:
        scope: Namespace for the secret (for compatibility with Databricks API)
        key: Secret key
        default: Optional default value if secret not found

    Returns:
        Secret value

    Raises:
        SecretsError: If secret cannot be found and no default provided

    Example:
        >>> api_key = get_secret("llm-credentials", "openai_api_key")
        >>> sender = get_secret("email-credentials", "sender_email")
    """
    # Try environment variable (format: SCOPE_KEY in uppercase)
    env_var_name = f"{scope}_{key}".upper().replace("-", "_")
    value = os.getenv(env_var_name)
    if value:
        return value

    # Try alternative format (just the key)
    value = os.getenv(key.upper().replace("-", "_"))
    if value:
        return value

    # Use default if provided
    if default is not None:
        return default

    # Secret not found and no default
    raise SecretsError(
        f"Secret not found: {key}. "
        f"Tried env vars: '{env_var_name}', '{key.upper().replace('-', '_')}'. "
        f"Set in environment or add to ~/.conbot/.env file."
    )


def get_aws_ses_credentials() -> dict:
    """
    Get AWS SES credentials from secrets.

    Returns:
        Dictionary with 'access_key_id', 'secret_access_key', 'region', 'sender_email'

    Note:
        AWS credentials (access_key_id, secret_access_key) are optional if using IAM role.

    Raises:
        SecretsError: If required credentials are missing
    """
    return {
        'access_key_id': get_secret("email-credentials", "aws_access_key_id", default=None),
        'secret_access_key': get_secret("email-credentials", "aws_secret_access_key", default=None),
        'region': get_secret("email-credentials", "aws_region", default="us-east-1"),
        'sender_email': get_secret("email-credentials", "sender_email"),
    }


def get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from secrets.

    Returns:
        OpenAI API key or None if not configured

    Note:
        OpenAI key is optional - system will work without LLM features.
    """
    try:
        return get_secret("llm-credentials", "openai_api_key")
    except SecretsError:
        return None
