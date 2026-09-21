import asyncio
from unittest.mock import Mock, patch

import pytest

from pkg_30922.services.gh_merge import (
    _merge,
    put_merge_pr,
)


class TestPutMergePr:
    """Tests for put_merge_pr function."""

    def test_put_merge_pr_dry_run(self) -> None:
        """Test dry_run mode - should return empty list without merging."""
        mock_gh = Mock()
        list_mergeable_prs = [{"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"}]

        result = asyncio.run(put_merge_pr(mock_gh, list_mergeable_prs, "merge", True))

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_success(self, mock_merge: Mock) -> None:
        """Test successful merge of PRs."""
        mock_merge.return_value = [
            {"html_url": "url1", "title": "PR 1"},
        ]

        mock_gh = Mock()
        list_mergeable_prs = [
            {"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"},
        ]

        result = await put_merge_pr(mock_gh, list_mergeable_prs, "squash", False)

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["html_url"] == "url1"  # type: ignore[union-attr]
        assert result[0]["title"] == "PR 1"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_github_exception(self, mock_merge: Mock) -> None:
        """Test handling of GithubException during merge."""
        mock_merge.side_effect = ValueError("GitHub API error for repo org/repo: 404 - {'message': 'Not found'}")

        mock_gh = Mock()
        list_mergeable_prs = [{"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"}]

        result = await put_merge_pr(mock_gh, list_mergeable_prs, "merge", False)

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_general_exception(self, mock_merge: Mock) -> None:
        """Test handling of general exception during merge."""
        mock_merge.side_effect = ValueError("Error processing repo org/repo: Connection timeout")

        mock_gh = Mock()
        list_mergeable_prs = [{"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"}]

        result = await put_merge_pr(mock_gh, list_mergeable_prs, "merge", False)

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_empty_list(self, mock_merge: Mock) -> None:
        """Test merge with empty list - should return empty list."""
        mock_gh = Mock()
        result = await put_merge_pr(mock_gh, [], "merge", False)

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_mixed_results(self, mock_merge: Mock) -> None:
        """Test handling of mixed results (some successful, some failed)."""
        mock_merge.side_effect = [
            [{"html_url": "url1", "title": "PR 1"}],
            ValueError("GitHub API error for repo org/repo2: 404"),
        ]

        mock_gh = Mock()
        list_mergeable_prs = [
            {"repo": "org/repo1", "number": 1, "title": "PR 1", "html_url": "url1"},
            {"repo": "org/repo2", "number": 2, "title": "PR 2", "html_url": "url2"},
        ]

        result = await put_merge_pr(mock_gh, list_mergeable_prs, "merge", False)

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["html_url"] == "url1"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_github_exception_from_merge(self, mock_merge: Mock) -> None:
        """Test handling of GithubException returned from _merge."""
        from github import GithubException

        mock_merge.return_value = GithubException(status=404, data={"message": "Not found"})

        mock_gh = Mock()
        list_mergeable_prs = [{"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"}]

        result = await put_merge_pr(mock_gh, list_mergeable_prs, "merge", False)

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge._merge")
    async def test_put_merge_pr_multiple_merge_methods(self, mock_merge: Mock) -> None:
        """Test with different merge methods."""
        mock_merge.return_value = [{"html_url": "url1", "title": "PR 1"}]

        mock_gh = Mock()
        list_mergeable_prs = [{"repo": "org/repo", "number": 1, "title": "PR 1", "html_url": "url1"}]

        for method in ["merge", "squash", "rebase"]:
            await put_merge_pr(mock_gh, list_mergeable_prs, method, False)
            mock_merge.assert_called()
            mock_merge.reset_mock()


class TestMerge:
    """Tests for _merge function."""

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_success(self, mock_to_thread: Mock) -> None:
        """Test successful merge operation."""
        mock_to_thread.return_value = (
            {"header": "value"},
            {"merged": True, "sha": "abc123", "message": "Merged"},
        )

        mock_gh = Mock()
        result = await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "squash")

        assert len(result) == 1
        assert result[0]["html_url"] == "url1"
        assert result[0]["title"] == "Test PR"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_merge_method(self, mock_to_thread: Mock) -> None:
        """Test merge with merge method."""
        mock_to_thread.return_value = (
            {"header": "value"},
            {"merged": True, "sha": "abc123", "message": "Merged"},
        )

        mock_gh = Mock()
        await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "merge")

        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        assert call_args[1]["input"]["merge_method"] == "merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_squash_method(self, mock_to_thread: Mock) -> None:
        """Test merge with squash method."""
        mock_to_thread.return_value = (
            {"header": "value"},
            {"merged": True, "sha": "abc123", "message": "Merged"},
        )

        mock_gh = Mock()
        await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "squash")

        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        assert call_args[1]["input"]["merge_method"] == "squash"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_rebase_method(self, mock_to_thread: Mock) -> None:
        """Test merge with rebase method."""
        mock_to_thread.return_value = (
            {"header": "value"},
            {"merged": True, "sha": "abc123", "message": "Merged"},
        )

        mock_gh = Mock()
        await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "rebase")

        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        assert call_args[1]["input"]["merge_method"] == "rebase"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_github_exception(self, mock_to_thread: Mock) -> None:
        """Test handling of GithubException."""
        from github import GithubException as GHException

        mock_to_thread.side_effect = GHException(status=404, data={"message": "Not found"})

        mock_gh = Mock()
        with pytest.raises(ValueError) as exc_info:
            await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "merge")

        exc_str = str(exc_info.value)
        assert "GitHub API error for repo org/repo: 404" in exc_str

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_github_exception_with_data_and_msg(self, mock_to_thread: Mock) -> None:
        """Test GithubException with data and message."""
        from github import GithubException as GHException

        mock_to_thread.side_effect = GHException(status=403, data={"message": "Permission denied"})

        mock_gh = Mock()
        with pytest.raises(ValueError) as exc_info:
            await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "merge")

        exc_str = str(exc_info.value)
        assert "GitHub API error for repo org/repo: 403" in exc_str
        assert "Permission denied" in exc_str

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_github_exception_without_data(self, mock_to_thread: Mock) -> None:
        """Test GithubException without data (empty data dict)."""
        from github import GithubException as GHException

        mock_to_thread.side_effect = GHException(status=404, data={})

        mock_gh = Mock()
        with pytest.raises(ValueError) as exc_info:
            await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "merge")

        exc_str = str(exc_info.value)
        assert "GitHub API error for repo org/repo: 404" in exc_str
        assert " - {}" not in exc_str

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_general_exception(self, mock_to_thread: Mock) -> None:
        """Test handling of general exception."""
        mock_to_thread.side_effect = Exception("Connection timeout")

        mock_gh = Mock()
        with pytest.raises(ValueError) as exc_info:
            await _merge(mock_gh, "org/repo", 1, "Test PR", "url1", "merge")

        exc_str = str(exc_info.value)
        assert "Error processing repo org/repo: Connection timeout" in exc_str

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_merge.asyncio.to_thread")
    async def test_merge_with_special_characters(self, mock_to_thread: Mock) -> None:
        """Test merge with special characters in PR title."""
        mock_to_thread.return_value = (
            {"header": "value"},
            {"merged": True, "sha": "abc123", "message": "Merged"},
        )

        mock_gh = Mock()
        result = await _merge(mock_gh, "org/repo", 1, "Test PR: Fix bug #123", "url1", "merge")

        assert result[0]["title"] == "Test PR: Fix bug #123"
