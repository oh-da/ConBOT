"""
Secrets management for ConBOT.

Provides unified interface for retrieving secrets from:
- Databricks secret scopes (production)
- Environment variables (local development)
- .env files (local development)
"""

import os
from typing import Optional


class SecretsError(Exception):
    """Raised when a required secret cannot be retrieved."""
    pass


def get_secret(scope: str, key: str, default: Optional[str] = None) -> str:
    """
    Retrieve a secret from Databricks or environment variables.

    Tries in order:
    1. Databricks secret scope (if available)
    2. Environment variable (for local dev)
    3. Default value (if provided)

    Args:
        scope: Databricks secret scope name
        key: Secret key within the scope
        default: Optional default value if secret not found

    Returns:
        Secret value

    Raises:
        SecretsError: If secret cannot be found and no default provided

    Example:
        >>> api_key = get_secret("llm-credentials", "openai_api_key")
        >>> sender = get_secret("email-credentials", "sender_email")
    """
    # Try Databricks secrets first (only available in Databricks runtime)
    try:
        # Import dbutils only when in Databricks environment
        from pyspark.dbutils import DBUtils
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        dbutils = DBUtils(spark)

        value = dbutils.secrets.get(scope=scope, key=key)
        if value:
            return value
    except (ImportError, Exception):
        # Not in Databricks environment or secret not found
        pass

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
        f"Secret not found: {scope}/{key}. "
        f"Tried: Databricks scope '{scope}', env vars '{env_var_name}', '{key.upper()}'"
    )


def get_aws_ses_credentials() -> dict:
    """
    Get AWS SES credentials from secrets.

    Returns:
        Dictionary with 'access_key_id', 'secret_access_key', 'region', 'sender_email'

    Raises:
        SecretsError: If required credentials are missing
    """
    return {
        'access_key_id': get_secret("email-credentials", "aws_access_key_id"),
        'secret_access_key': get_secret("email-credentials", "aws_secret_access_key"),
        'region': get_secret("email-credentials", "ses_region", default="us-east-1"),
        'sender_email': get_secret("email-credentials", "sender_email"),
    }


def get_openai_api_key() -> str:
    """
    Get OpenAI API key from secrets.

    Returns:
        OpenAI API key

    Raises:
        SecretsError: If API key not found
    """
    return get_secret("llm-credentials", "openai_api_key")


def is_databricks_environment() -> bool:
    """
    Check if running in Databricks environment.

    Returns:
        True if in Databricks, False otherwise
    """
    try:
        from pyspark.dbutils import DBUtils
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        DBUtils(spark)
        return True
    except (ImportError, Exception):
        return False
