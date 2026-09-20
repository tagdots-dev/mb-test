"""
Configuration management and validation.

This module handles:
- Loading YAML configuration files from multiple locations
- Strict validation against a dataclass schema
- Merging CLI options with config file (CLI takes precedence over YAML)
- Label conversion (string to set) and boolean string parsing
- Error handling for invalid configurations
"""

import os
from dataclasses import dataclass, fields
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import yaml


@dataclass
class Config:
    """
    Configuration model.

    All fields are optional with defaults. CLI arguments take precedence over
    this configuration when provided.

    Attributes:
        base_branch: Target base branch name (default: "main")
        bypass_review_count: Bypass required review count (default: False)
        dry_run: Preview mode without actual merges (default: True)
        exclude_labels: List of labels to exclude to filter PRs (default: [])
        include_labels: List of labels to include to filter PRs (default: [])
        merge_method: Merge strategy: merge, rebase, or squash (default: "merge")
        owner: Filter to specific user/org (default: "")
        prefix: Filter PRs by title prefix (default: "")
        repo_type: Repository type filter: all, private, or public (default: "all")
    """

    base_branch: str = "main"
    dry_run: bool = True
    exclude_labels: Optional[List[str]] = None
    include_labels: Optional[List[str]] = None
    merge_method: str = "merge"
    bypass_review_count: bool = False
    owner: str = ""
    prefix: str = ""
    repo_type: str = "all"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.exclude_labels is None:
            self.exclude_labels = []

        if self.include_labels is None:
            self.include_labels = []

        allowed_merge_methods = {"merge", "rebase", "squash"}
        if self.merge_method not in allowed_merge_methods:
            raise ValueError(f"merge_method must be one of {allowed_merge_methods}, got '{self.merge_method}'")

        allowed_repo_types = {"all", "private", "public"}
        if self.repo_type not in allowed_repo_types:
            raise ValueError(f"repo_type must be one of {allowed_repo_types}, got '{self.repo_type}'")

        # Reject extra fields
        field_names = {f.name for f in fields(self)}
        for key in self.__dict__.keys():
            if key not in field_names:
                raise ValueError(f"Invalid config field: '{key}'")


def load_config(config_path: Optional[str] = None) -> tuple[Config, Dict[str, Any]]:
    """
    Load configuration from YAML file.

    For GitHub Actions users, config is expected at ./config/default.yaml.
    For CLI users, this file is optional (dataclass defaults are used if not found).

    Args:
        config_path: Optional explicit path to config file (default: ./config/default.yaml).

    Returns:
        Tuple of (Config object, raw config dict)

    Raises:
        ValueError: If config validation fails.
        yaml.YAMLError: If YAML parsing fails.
    """
    config_locations = []

    if config_path:
        config_locations.append(config_path)
    else:
        # Default location for GA users
        config_locations.append("./config/default.yaml")

    config_dict: Dict[str, Any] = {}

    for location in config_locations:
        if os.path.exists(location):
            with open(location, "r") as f:
                config_dict = yaml.safe_load(f) or {}
                break

    if not config_dict and not config_path:
        config_dict = {}

    try:
        # Convert kebab-case keys to snake_case
        converted_dict = _convert_kebab_to_snake(config_dict)
        config = Config(**converted_dict)
        return config, config_dict
    except Exception as err:
        source_file = config_locations[0] if config_path else "default configuration"
        raise ValueError(f"Configuration error in {source_file}: {err}")


def _convert_kebab_to_snake(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert kebab-case keys to snake_case for dataclass initialization."""
    conversion_map = {
        "base-branch": "base_branch",
        "bypass-review-count": "bypass_review_count",
        "dry-run": "dry_run",
        "exclude-labels": "exclude_labels",
        "include-labels": "include_labels",
        "merge-method": "merge_method",
        "repo-type": "repo_type",
    }

    result: Dict[str, Any] = {}
    for key, value in data.items():
        if key in conversion_map:
            result[conversion_map[key]] = value
        else:
            # Keep unknown keys as-is (they'll be caught by __post_init__ validation if invalid)
            result[key] = value

    return result


def merge_config_with_cli(config: Config, cli_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge CLI arguments with config, giving precedence to CLI args.

    Args:
        config: Config object from YAML file (or defaults).
        cli_args: Dictionary of CLI arguments.

    Returns:
        Dictionary with merged configuration (CLI overrides YAML).
    """
    merged = {
        "base_branch": cli_args.get("base_branch") or config.base_branch,
        "bypass_review_count": (
            cli_args.get("bypass_review_count")
            if cli_args.get("bypass_review_count") is not None
            else config.bypass_review_count
        ),
        "dry_run": cli_args.get("dry_run") if cli_args.get("dry_run") is not None else config.dry_run,
        "exclude_labels": cli_args.get("exclude_labels"),
        "include_labels": cli_args.get("include_labels"),
        "merge_method": cli_args.get("merge_method") or config.merge_method,
        "owner": cli_args.get("owner") or config.owner,
        "prefix": cli_args.get("prefix") or config.prefix,
        "repo_type": cli_args.get("repo_type") or config.repo_type,
    }

    # Use config defaults for any None values (labels can be None, others use 'or' above)
    if merged["exclude_labels"] is None:
        merged["exclude_labels"] = config.exclude_labels
    if merged["include_labels"] is None:
        merged["include_labels"] = config.include_labels

    # Handle exclude_labels: convert to set (CLI string or YAML list)
    if isinstance(merged["exclude_labels"], str):
        # Split on both commas and spaces for flexibility
        # First replace commas with spaces, then split
        exclude_label_str = merged["exclude_labels"].replace(",", " ")
        merged["exclude_labels"] = (
            {item.strip() for item in exclude_label_str.split() if item.strip()} if merged["exclude_labels"] else set()
        )
    elif isinstance(merged["exclude_labels"], list):
        merged["exclude_labels"] = set(merged["exclude_labels"])
    else:
        # Handle None or other types (None falls back to config in merge, so this is defensive)
        merged["exclude_labels"] = set()

    # Handle include_labels: convert to set (CLI string or YAML list)
    if isinstance(merged["include_labels"], str):
        # Split on both commas and spaces for flexibility
        # First replace commas with spaces, then split
        include_label_str = merged["include_labels"].replace(",", " ")
        merged["include_labels"] = (
            {item.strip() for item in include_label_str.split() if item.strip()} if merged["include_labels"] else set()
        )
    elif isinstance(merged["include_labels"], list):
        merged["include_labels"] = set(merged["include_labels"])
    else:
        # Handle None or other types (None falls back to config in merge, so this is defensive)
        merged["include_labels"] = set()

    # Convert boolean strings to actual booleans (for CLI args)
    for bool_field in ["dry_run", "bypass_review_count"]:
        if isinstance(merged[bool_field], str):
            value = merged[bool_field].lower()
            merged[bool_field] = value in ("true", "1", "yes")

    return merged
