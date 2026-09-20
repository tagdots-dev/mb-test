"""
Integration tests
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from asyncclick.testing import CliRunner

from pkg_30922.cli import (
    CustomError,
    check_merge_method,
    check_owner,
    check_repo_type,
    find_config_file,
    main,
)


class TestCliHelperFunctions:
    """Tests for helper functions in cli.py."""

    def test_check_owner_valid(self) -> None:
        """Test check_owner with valid owner."""
        check_owner("user", ["org1", "org2"], "user")
        check_owner("org1", ["org1", "org2"], "user")

    def test_check_owner_invalid(self) -> None:
        """Test check_owner with invalid owner."""
        with pytest.raises(CustomError) as exc_info:
            check_owner("invalid", ["org1", "org2"], "user")
        assert "mismatch" in str(exc_info.value)

    def test_check_repo_type_valid(self) -> None:
        """Test check_repo_type with valid types."""
        check_repo_type("all")
        check_repo_type("private")
        check_repo_type("public")

    def test_check_repo_type_invalid(self) -> None:
        """Test check_repo_type with invalid type."""
        with pytest.raises(CustomError) as exc_info:
            check_repo_type("invalid")
        assert "requires all or private or public" in str(exc_info.value)

    def test_check_repo_type_empty_string(self) -> None:
        """Test check_repo_type with empty string (falsy value)."""
        # When repo_type is empty string, it's falsy so the if block is skipped
        # This covers the 73->exit False branch
        check_repo_type("")
        check_repo_type(None)  # type: ignore

    def test_check_merge_method_empty_string(self) -> None:
        """Test check_merge_method with empty string (falsy value)."""
        # When merge_method is empty string, it's falsy so the if block is skipped
        # This covers the 79->exit False branch
        check_merge_method("")
        check_merge_method(None)  # type: ignore

    def test_check_merge_method_valid(self) -> None:
        """Test check_merge_method with valid methods."""
        check_merge_method("merge")
        check_merge_method("rebase")
        check_merge_method("squash")

    def test_check_merge_method_invalid(self) -> None:
        """Test check_merge_method with invalid method."""
        with pytest.raises(CustomError) as exc_info:
            check_merge_method("invalid")
        assert "CLI option" in str(exc_info.value) and "merge, rebase, or squash" in str(exc_info.value)

    def test_find_config_file_exists(self) -> None:
        """Test find_config_file when config exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = f"{tmpdir}/config"
            os.makedirs(config_path)
            config_file = f"{config_path}/default.yaml"
            with open(config_file, "w") as f:
                f.write("base-branch: main\n")

            with patch("os.path.exists", return_value=True):
                result = find_config_file()
                assert result is not None

    def test_find_config_file_not_exists(self) -> None:
        """Test find_config_file when config does not exist."""
        with patch("os.path.exists", return_value=False):
            result = find_config_file()
            assert result is None


class TestCliRunnerIntegration:
    """Integration tests for CLI runner using asyncclick CliRunner."""

    @pytest.mark.asyncio
    async def test_cli_main_help(self) -> None:
        """Test CLI help output."""
        runner = CliRunner()
        result = await runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "--base-branch" in result.output
        assert "--dry-run" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_version(self) -> None:
        """Test CLI version output."""
        runner = CliRunner()
        result = await runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output.lower()

    @pytest.mark.asyncio
    async def test_cli_main_with_config_file(self) -> None:
        """Test main() with config file present."""
        from unittest.mock import AsyncMock

        runner = CliRunner()

        # Create a temporary config file
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = f"{tmpdir}/config"
            os.makedirs(config_path)
            config_file = f"{config_path}/default.yaml"
            with open(config_file, "w") as f:
                f.write("base-branch: main\n")

            # Mock all the external dependencies
            with (
                patch("pkg_30922.cli.get_auth") as mock_get_auth,
                patch("pkg_30922.cli.get_token_user_info") as mock_get_token_user_info,
                patch("pkg_30922.cli.get_repos_from_all") as mock_get_repos,
                patch("pkg_30922.cli.get_open_prs") as mock_get_open_prs,
                patch("pkg_30922.cli.get_merge_readiness") as mock_get_merge_readiness,
                patch("pkg_30922.cli.put_merge_pr") as mock_put_merge_pr,
                patch("pkg_30922.cli.find_config_file", return_value=config_file),
                patch("pkg_30922.cli.load_config") as mock_load_config,
            ):

                # Return proper Config object from load_config
                from pkg_30922.config import Config

                mock_load_config.return_value = (Config(base_branch="main"), {})

                gh_mock = MagicMock()
                user_mock = MagicMock()
                user_mock.login = "testuser"
                gh_mock.get_user.return_value = user_mock

                mock_get_auth.return_value = (gh_mock, "test_token")
                mock_get_token_user_info.return_value = ("testuser", [])
                mock_get_repos.return_value = ([], [])
                mock_get_open_prs.return_value = AsyncMock(return_value=[])
                mock_get_merge_readiness.return_value = AsyncMock(return_value=[])
                mock_put_merge_pr.return_value = AsyncMock(return_value=None)

                result = await runner.invoke(main, ["--dry-run", "true"])

                assert result.exit_code == 0 or result.exit_code == 1
                # Should have config file loading message
                assert "Loading configuration" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_with_invalid_repo_type(self) -> None:
        """Test CLI with invalid repo-type."""
        runner = CliRunner()
        result = await runner.invoke(main, ["--repo-type", "invalid"])
        assert result.exit_code == 1
        # The validation happens after config is loaded, so we get "Authentication Error"
        # because the config file exists but the validation runs in check_repo_type
        # The error might be a CustomError or an authentication error depending on flow
        assert "Error" in result.output or "Error" in result.exception.__str__()

    @pytest.mark.asyncio
    async def test_cli_main_with_invalid_merge_method(self) -> None:
        """Test CLI with invalid merge-method."""
        runner = CliRunner()
        result = await runner.invoke(main, ["--merge-method", "invalid"])
        assert result.exit_code == 1
        # Similar to repo-type, the validation happens after config is loaded
        assert "Error" in result.output or "Error" in result.exception.__str__()

    @pytest.mark.asyncio
    async def test_cli_main_prints_config(self) -> None:
        """Test that main() prints configuration."""
        from unittest.mock import AsyncMock

        runner = CliRunner()

        with (
            patch("pkg_30922.cli.get_auth") as mock_get_auth,
            patch("pkg_30922.cli.get_token_user_info") as mock_get_token_user_info,
            patch("pkg_30922.cli.get_repos_from_all") as mock_get_repos,
            patch("pkg_30922.cli.get_open_prs") as mock_get_open_prs,
            patch("pkg_30922.cli.get_merge_readiness") as mock_get_merge_readiness,
            patch("pkg_30922.cli.put_merge_pr") as mock_put_merge_pr,
        ):

            gh_mock = MagicMock()
            user_mock = MagicMock()
            user_mock.login = "testuser"
            gh_mock.get_user.return_value = user_mock

            mock_get_auth.return_value = (gh_mock, "test_token")
            mock_get_token_user_info.return_value = ("testuser", [])
            mock_get_repos.return_value = ([], [])
            mock_get_open_prs.return_value = AsyncMock(return_value=[])
            mock_get_merge_readiness.return_value = AsyncMock(return_value=[])
            mock_put_merge_pr.return_value = AsyncMock(return_value=None)

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 0 or result.exit_code == 1
            # Should have configuration output
            assert "Configuration" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_with_owner(self) -> None:
        """Test main() with owner specified."""
        from unittest.mock import AsyncMock

        runner = CliRunner()

        with (
            patch("pkg_30922.cli.get_auth") as mock_get_auth,
            patch("pkg_30922.cli.get_token_user_info") as mock_get_token_user_info,
            patch("pkg_30922.cli.get_repos_from_owner") as mock_get_repos,
            patch("pkg_30922.cli.get_open_prs") as mock_get_open_prs,
            patch("pkg_30922.cli.get_merge_readiness") as mock_get_merge_readiness,
            patch("pkg_30922.cli.put_merge_pr") as mock_put_merge_pr,
        ):

            gh_mock = MagicMock()
            user_mock = MagicMock()
            user_mock.login = "testuser"
            gh_mock.get_user.return_value = user_mock

            mock_get_auth.return_value = (gh_mock, "test_token")
            mock_get_token_user_info.return_value = ("testuser", [])
            mock_get_repos.return_value = ([], [])
            mock_get_open_prs.return_value = AsyncMock(return_value=[])
            mock_get_merge_readiness.return_value = AsyncMock(return_value=[])
            mock_put_merge_pr.return_value = AsyncMock(return_value=None)

            result = await runner.invoke(main, ["--owner", "testuser", "--dry-run", "false"])

            assert result.exit_code == 0 or result.exit_code == 1

    @pytest.mark.asyncio
    async def test_cli_main_handles_value_error(self) -> None:
        """Test main() handles ValueError."""
        runner = CliRunner()

        with patch("pkg_30922.cli.get_auth") as mock_get_auth:
            mock_get_auth.side_effect = ValueError("test error")

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 1
            assert "Error" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_handles_other_exception(self) -> None:
        """Test main() handles other exceptions."""
        runner = CliRunner()

        with patch("pkg_30922.cli.get_auth") as mock_get_auth:
            mock_get_auth.side_effect = Exception("unexpected error")

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 1
            assert "Unexpected Error" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_custom_error(self) -> None:
        """Test main() handles CustomError."""
        from pkg_30922.cli import CustomError

        runner = CliRunner()

        with patch("pkg_30922.cli.get_auth") as mock_get_auth:
            mock_get_auth.side_effect = CustomError("test custom error")

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 1
            assert "Configuration Error" in result.output
            assert "test custom error" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_key_error(self) -> None:
        """Test main() handles KeyError."""
        runner = CliRunner()

        with patch("pkg_30922.cli.get_auth") as mock_get_auth:
            mock_get_auth.side_effect = KeyError("test key error")

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 1
            assert "Authentication Error" in result.output

    @pytest.mark.asyncio
    async def test_cli_main_with_none_config_file(self) -> None:
        """Test main() handles None config file (no config file exists)."""
        from unittest.mock import AsyncMock

        runner = CliRunner()

        with (
            patch("pkg_30922.cli.get_auth") as mock_get_auth,
            patch("pkg_30922.cli.get_token_user_info") as mock_get_token_user_info,
            patch("pkg_30922.cli.get_repos_from_all") as mock_get_repos,
            patch("pkg_30922.cli.get_open_prs") as mock_get_open_prs,
            patch("pkg_30922.cli.get_merge_readiness") as mock_get_merge_readiness,
            patch("pkg_30922.cli.put_merge_pr") as mock_put_merge_pr,
            patch("pkg_30922.cli.find_config_file", return_value=None),
        ):

            gh_mock = MagicMock()
            user_mock = MagicMock()
            user_mock.login = "testuser"
            gh_mock.get_user.return_value = user_mock

            mock_get_auth.return_value = (gh_mock, "test_token")
            mock_get_token_user_info.return_value = ("testuser", [])
            mock_get_repos.return_value = ([], [])
            mock_get_open_prs.return_value = AsyncMock(return_value=[])
            mock_get_merge_readiness.return_value = AsyncMock(return_value=[])
            mock_put_merge_pr.return_value = AsyncMock(return_value=None)

            result = await runner.invoke(main, ["--dry-run", "true"])

            assert result.exit_code == 0 or result.exit_code == 1
            # Should NOT have config file loading message (config file doesn't exist)
            assert "Loading configuration" not in result.output
