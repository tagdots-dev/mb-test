import os
import tempfile

import pytest

from pkg_30922.config import Config, load_config, merge_config_with_cli


class TestConfigModel:
    def test_config_defaults(self) -> None:
        config = Config()
        assert config.base_branch == "main"
        assert config.dry_run is True
        assert config.exclude_labels == []
        assert config.include_labels == []
        assert config.merge_method == "merge"
        assert config.bypass_review_count is False
        assert config.owner == ""
        assert config.prefix == ""
        assert config.repo_type == "all"

    def test_config_with_values(self) -> None:
        config = Config(
            base_branch="develop",
            dry_run=False,
            exclude_labels=["WIP", "blocked"],
            include_labels=["bug", "ready"],
            merge_method="squash",
            bypass_review_count=True,
            owner="my-org",
            prefix="chore:",
            repo_type="private",
        )
        assert config.base_branch == "develop"
        assert config.dry_run is False
        assert config.exclude_labels == ["WIP", "blocked"]
        assert config.include_labels == ["bug", "ready"]
        assert config.merge_method == "squash"
        assert config.bypass_review_count is True
        assert config.owner == "my-org"
        assert config.prefix == "chore:"
        assert config.repo_type == "private"

    def test_config_with_none_labels_converts_to_empty_list(self) -> None:
        config = Config(
            base_branch="main",
            dry_run=True,
            exclude_labels=None,
            include_labels=None,
        )
        assert config.exclude_labels == []
        assert config.include_labels == []

    def test_config_extra_field_validation(self) -> None:
        # Test that __post_init__ validates extra fields and raises ValueError
        config = Config()
        # Add an extra field directly to __dict__ to simulate invalid config
        config.__dict__["extra_field"] = "invalid"  # type: ignore[arg-type]
        with pytest.raises(ValueError) as exc_info:
            config.__post_init__()
        assert "Invalid config field" in str(exc_info.value)

    def test_config_with_kebab_aliases(self) -> None:
        config = Config(
            base_branch="main",
            dry_run=True,
            exclude_labels=["test"],
            include_labels=["feature"],
            merge_method="rebase",
            bypass_review_count=False,
            owner="org",
            prefix="feat:",
            repo_type="public",
        )
        assert config.base_branch == "main"
        assert config.dry_run is True
        assert config.exclude_labels == ["test"]
        assert config.include_labels == ["feature"]
        assert config.merge_method == "rebase"
        assert config.bypass_review_count is False
        assert config.owner == "org"
        assert config.prefix == "feat:"
        assert config.repo_type == "public"

    def test_config_extra_forbidden(self) -> None:
        with pytest.raises(TypeError):
            Config(extra_field="invalid")  # type: ignore[call-arg]

    def test_validate_merge_method_invalid(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            Config(merge_method="invalid")
        assert "merge_method must be one of" in str(exc_info.value)

    def test_validate_repo_type_invalid(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            Config(repo_type="invalid")
        assert "repo_type must be one of" in str(exc_info.value)


class TestLoadConfig:
    def test_load_config_with_file(self) -> None:
        yaml_content = """base-branch: develop
dry-run: true
exclude-labels:
  - WIP
  - blocked
include-labels:
  - bug
  - ready
merge-method: squash
bypass-review-count: true
owner: my-org
prefix: "chore:"
repo-type: private
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                config, raw = load_config(f.name)
                assert config.base_branch == "develop"
                assert config.dry_run is True
                assert config.exclude_labels == ["WIP", "blocked"]
                assert config.include_labels == ["bug", "ready"]
                assert config.merge_method == "squash"
                assert config.bypass_review_count is True
                assert config.owner == "my-org"
                assert config.prefix == "chore:"
                assert config.repo_type == "private"
                assert raw is not None
            finally:
                os.unlink(f.name)

    def test_load_config_file_not_found(self) -> None:
        config, raw = load_config("/nonexistent/path/config.yaml")
        assert config.base_branch == "main"
        assert raw == {}

    def test_load_config_empty_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            try:
                config, raw = load_config(f.name)
                assert config.base_branch == "main"
                assert raw == {}
            finally:
                os.unlink(f.name)

    def test_load_config_default_location(self) -> None:
        # Test that default location is added to config_locations when no path provided
        # This tests line 94: config_locations.append("./config/default.yaml")
        # We create a ./config directory in the temp directory and put default.yaml there
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = os.path.join(tmpdir, "config")
            os.makedirs(config_dir)
            config_file = os.path.join(config_dir, "default.yaml")
            with open(config_file, "w") as f:
                f.write("base-branch: develop\n")
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config, raw = load_config()
                assert config.base_branch == "develop"
                assert raw == {"base-branch": "develop"}
            finally:
                os.chdir(original_cwd)

    def test_load_config_default_location_file_not_found(self) -> None:
        # Test lines 112-114: if not config_dict and not config_path
        # This happens when default file doesn't exist and no config_path provided
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                # Default location ./config/default.yaml doesn't exist
                config, raw = load_config()
                assert config.base_branch == "main"
                assert raw == {}
            finally:
                os.chdir(original_cwd)

    def test_load_config_with_invalid_merge_method(self) -> None:
        # Test lines 112-114: exception handling in load_config
        # This happens when config validation fails
        yaml_content = "merge-method: invalid"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                with pytest.raises(ValueError) as exc_info:
                    load_config(f.name)
                assert "Configuration error" in str(exc_info.value)
                assert "merge_method must be one of" in str(exc_info.value)
            finally:
                os.unlink(f.name)

    def test_load_config_with_invalid_repo_type(self) -> None:
        # Test lines 112-114: exception handling in load_config
        # This happens when config validation fails
        yaml_content = "repo-type: invalid"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                with pytest.raises(ValueError) as exc_info:
                    load_config(f.name)
                assert "Configuration error" in str(exc_info.value)
                assert "repo_type must be one of" in str(exc_info.value)
            finally:
                os.unlink(f.name)


class TestMergeConfigWithCli:
    def test_merge_cli_overrides_config(self) -> None:
        config = Config(
            base_branch="main",
            dry_run=True,
            exclude_labels=["WIP"],
            include_labels=["bug"],
            merge_method="merge",
            bypass_review_count=False,
            owner="config-owner",
            prefix="prefix1",
            repo_type="all",
        )
        cli_args = {
            "base_branch": "develop",
            "dry_run": False,
            "exclude_labels": ["blocked"],
            "include_labels": ["feature"],
            "merge_method": "squash",
            "bypass_review_count": True,
            "owner": "cli-owner",
            "prefix": "feat:",
            "repo_type": "private",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert merged["base_branch"] == "develop"
        assert merged["dry_run"] is False
        assert merged["exclude_labels"] == {"blocked"}
        assert merged["include_labels"] == {"feature"}
        assert merged["merge_method"] == "squash"
        assert merged["bypass_review_count"] is True
        assert merged["owner"] == "cli-owner"
        assert merged["prefix"] == "feat:"
        assert merged["repo_type"] == "private"

    def test_merge_config_defaults_used_when_cli_empty(self) -> None:
        config = Config(
            base_branch="main",
            dry_run=True,
            exclude_labels=["WIP"],
            include_labels=["bug"],
            merge_method="merge",
            bypass_review_count=False,
            owner="config-owner",
            prefix="prefix1",
            repo_type="all",
        )
        cli_args = {
            "base_branch": "",
            "dry_run": None,
            "exclude_labels": "",
            "include_labels": "",
            "merge_method": "",
            "bypass_review_count": None,
            "owner": "",
            "prefix": "",
            "repo_type": "",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert merged["base_branch"] == "main"
        assert merged["dry_run"] is True
        # Empty strings from CLI are used as-is and converted to empty sets
        assert merged["exclude_labels"] == set()
        assert merged["include_labels"] == set()
        assert merged["merge_method"] == "merge"
        assert merged["bypass_review_count"] is False
        assert merged["owner"] == "config-owner"
        assert merged["prefix"] == "prefix1"
        assert merged["repo_type"] == "all"

    def test_merge_cli_string_labels_converted_to_set(self) -> None:
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": "WIP, blocked",
            "include_labels": "bug, feature",
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert merged["exclude_labels"] == {"WIP", "blocked"}
        assert merged["include_labels"] == {"bug", "feature"}

    def test_merge_cli_list_labels_converted_to_set(self) -> None:
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": ["WIP", "blocked"],
            "include_labels": ["bug", "feature"],
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert merged["exclude_labels"] == {"WIP", "blocked"}
        assert merged["include_labels"] == {"bug", "feature"}

    def test_merge_cli_boolean_string_conversion(self) -> None:
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": "false",  # String "false"
            "exclude_labels": [],
            "include_labels": [],
            "merge_method": "merge",
            "bypass_review_count": "true",  # String "true"
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert merged["dry_run"] is False
        assert merged["bypass_review_count"] is True

    def test_merge_cli_list_to_set_conversion(self) -> None:
        # Test that list labels are converted to set
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": ["WIP", "blocked", "bug"],
            "include_labels": ["feature", "enhancement"],
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        assert isinstance(merged["exclude_labels"], set)
        assert isinstance(merged["include_labels"], set)
        assert merged["exclude_labels"] == {"WIP", "blocked", "bug"}
        assert merged["include_labels"] == {"feature", "enhancement"}

    def test_merge_cli_none_labels(self) -> None:
        # Test that None labels are handled correctly
        # This covers the else branch where labels are neither string nor list
        config = Config(exclude_labels=["existing"], include_labels=["existing"])
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": None,
            "include_labels": None,
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        # None from cli falls back to config's list, which is then converted to set
        assert isinstance(merged["exclude_labels"], set)
        assert isinstance(merged["include_labels"], set)
        assert merged["exclude_labels"] == {"existing"}
        assert merged["include_labels"] == {"existing"}

    def test_merge_cli_none_labels_with_none_config(self) -> None:
        # Test that None labels with None config are handled correctly
        # Note: Config.__post_init__ converts None to [], so config.exclude_labels
        # will always be a list, never None
        config = Config(exclude_labels=None, include_labels=None)
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": None,
            "include_labels": None,
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        # None from cli falls back to config's None, but __post_init__ converts
        # config.exclude_labels to [], which is then converted to set()
        assert isinstance(merged["exclude_labels"], set)
        assert isinstance(merged["include_labels"], set)
        assert merged["exclude_labels"] == set()
        assert merged["include_labels"] == set()

    def test_merge_cli_empty_list_labels(self) -> None:
        # Test that empty list labels are handled correctly
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": [],
            "include_labels": [],
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        # Empty list should be converted to empty set
        assert isinstance(merged["exclude_labels"], set)
        assert isinstance(merged["include_labels"], set)
        assert merged["exclude_labels"] == set()
        assert merged["include_labels"] == set()

    def test_merge_cli_non_string_non_list_labels(self) -> None:
        # Test that non-string, non-list labels are handled correctly
        # This covers the else branch for the isinstance check
        config = Config()
        cli_args = {
            "base_branch": "main",
            "dry_run": True,
            "exclude_labels": 123,  # Non-string, non-list value
            "include_labels": {"already": "set"},  # Dict instead of list
            "merge_method": "merge",
            "bypass_review_count": False,
            "owner": "",
            "prefix": "",
            "repo_type": "all",
        }
        merged = merge_config_with_cli(config, cli_args)
        # Non-string, non-list values should become empty sets
        assert isinstance(merged["exclude_labels"], set)
        assert isinstance(merged["include_labels"], set)
        assert merged["exclude_labels"] == set()
        assert merged["include_labels"] == set()
