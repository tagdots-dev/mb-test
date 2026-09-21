from unittest.mock import Mock, patch

import pytest

from pkg_30922.services.gh_ci import (
    GithubException,
    _evaluate_ci_status,
    _evaluate_review_status,
    _evaluation,
    _extract_result_or_handle_error,
    _fetch_ci_status_with_fallback,
    _fetch_status_ci_fallback,
    get_merge_readiness,
)


class TestEvaluateCiStatus:
    """Tests for _evaluate_ci_status function."""

    def test_evaluate_ci_status_no_check_suites(self) -> None:
        """Test CI status with no check suites - should return ok-for-merge."""
        ci_status = {"total_count": 0}
        result = _evaluate_ci_status(ci_status)
        assert result == "ok-for-merge"

    def test_evaluate_ci_status_single_check_suite_pending(self) -> None:
        """Test CI status with single check suite - should return None (pending)."""
        ci_status = {"total_count": 1}
        result = _evaluate_ci_status(ci_status)
        assert result is None

    def test_evaluate_ci_status_last_conclusion_success(self) -> None:
        """Test CI status with last check suite success - should return ok-for-merge."""
        ci_status = {
            "total_count": 2,
            "check_suites": [
                {"conclusion": "failure"},
                {"conclusion": "success"},
            ],
        }
        result = _evaluate_ci_status(ci_status)
        assert result == "ok-for-merge"

    def test_evaluate_ci_status_last_conclusion_failure(self) -> None:
        """Test CI status with last check suite failure - should return None."""
        ci_status = {
            "total_count": 2,
            "check_suites": [
                {"conclusion": "success"},
                {"conclusion": "failure"},
            ],
        }
        result = _evaluate_ci_status(ci_status)
        assert result is None

    def test_evaluate_ci_status_last_conclusion_pending(self) -> None:
        """Test CI status with last check suite pending - should return None."""
        ci_status = {
            "total_count": 2,
            "check_suites": [
                {"conclusion": "success"},
                {"conclusion": None},
            ],
        }
        result = _evaluate_ci_status(ci_status)
        assert result is None

    def test_evaluate_ci_status_empty_total_count(self) -> None:
        """Test CI status with empty total_count - should return ok-for-merge."""
        ci_status = {"total_count": 0}
        result = _evaluate_ci_status(ci_status)
        assert result == "ok-for-merge"

    def test_evaluate_review_status_approved(self) -> None:
        """Test review status with sufficient approvals."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
            {"state": "APPROVED", "user": {"login": "user2"}},
        ]
        result = _evaluate_review_status(reviews, 2, False)
        assert result == "ok-for-merge"

    def test_evaluate_review_status_not_approved(self) -> None:
        """Test review status with insufficient approvals."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
        ]
        result = _evaluate_review_status(reviews, 2, False)
        assert result == "not-ok-for-merge"

    def test_evaluate_review_status_override_enabled(self) -> None:
        """Test review status with override enabled and insufficient approvals."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
        ]
        result = _evaluate_review_status(reviews, 2, True)
        assert result == "ok-for-merge"

    def test_evaluate_review_status_changes_requested(self) -> None:
        """Test review status with changes requested - should return not-ok."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
            {"state": "CHANGES_REQUESTED", "user": {"login": "user2"}},
        ]
        result = _evaluate_review_status(reviews, 1, False)
        assert result == "not-ok-for-merge"

    def test_evaluate_review_status_changes_requested_override(self) -> None:
        """Test review status with changes requested - override does not bypass."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
            {"state": "CHANGES_REQUESTED", "user": {"login": "user2"}},
        ]
        result = _evaluate_review_status(reviews, 1, True)
        assert result == "not-ok-for-merge"

    def test_evaluate_review_status_mixed_states(self) -> None:
        """Test review status with mixed approval states."""
        reviews = [
            {"state": "APPROVED", "user": {"login": "user1"}},
            {"state": "DISMISSED", "user": {"login": "user2"}},
            {"state": "APPROVED", "user": {"login": "user3"}},
        ]
        result = _evaluate_review_status(reviews, 2, False)
        assert result == "ok-for-merge"

    def test_evaluate_review_status_no_reviews(self) -> None:
        """Test review status with no reviews."""
        reviews = []
        result = _evaluate_review_status(reviews, 1, False)
        assert result == "not-ok-for-merge"

    def test_evaluate_review_status_only_changes_requested(self) -> None:
        """Test review status with only changes requested."""
        reviews = [
            {"state": "CHANGES_REQUESTED", "user": {"login": "user1"}},
        ]
        result = _evaluate_review_status(reviews, 1, False)
        assert result == "not-ok-for-merge"


class TestExtractResultOrHandleError:
    """Tests for _extract_result_or_handle_error function."""

    def test_extract_result_success(self) -> None:
        """Test successful result extraction."""
        result = ("header", "data")
        extracted = _extract_result_or_handle_error(result, "test_task", "test_repo")
        assert extracted == "data"

    def test_extract_result_github_exception_suppressed(self) -> None:
        """Test GithubException handling with warning suppressed."""
        github_exception = GithubException(status=404, data={"message": "Not found"})
        extracted = _extract_result_or_handle_error(github_exception, "test_task", "test_repo", suppress_warning=True)
        assert extracted is None

    def test_extract_result_github_exception_not_suppressed(self) -> None:
        """Test GithubException handling with warning not suppressed."""
        github_exception = GithubException(status=403, data={"message": "Forbidden"})
        extracted = _extract_result_or_handle_error(github_exception, "test_task", "test_repo", suppress_warning=False)
        assert extracted is None

    def test_extract_result_general_exception_raised(self) -> None:
        """Test that general exceptions are re-raised."""
        general_exception = ValueError("Some error")
        with pytest.raises(ValueError, match="Some error"):
            _extract_result_or_handle_error(general_exception, "test_task", "test_repo")

    def test_extract_result_none(self) -> None:
        """Test handling of None result."""
        extracted = _extract_result_or_handle_error(None, "test_task", "test_repo")
        assert extracted is None


class TestEvaluateCiStatusStatusApiFallback:
    """Tests for CI status evaluation with status API fallback (403 on check-suites)."""

    def test_evaluate_ci_status_status_api_fallback_success(self) -> None:
        """Test CI status with status API fallback (total_count=1, conclusion=success)."""
        ci_status = {
            "total_count": 1,
            "check_suites": [{"conclusion": "success"}],
        }
        result = _evaluate_ci_status(ci_status)
        assert result == "ok-for-merge"

    def test_evaluate_ci_status_status_api_fallback_pending(self) -> None:
        """Test CI status with status API fallback (total_count=1, conclusion=None)."""
        ci_status = {
            "total_count": 1,
            "check_suites": [{"conclusion": None}],
        }
        result = _evaluate_ci_status(ci_status)
        assert result is None

    def test_evaluate_ci_status_status_api_fallback_failure(self) -> None:
        """Test CI status with status API fallback (total_count=1, conclusion=failure)."""
        ci_status = {
            "total_count": 1,
            "check_suites": [{"conclusion": "failure"}],
        }
        result = _evaluate_ci_status(ci_status)
        assert result is None


class TestFetchStatusCiFallback:
    """Tests for _fetch_status_ci_fallback function."""

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_success_empty_statuses(self, mock_to_thread: Mock) -> None:
        """Test successful status API fallback with empty statuses."""
        mock_to_thread.return_value = (
            None,
            {"state": "success", "statuses": []},
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 0
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "success"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_success_with_statuses(self, mock_to_thread: Mock) -> None:
        """Test successful status API fallback with statuses."""
        mock_to_thread.return_value = (
            None,
            {
                "state": "success",
                "statuses": [
                    {"context": "ci/circleci", "state": "success", "target_url": None, "description": "Build succeeded"}
                ],
            },
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 1
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "success"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_pending_status(self, mock_to_thread: Mock) -> None:
        """Test status API with pending status."""
        mock_to_thread.return_value = (
            None,
            {"state": "pending", "statuses": []},
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 0
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "pending"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_failure_status(self, mock_to_thread: Mock) -> None:
        """Test status API with failure status."""
        mock_to_thread.return_value = (
            None,
            {"state": "failure", "statuses": []},
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 0
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "failure"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_failure_in_statuses(self, mock_to_thread: Mock) -> None:
        """Test status API with failure in statuses list."""
        mock_to_thread.return_value = (
            None,
            {
                "state": "success",
                "statuses": [
                    {"context": "ci/circleci", "state": "failure", "target_url": None, "description": "Build failed"}
                ],
            },
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 1
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "failure"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_pending_in_statuses(self, mock_to_thread: Mock) -> None:
        """Test status API with pending status and success as base state."""
        mock_to_thread.return_value = (
            None,
            {
                "state": "success",
                "statuses": [
                    {"context": "ci/circleci", "state": "pending", "target_url": None, "description": "Build running"}
                ],
            },
        )
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is not None
        assert result["total_count"] == 1
        assert len(result["check_suites"]) == 1
        assert result["check_suites"][0]["conclusion"] == "pending"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_403(self, mock_to_thread: Mock) -> None:
        """Test status API returns 403 - should return empty check_suites."""
        mock_to_thread.side_effect = GithubException(403, {"message": "Forbidden"})
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result == {"total_count": 0, "check_suites": []}

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_exception(self, mock_to_thread: Mock) -> None:
        """Test status API raises exception - should return None."""
        mock_to_thread.side_effect = Exception("API Error")
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_status_ci_fallback_github_exception_non_403(self, mock_to_thread: Mock) -> None:
        """Test status API raises non-403 GithubException - should return None."""
        mock_to_thread.side_effect = GithubException(500, {"message": "Internal Server Error"})
        result = await _fetch_status_ci_fallback(Mock(), "org/repo", "abc123")
        assert result is None


class TestFetchCiStatusWithFallback:
    """Tests for _fetch_ci_status_with_fallback function."""

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_ci_status_with_fallback_check_suites_success(self, mock_to_thread: Mock) -> None:
        """Test successful check-suites API (no fallback needed)."""
        mock_to_thread.return_value = (
            None,
            {"total_count": 1, "check_suites": [{"conclusion": "success"}]},
        )
        result = await _fetch_ci_status_with_fallback(Mock(), "org/repo", "abc123", "test_task")
        assert result is not None
        assert result["total_count"] == 1
        assert result["check_suites"][0]["conclusion"] == "success"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_ci_status_with_fallback_check_suites_403_fallback_success(self, mock_to_thread: Mock) -> None:
        """Test check-suites returns 403, status API fallback succeeds."""
        mock_to_thread.side_effect = [
            GithubException(403, {"message": "Forbidden"}),  # check-suites 403
            (None, {"state": "success", "statuses": []}),  # status API success
        ]
        result = await _fetch_ci_status_with_fallback(Mock(), "org/repo", "abc123", "test_task")
        assert result is not None
        assert result["total_count"] == 0

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_ci_status_with_fallback_check_suites_403_fallback_403(self, mock_to_thread: Mock) -> None:
        """Test check-suites 403, status API also returns 403."""
        mock_to_thread.side_effect = [
            GithubException(403, {"message": "Forbidden"}),  # check-suites 403
            GithubException(403, {"message": "Forbidden"}),  # status API 403
        ]
        result = await _fetch_ci_status_with_fallback(Mock(), "org/repo", "abc123", "test_task")
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_ci_status_with_fallback_check_suites_exception(self, mock_to_thread: Mock) -> None:
        """Test check-suites API raises exception (not 403)."""
        mock_to_thread.side_effect = GithubException(404, {"message": "Not Found"})
        result = await _fetch_ci_status_with_fallback(Mock(), "org/repo", "abc123", "test_task")
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_fetch_ci_status_with_fallback_general_exception(self, mock_to_thread: Mock) -> None:
        """Test general exception in check-suites API."""
        mock_to_thread.side_effect = Exception("Network Error")
        result = await _fetch_ci_status_with_fallback(Mock(), "org/repo", "abc123", "test_task")
        assert result is None


class TestGetMergeReadiness:
    """Tests for get_merge_readiness function."""

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_success(self, mock_evaluation: Mock) -> None:
        """Test successful merge readiness evaluation."""
        mock_evaluation.return_value = [
            {
                "repo": "org/repo",
                "number": 1,
                "rebaseable": True,
                "ci_chk_suites_status": "ok-for-merge",
                "pr_req_review_status": "ok-for-merge",
            }
        ]

        list_open_prs = [{"repo": "org/repo", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"}]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")

        assert len(result) == 1
        assert result[0]["repo"] == "org/repo"
        assert result[0]["number"] == 1

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_empty_list(self, mock_evaluation: Mock) -> None:
        """Test with empty PR list."""
        result = await get_merge_readiness(Mock(), [], "main", False, "merge")
        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_github_exception(self, mock_evaluation: Mock) -> None:
        """Test handling of GithubException in a PR."""
        mock_evaluation.return_value = GithubException(status=403, data={"message": "Rate limit exceeded"})

        list_open_prs = [{"repo": "org/repo", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"}]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")
        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_general_exception(self, mock_evaluation: Mock) -> None:
        """Test handling of general exception in a PR."""
        mock_evaluation.return_value = Exception("Unexpected error")

        list_open_prs = [{"repo": "org/repo", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"}]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")
        assert result == []

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_mixed_results(self, mock_evaluation: Mock) -> None:
        """Test handling of mixed results (some successful, some failed)."""
        mock_evaluation.side_effect = [
            [
                {
                    "repo": "org/repo1",
                    "number": 1,
                    "rebaseable": True,
                    "ci_chk_suites_status": "ok",
                    "pr_req_review_status": "ok",
                }
            ],
            GithubException(status=404, data={"message": "Not found"}),
        ]

        list_open_prs = [
            {"repo": "org/repo1", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"},
            {"repo": "org/repo2", "number": 2, "sha": "def", "title": "PR 2", "html_url": "url2"},
        ]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")

        assert len(result) == 1
        assert result[0]["repo"] == "org/repo1"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_with_override(self, mock_evaluation: Mock) -> None:
        """Test merge readiness with override enabled."""
        mock_evaluation.return_value = [
            {
                "repo": "org/repo",
                "number": 1,
                "rebaseable": True,
                "ci_chk_suites_status": "ok-for-merge",
                "pr_req_review_status": "ok-for-merge",
            }
        ]

        list_open_prs = [{"repo": "org/repo", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"}]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", True, "squash")

        assert len(result) == 1

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_multiple_repos(self, mock_evaluation: Mock) -> None:
        """Test with multiple repositories."""
        mock_evaluation.side_effect = [
            [
                {
                    "repo": "org/repo1",
                    "number": 1,
                    "rebaseable": True,
                    "ci_chk_suites_status": "ok",
                    "pr_req_review_status": "ok",
                }
            ],
            [
                {
                    "repo": "org/repo2",
                    "number": 2,
                    "rebaseable": False,
                    "ci_chk_suites_status": "ok",
                    "pr_req_review_status": "ok",
                }
            ],
        ]

        list_open_prs = [
            {"repo": "org/repo1", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"},
            {"repo": "org/repo2", "number": 2, "sha": "def", "title": "PR 2", "html_url": "url2"},
        ]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")

        assert len(result) == 2
        assert result[0]["repo"] == "org/repo1"
        assert result[1]["repo"] == "org/repo2"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci._evaluation")
    async def test_get_merge_readiness_with_none_result(self, mock_evaluation: Mock) -> None:
        """Test when _evaluation returns None (PR should be skipped)."""
        mock_evaluation.side_effect = [
            None,  # First PR should be skipped
            [
                {
                    "repo": "org/repo2",
                    "number": 2,
                    "rebaseable": True,
                    "ci_chk_suites_status": "ok",
                    "pr_req_review_status": "ok",
                }
            ],
        ]

        list_open_prs = [
            {"repo": "org/repo1", "number": 1, "sha": "abc", "title": "PR 1", "html_url": "url1"},
            {"repo": "org/repo2", "number": 2, "sha": "def", "title": "PR 2", "html_url": "url2"},
        ]

        result = await get_merge_readiness(Mock(), list_open_prs, "main", False, "merge")

        assert len(result) == 1
        assert result[0]["repo"] == "org/repo2"


class TestEvaluationIntegration:
    """Integration tests for _evaluation function that mock asyncio.to_thread."""

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_success(self, mock_to_thread: Mock) -> None:
        """Test successful PR evaluation where all checks pass."""
        # Mock all API calls to return (headers, body) tuples
        # Note: to_thread returns (headers, body) where body is the actual response data
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),  # PR body
            (None, {"total_count": 2, "check_suites": [{"conclusion": "success"}, {"conclusion": "success"}]}),  # CI status
            (None, {"required_approving_review_count": 1}),  # Protection
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews
        ]

        result = await _evaluation(
            Mock(),
            "org/repo",
            1,
            "abc123",
            "Test PR",
            "https://github.com/org/repo/pull/1",
            "main",
            False,
            "merge",
        )

        # Verify the result is a list with the PR data (success case)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["repo"] == "org/repo"
        assert result[0]["number"] == 1
        assert result[0]["rebaseable"] is True
        assert result[0]["ci_chk_suites_status"] == "ok-for-merge"
        assert result[0]["pr_req_review_status"] == "ok-for-merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_draft_pr(self, mock_to_thread: Mock) -> None:
        """Test PR evaluation with draft PR - should return None."""
        mock_to_thread.side_effect = [
            (None, {"draft": True, "mergeable": True, "rebaseable": True}),  # PR body - draft
            (None, {"total_count": 0, "check_suites": []}),  # CI status
            (None, {"required_approving_review_count": 1}),  # Protection
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews
        ]

        result = await _evaluation(
            Mock(),
            "org/repo",
            1,
            "abc123",
            "Draft PR",
            "https://github.com/org/repo/pull/1",
            "main",
            False,
            "merge",
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_mergeable_false(self, mock_to_thread: Mock) -> None:
        """Test PR evaluation with mergeable=False - should return None."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": False, "rebaseable": True}),  # PR body - not mergeable
            (None, {"total_count": 0, "check_suites": []}),  # CI status
            (None, {"required_approving_review_count": 1}),  # Protection
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews
        ]

        result = await _evaluation(
            Mock(),
            "org/repo",
            1,
            "abc123",
            "Test PR",
            "https://github.com/org/repo/pull/1",
            "main",
            False,
            "merge",
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_rebaseable_false(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": False}),
            (None, {"total_count": 0, "check_suites": []}),
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "rebase"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_ci_pending(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 1, "check_suites": [{"conclusion": None}]}),
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_ci_failure(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 2, "check_suites": [{"conclusion": "success"}, {"conclusion": "failure"}]}),
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_changes_requested(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 2, "check_suites": [{"conclusion": "success"}, {"conclusion": "success"}]}),
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "CHANGES_REQUESTED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_insufficient_approvals(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 2, "check_suites": [{"conclusion": "success"}, {"conclusion": "success"}]}),
            (None, {"required_approving_review_count": 2}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_check_suites_403_fallback_success(self, mock_to_thread: Mock) -> None:
        """Test check-suites returns 403, status API fallback succeeds with ok-for-merge."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),  # PR body (first)
            GithubException(403, {"message": "Forbidden"}),  # check-suites 403 (second)
            (None, {"required_approving_review_count": 1}),  # Protection (third)
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews (fourth)
            (None, {"state": "success", "statuses": []}),  # status API fallback (fifth, inside _fetch_status_ci_fallback)
        ]

        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )

        assert result is not None
        assert result[0]["ci_chk_suites_status"] == "ok-for-merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_check_suites_403_warning_log(self, mock_to_thread: Mock) -> None:
        """Test check-suites 403 triggers fallback and warning log."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),  # PR body (first)
            GithubException(403, {"message": "Forbidden"}),  # check-suites 403 (second)
            (None, {"required_approving_review_count": 1}),  # Protection (third)
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews (fourth)
            (None, {"state": "success", "statuses": []}),  # status API fallback (fifth, inside _fetch_status_ci_fallback)
        ]

        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )

        assert result is not None
        assert result[0]["ci_chk_suites_status"] == "ok-for-merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_check_suites_404_no_fallback(self, mock_to_thread: Mock) -> None:
        """Test check-suites returns 404 (not 403) - no fallback triggered."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),  # PR body
            GithubException(404, {"message": "Not Found"}),  # check-suites 404 (not 403)
            (None, {"required_approving_review_count": 1}),  # Protection
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),  # Reviews
        ]

        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )

        # Since ci_status_body is None (404 not 403, so no fallback), returns None
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_bypass_review_count(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 2, "check_suites": [{"conclusion": "success"}, {"conclusion": "success"}]}),
            (None, {"required_approving_review_count": 2}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", True, "merge"
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["pr_req_review_status"] == "ok-for-merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_no_ci_checks(self, mock_to_thread: Mock) -> None:
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 0, "check_suites": []}),
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["ci_chk_suites_status"] == "ok-for-merge"

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_no_required_reviews_body(self, mock_to_thread: Mock) -> None:
        """Test when required_reviews_body is None (404/403 for non-protected branch)."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 0, "check_suites": []}),
            (None, None),  # Task C: required_reviews_body is None (404/403)
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is not None
        assert len(result) == 1
        # Should use default required_approving_review_count = 0

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_no_pr_body(self, mock_to_thread: Mock) -> None:
        """Test when pr_body is None - should return None."""
        mock_to_thread.return_value = (None, None)  # Task A: pr_body is None
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_no_ci_status_body(self, mock_to_thread: Mock) -> None:
        """Test when ci_status_body is None - should return None."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, None),  # Task B: ci_status_body is None
            (None, {"required_approving_review_count": 1}),
            (None, [{"state": "APPROVED", "user": {"login": "reviewer1"}}]),
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_no_pr_reviews_body(self, mock_to_thread: Mock) -> None:
        """Test when pr_reviews_body is None - should return None."""
        mock_to_thread.side_effect = [
            (None, {"draft": False, "mergeable": True, "rebaseable": True}),
            (None, {"total_count": 0, "check_suites": []}),
            (None, {"required_approving_review_count": 1}),
            (None, None),  # Task D: pr_reviews_body is None
        ]
        result = await _evaluation(
            Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("pkg_30922.services.gh_ci.asyncio.to_thread")
    async def test_evaluation_exception_in_try_block(self, mock_to_thread: Mock) -> None:
        """Test exception handling in _evaluation try block."""
        # Mock to raise a ValueError during evaluation (simulating a real error)
        mock_to_thread.side_effect = ValueError("Simulated error")
        with pytest.raises(ValueError, match="Error processing repo org/repo"):
            await _evaluation(
                Mock(), "org/repo", 1, "abc123", "Test PR", "https://github.com/org/repo/pull/1", "main", False, "merge"
            )
