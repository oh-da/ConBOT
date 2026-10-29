"""
Configuration loader for ConBOT.

Loads and validates YAML configuration files for conferences and settings.
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


def load_yaml(file_path: str | Path) -> Dict[str, Any]:
    """
    Load YAML file and return parsed content.

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML content as dictionary

    Raises:
        ConfigurationError: If file doesn't exist or is invalid YAML
    """
    path = Path(file_path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = yaml.safe_load(f)
        if content is None:
            raise ConfigurationError(f"Empty configuration file: {path}")
        return content
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e


def load_conferences_config(file_path: str | Path = None) -> Dict[str, Any]:
    """
    Load conferences.yaml configuration.

    Args:
        file_path: Optional path to conferences.yaml (default: config/conferences.yaml)

    Returns:
        Dictionary with 'defaults' and 'conferences' keys

    Raises:
        ConfigurationError: If configuration is invalid
    """
    if file_path is None:
        # Try to find conferences.yaml in standard locations
        candidates = [
            Path("config/conferences.yaml"),
            Path("/Workspace/conbot/config/conferences.yaml"),  # Databricks
            Path.home() / ".conbot" / "conferences.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                file_path = candidate
                break
        else:
            raise ConfigurationError(
                "conferences.yaml not found. Tried: " + ", ".join(str(c) for c in candidates)
            )

    config = load_yaml(file_path)

    # Validate required sections
    if 'defaults' not in config:
        raise ConfigurationError("Missing 'defaults' section in configuration")
    if 'conferences' not in config:
        raise ConfigurationError("Missing 'conferences' section in configuration")

    # Validate conferences list
    if not isinstance(config['conferences'], list):
        raise ConfigurationError("'conferences' must be a list")
    if len(config['conferences']) == 0:
        raise ConfigurationError("'conferences' list is empty")

    # Validate each conference has required fields
    for i, conf in enumerate(config['conferences']):
        if 'id' not in conf:
            raise ConfigurationError(f"Conference at index {i} missing 'id' field")
        if 'urls' not in conf and 'primary_urls' not in conf:
            raise ConfigurationError(
                f"Conference '{conf['id']}' missing 'urls' or 'primary_urls' field"
            )

    return config


def get_conference_by_id(config: Dict[str, Any], conference_id: str) -> Optional[Dict[str, Any]]:
    """
    Get configuration for a specific conference.

    Args:
        config: Full configuration dictionary
        conference_id: Conference ID to look up

    Returns:
        Conference configuration dict or None if not found
    """
    for conf in config.get('conferences', []):
        if conf.get('id') == conference_id:
            return conf
    return None


def get_all_conference_ids(config: Dict[str, Any]) -> List[str]:
    """
    Get list of all conference IDs in configuration.

    Args:
        config: Full configuration dictionary

    Returns:
        List of conference IDs
    """
    return [conf['id'] for conf in config.get('conferences', [])]


def merge_with_defaults(conference_config: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge conference-specific config with defaults.

    Args:
        conference_config: Conference-specific configuration
        defaults: Default configuration values

    Returns:
        Merged configuration (conference overrides defaults)
    """
    merged = defaults.copy()
    merged.update(conference_config)
    return merged


def load_conference_config(file_path: str | Path = None) -> List[Dict[str, Any]]:
    """
    Load conferences.yaml as a flat list of per-conference settings.

    Each entry is the conference block merged over ``defaults`` and gets
    these convenience keys:

    - ``name``: display name (falls back to the id)
    - ``primary_url``: first entry of ``urls``/``primary_urls``
    - ``keyword_groups``: dict of keyword lists (``cfp``, ``no_dates``)
    - ``cfp_keywords`` / ``no_dates_keywords``: the two lists, flattened

    Args:
        file_path: Optional path to conferences.yaml

    Returns:
        List of conference dicts

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_conferences_config(file_path)
    defaults = config['defaults']

    conferences = []
    for conf in config['conferences']:
        merged = merge_with_defaults(conf, defaults)
        urls = conf.get('urls') or conf.get('primary_urls') or []
        if not urls:
            raise ConfigurationError(f"Conference '{conf['id']}' has an empty url list")

        groups = merged.get('keyword_groups') or {}
        merged['name'] = conf.get('name', conf['id'])
        merged['primary_url'] = urls[0]
        merged['keyword_groups'] = groups
        merged['cfp_keywords'] = list(groups.get('cfp', []))
        merged['no_dates_keywords'] = list(groups.get('no_dates', []))
        conferences.append(merged)

    return conferences
