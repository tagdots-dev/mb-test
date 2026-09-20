from unittest.mock import AsyncMock, Mock, patch

import pytest

from pkg_30922.services.gh_pr import GithubException, _filter_prs, get_open_prs


@pytest.mark.asyncio
class TestGetOpenPrs:
    """Tests for get_open_prs function."""

    @patch("pkg_30922.services.gh_pr._filter_prs")
    async def test_get_open_prs_success(self, mock_filter_prs: AsyncMock) -> None:
        """Test successful retrieval of open PRs."""
        mock_gh = Mock()
        mock_repo1 = Mock()
        mock_repo1.full_name = "org/repo1"
        mock_repo2 = Mock()
        mock_repo2.full_name = "org/repo2"

        mock_filter_prs.side_effect = [
            [{"repo": "org/repo1", "number": 1, "title": "PR 1", "sha": "abc", "html_url": "url1"}],
            [{"repo": "org/repo2", "number": 2, "title": "PR 2", "sha": "def", "html_url": "url2"}],
        ]

        repos = [mock_repo1, mock_repo2]
        result = await get_open_prs(mock_gh, repos, "main", set(), set(), "")

        assert len(result) == 2
        assert result[0]["repo"] == "org/repo1"
        assert result[1]["repo"] == "org/repo2"

    @patch("pkg_30922.services.gh_pr._filter_prs")
    async def test_get_open_prs_empty_repos(self, mock_filter_prs: AsyncMock) -> None:
        """Test with empty repos list."""
        mock_gh = Mock()

        result = await get_open_prs(mock_gh, [], "main", set(), set(), "")

        assert result == []
        mock_filter_prs.assert_not_called()

    @patch("pkg_30922.services.gh_pr._filter_prs")
    async def test_get_open_prs_with_github_exception(self, mock_filter_prs: AsyncMock) -> None:
        """Test handling of GithubException in a repo."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_filter_prs.return_value = GithubException(status=403, data={"message": "Rate limit exceeded"})

        repos = [mock_repo]
        result = await get_open_prs(mock_gh, repos, "main", set(), set(), "")

        assert result == []

    @patch("pkg_30922.services.gh_pr._filter_prs")
    async def test_get_open_prs_with_general_exception(self, mock_filter_prs: AsyncMock) -> None:
        """Test handling of general exception in a repo."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_filter_prs.return_value = Exception("Unexpected error")

        repos = [mock_repo]
        result = await get_open_prs(mock_gh, repos, "main", set(), set(), "")

        assert result == []

    @patch("pkg_30922.services.gh_pr._filter_prs")
    async def test_get_open_prs_with_none_result(self, mock_filter_prs: AsyncMock) -> None:
        """Test handling when _filter_prs returns None (no matching PRs)."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_filter_prs.return_value = None

        repos = [mock_repo]
        result = await get_open_prs(mock_gh, repos, "main", set(), set(), "")

        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_no_matching_labels(self, mock_to_thread: AsyncMock) -> None:
        """Test that PRs without matching labels are filtered out."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [{"name": "bug"}],
            },
            {
                "number": 2,
                "title": "feat: add feature",
                "head": {"sha": "def456"},
                "html_url": "https://github.com/org/repo/pull/2",
                "labels": [{"name": "enhancement"}],
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Feature label filter matches second PR
        # Pylance: return type is List[dict] | None, but mock ensures non-None
        result = await _filter_prs(mock_gh, mock_repo, "main", set(), {"enhancement"}, "")  # type: ignore[misc]

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["title"] == "feat: add feature"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_empty_repos(self, mock_to_thread: AsyncMock) -> None:
        """Test that empty repos return None."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_to_thread.return_value = ([], [])

        result = await _filter_prs(mock_gh, mock_repo, "main", set(), set(), "")

        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_no_matching_prs(self, mock_to_thread: AsyncMock) -> None:
        """Test that PRs with no matching labels return None."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        # PR exists but doesn't match the label filter
        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [{"name": "bug"}],
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Filter for a label that doesn't exist
        result = await _filter_prs(mock_gh, mock_repo, "main", set(), {"feature"}, "")

        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_github_exception(self, mock_to_thread: AsyncMock) -> None:
        """Test handling of GithubException."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_to_thread.side_effect = GithubException(status=404, data={"message": "Not Found"})

        with pytest.raises(ValueError, match="GitHub API error for repo"):
            await _filter_prs(mock_gh, mock_repo, "main", set(), set(), "")

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_general_exception(self, mock_to_thread: AsyncMock) -> None:
        """Test handling of general exception."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        mock_to_thread.side_effect = Exception("Network error")

        with pytest.raises(ValueError, match="Error processing repo"):
            await _filter_prs(mock_gh, mock_repo, "main", set(), set(), "")

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_with_labels(self, mock_to_thread: AsyncMock) -> None:
        """Test filtering PRs by labels."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [{"name": "bug"}, {"name": "priority"}],
            },
            {
                "number": 2,
                "title": "feat: add feature",
                "head": {"sha": "def456"},
                "html_url": "https://github.com/org/repo/pull/2",
                "labels": [{"name": "enhancement"}],
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Pylance: return type is List[dict] | None, but mock ensures non-None
        result = await _filter_prs(mock_gh, mock_repo, "main", set(), {"bug"}, "")  # type: ignore[misc]

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["number"] == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_with_prefix(self, mock_to_thread: AsyncMock) -> None:
        """Test filtering PRs by title prefix."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [],
            },
            {
                "number": 2,
                "title": "feat: add feature",
                "head": {"sha": "def456"},
                "html_url": "https://github.com/org/repo/pull/2",
                "labels": [],
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Pylance: return type is List[dict] | None, but mock ensures non-None
        result = await _filter_prs(mock_gh, mock_repo, "main", set(), set(), "fix:")  # type: ignore[misc]

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["title"] == "fix: add bug fix"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_with_exclude_labels(self, mock_to_thread: AsyncMock) -> None:
        """Test filtering PRs by exclude labels."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [{"name": "bug"}, {"name": "security"}],  # Has security label (to be excluded)
            },
            {
                "number": 2,
                "title": "feat: add feature",
                "head": {"sha": "def456"},
                "html_url": "https://github.com/org/repo/pull/2",
                "labels": [{"name": "enhancement"}],  # No exclude label
            },
            {
                "number": 3,
                "title": "docs: add documentation",
                "head": {"sha": "ghi789"},
                "html_url": "https://github.com/org/repo/pull/3",
                "labels": [{"name": "security"}],  # Has security label (to be excluded)
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Exclude "security" label - should only return PR #2
        # Pylance: return type is List[dict] | None, but mock ensures non-None
        result = await _filter_prs(mock_gh, mock_repo, "main", {"security"}, set(), "")  # type: ignore[misc]

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["number"] == 2  # type: ignore[union-attr]
        assert result[0]["title"] == "feat: add feature"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_pr.asyncio.to_thread")
    async def test_filter_prs_with_exclude_labels_no_match(self, mock_to_thread: AsyncMock) -> None:
        """Test that PRs without matching exclude labels are included."""
        mock_gh = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "org/repo"

        pr_data = [
            {
                "number": 1,
                "title": "fix: add bug fix",
                "head": {"sha": "abc123"},
                "html_url": "https://github.com/org/repo/pull/1",
                "labels": [{"name": "bug"}],  # Doesn't match exclude label
            },
        ]

        mock_to_thread.return_value = ([], pr_data)

        # Exclude "security" label - PR has "bug", not "security", so should be included
        # Pylance: return type is List[dict] | None, but mock ensures non-None
        result = await _filter_prs(mock_gh, mock_repo, "main", {"security"}, set(), "")  # type: ignore[misc]

        # Pylance: result could be None, but assertion ensures it's not
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["number"] == 1  # type: ignore[union-attr]
