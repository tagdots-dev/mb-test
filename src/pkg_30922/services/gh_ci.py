"""
Merge readiness evaluation services.

This module provides functionality for:
- Evaluating pull request merge readiness based on CI status
- Checking required code review approvals
- Determining if PRs can be merged (mergeable status)
- Concurrent evaluation across multiple PRs

The evaluation process checks:
1. PR must be mergeable and not be a draft
2. CI status (check-suites conclusion) - must be "success" or no check-suites
3. Required code review approvals - must meet branch protection requirements
4. Review status - no "CHANGES_REQUESTED" from any reviewer
"""

import asyncio
import logging
from typing import (
    Any,
    List,
    Tuple,
    cast,
)

from github import Github, GithubException

# Configure logging to suppress GitHub library's 403 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("github").setLevel(logging.ERROR)


async def get_merge_readiness(
    gh: Github, list_open_prs: List[dict], base_branch: str, bypass_review_count: bool, merge_method: str
) -> List[dict]:
    """
    Evaluate merge readiness for a list of open pull requests.

    Performs concurrent evaluation of each PR's merge readiness by checking:
    - CI status (check-suites conclusion) - must be "success" or no check-suites
    - Required code review approvals - must meet branch protection requirements
    - Mergeability status - PR must not be a draft
    - Review status - no "CHANGES_REQUESTED" from any reviewer

    Args:
        gh: Authenticated Github client instance.
        list_open_prs: List of PR data dictionaries (from get_open_prs).
        base_branch: Target base branch name for branch protection checks.
        bypass_review_count: Whether to bypass required approval count.
        merge_method: Preferred merge method ('merge', 'rebase', or 'squash').

    Returns:
        List of PR data dictionaries that are ready for merging, including:
        - repo: Repository full name
        - number: PR number
        - title: PR title
        - html_url: PR URL
        - rebaseable: Whether PR can be rebased
        - ci_chk_suites_status: CI status
        - pr_req_review_status: Review approval status
    """
    print("✅ Finding PR Ready For Merge...")
    tasks = [
        _evaluation(
            gh,
            pr["repo"],
            pr["number"],
            pr["sha"],
            pr["title"],
            pr["html_url"],
            base_branch,
            bypass_review_count,
            merge_method,
        )
        for pr in list_open_prs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    list_mergeable_prs = []
    for pr_data, result in zip(list_open_prs, results):
        if isinstance(result, GithubException):
            # Log error but continue processing other PRs
            print(f"⚠️  Error processing {pr_data['repo']} (PR #{pr_data['number']}): {result}")
        elif isinstance(result, Exception):
            # Log error but continue processing other PRs
            print(f"⚠️  Error processing {pr_data['repo']} (PR #{pr_data['number']}): {result}")
        elif isinstance(result, list):
            list_mergeable_prs.extend(result)

    for mpr in list_mergeable_prs:
        print(
            f"   ▪ Repo: {mpr["repo"]} (PR #{mpr["number"]}) -> "
            f"Mergeable: True, "
            f"Rebaseable: {mpr["rebaseable"]}, "
            f"CI status checks: {mpr["ci_chk_suites_status"]}, "
            f"Approval Review checks: {mpr["pr_req_review_status"]}"
        )
    print(f"   Total Number of Mergeable PR :: {len(list_mergeable_prs)}\n")
    return list_mergeable_prs


async def _evaluation(
    gh: Github,
    pr_repo: str,
    pr_number: int,
    pr_sha: str,
    pr_title: str,
    pr_url: str,
    base_branch: str,
    bypass_review_count: bool,
    merge_method: str,
) -> List[dict] | None:
    """
    Evaluate merge readiness for a single pull request.

    Performs concurrent API calls to fetch:
    - PR details (draft, mergeable, rebaseable)
    - CI status (check-suites conclusion)
    - Required approving review count (branch protection)
    - PR reviews history (approval status)

    The PR is ok to merge if:
    1. It is not a draft and mergeable (clean to merge)
    2. CI check-suites status is "success" or no check-suites
    3. Has sufficient approving reviews (meets branch protection requirements)
    4. No "CHANGES_REQUESTED" review status

    Args:
        gh: Authenticated Github client instance.
        pr_repo: Repository full name (e.g., "owner/repo").
        pr_number: Pull request number.
        pr_sha: Head commit SHA.
        pr_title: Pull request title.
        pr_url: Pull request URL.
        base_branch: Target base branch name.
        bypass_review_count: Whether to bypass required approval count.
        merge_method: Preferred merge method ('merge', 'rebase', or 'squash').

    Returns:
        List containing PR data if mergeable, or empty list if not ready.
        PR data includes: repo, number, title, html_url, rebaseable,
        ci_chk_suites_status, pr_req_review_status.
    """
    try:
        mergeable_pr_list = []

        """Task A: Fetch specific PR detail (read draft, mergeable, rehashable)
        """
        endpoint = f"/repos/{pr_repo}/pulls/{pr_number}"
        task_pr_body = asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)

        """Task B: Fetch combined CI Status for the head commit
        """
        endpoint = f"/repos/{pr_repo}/commits/{pr_sha}/check-suites"
        hdrs = {"Accept": "application/vnd.github+json"}
        task_ci_status = asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint, parameters=None, headers=hdrs)

        """Task C. Fetches the number of required approving reviews configured for a branch
        """
        endpoint = f"/repos/{pr_repo}/branches/{base_branch}/protection/required_pull_request_reviews"
        task_req_reviews = asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)

        """Task D: Fetch the chronological list of reviews for this PR
        """
        endpoint = f"/repos/{pr_repo}/pulls/{pr_number}/reviews"
        task_pr_reviews = asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)

        """Execute tasks concurrently
        """
        results = await asyncio.gather(
            task_pr_body, task_ci_status, task_req_reviews, task_pr_reviews, return_exceptions=True
        )

        # Task A result (index 0)
        pr_body = _extract_result_or_handle_error(results[0], "PR fetch", pr_repo)

        # Task B result (index 1)
        # Suppress 403 warning since we have a fallback to status API
        ci_status_body = _extract_result_or_handle_error(results[1], "CI status fetch", pr_repo, suppress_warning=True)

        # If check-suites returns 403 (common with fine-grained PATs on private repos with no suites),
        # fall back to status API to get CI test results
        if ci_status_body is None and results[1] is not None and isinstance(results[1], GithubException):
            if results[1].status == 403:
                # Try status API as fallback
                # print(f"⚠️  Check-suites API returned 403 for {pr_repo}, falling back to status API")
                ci_status_body = await _fetch_status_ci_fallback(gh, pr_repo, pr_sha)

        # Task C result (index 2) - task_req_reviews
        # Handle req_reviews result - if it fails with 404/403, it means no branch protection
        # GitHub returns 404 when no protection rules exist on the branch
        # Suppress warning for Task C since 404/403 is expected for non-protected branches
        req_reviews_body = _extract_result_or_handle_error(
            results[2], "Required review count fetch", pr_repo, suppress_warning=True
        )
        if not req_reviews_body:
            req_reviews_body = {"required_approving_review_count": 0}

        # Task D result (index 3) - task_pr_reviews
        pr_reviews_body = _extract_result_or_handle_error(results[3], "PR reviews fetch", pr_repo)

        """
        | =============================================================================================================== |
        |                                           Task A. Inspect PR Details                                            |
        | Draft      : If the code is a WIP and not meant for merge (bool)                                                |
        | Mergeable  : If the PR has no merge conflicts and can be cleanly integrated (bool)                              |
        | Rebaseable : If the PR commits can be cleanly reapplied on top of the latest base branch w/o conflict using     |
        |              "Rebase and merge" strategy (bool)                                                                 |
        | =============================================================================================================== |
        """
        if not pr_body:
            return

        pr_draft = pr_body["draft"]
        pr_mergeable = pr_body["mergeable"]
        pr_rebaseable = pr_body["rebaseable"]

        if pr_draft or not pr_mergeable:
            return

        if not pr_rebaseable and merge_method in ["rebase"]:
            return

        """
        | =============================================================================================================== |
        |                                           Task B. Inspect Check Suites                                          |
        | status     : If all runs are completed                                                                          |
        | conclusion : If all runs are in [success, skipped, neutral]                                                     |
        | =============================================================================================================== |
        """
        if not ci_status_body:
            # DEBUG ONLY # print(f"⚠️  CI status body is None, skipping PR {pr_url}")
            return

        ci_chk_suites_status = _evaluate_ci_status(ci_status_body)

        if ci_chk_suites_status is None:
            return

        """
        | =============================================================================================================== |
        |                               Task C. Inspect the number of required approving reviews                          |
        | =============================================================================================================== |
        """
        required_review_count = req_reviews_body["required_approving_review_count"]
        # DEBUG ONLY # print(f"✅ Req'd no. of approving review :: {required_review_count}")

        """
        | =============================================================================================================== |
        |                                    Task D. Inspect PR Approval Reviews                                          |
        | =============================================================================================================== |
        | Approval Reviews range from 0 to many ([] to [{id: 123, ...}, {id: 234, ...}, {id: 345, ...}])                  |
        | Notes:                                                                                                          |
        | - Bypass review count only applies when the number of approval reviews is not met                               |
        | - Bypass review count does not override "change request"                                                        |
        | =============================================================================================================== |
        | Req'd number of       | Number of               | Change Request?  | Bypass Review       | Review Status        |
        | Approval Review       | Approval Review         |                  | Count?              |                      |
        | --------------------------------------------------------------------------------------------------------------- |
        | required_review_count | latest_approval_count   | has_active_      | bypass_review_count | pr_req_review_status |
        |                       |                         | change_request   |                     |                      |
        | --------------------------------------------------------------------------------------------------------------- |
        | 0                     | >= 0                    | False            | ANY                 | ok-for-merge     (1) |
        | 1 or more             | < required_review_count | False            | True                | ok-for-merge     (2) |
        | 1 or more             | < required_review_count | False            | False               | not-ok-for-merge (3) |
        | 0                     | >= 0                    | True             | ANY                 | not-ok-for-merge (4) |
        | --------------------------------------------------------------------------------------------------------------- |
        """
        pr_req_review_status = ""

        # If PR reviews API call failed with Exception (None, not empty list)
        # Skip PR Approval Review Processing
        if pr_reviews_body is None:
            return

        pr_req_review_status = _evaluate_review_status(pr_reviews_body, required_review_count, bypass_review_count)

        if pr_req_review_status == "not-ok-for-merge":
            return

        """
        | =============================================================================================================== |
        |                                               PR Ready for Merge Matrix                                         |
        | =============================================================================================================== |
        | bypass_review_count | mergeable  | rebaseable | merge_method   | ci_chk_suites_status  | pr_req_review_status   |
        | --------------------------------------------------------------------------------------------------------------- |
        | ANY                 | True       | True       | ANY            | ok-for-merge           | ok-for-merge          |
        | False               | True       | False      | ANY but rebase | ok-for-merge           | ok-for-merge          |
        | --------------------------------------------------------------------------------------------------------------- |
        """
        mergeable_pr_list.append(
            {
                "repo": pr_repo,
                "number": pr_number,
                "html_url": pr_url,
                "title": pr_title,
                "rebaseable": pr_rebaseable,
                "ci_chk_suites_status": ci_chk_suites_status,
                "pr_req_review_status": pr_req_review_status,
            }
        )

        return mergeable_pr_list

    except Exception as err:
        raise ValueError(f"Error processing repo {pr_repo}: {err}")


def _extract_result_or_handle_error(result: Any, task_name: str, repo: str, suppress_warning: bool = False) -> Any | None:
    """
    Extract result data from a task result, handling exceptions gracefully.

    Args:
        result: The result from an async task.
        task_name: Name of the task for logging purposes.
        repo: Repository name for error context.
        suppress_warning: Whether to suppress warning messages.

    Returns:
        Extracted data (tuple[1]) if successful, None if a GithubException
        occurred (with optional warning logged), or raises other exceptions.
    """
    if result is None:
        return None
    if isinstance(result, GithubException):
        if not suppress_warning:
            print(f"⚠️  {task_name} failed for {repo}: {result}")
        return None
    elif isinstance(result, Exception):
        # Re-raise non-GithubException exceptions for higher-level handling
        raise result
    else:
        return cast(Tuple[Any, Any], result)[1]


async def _fetch_ci_status_with_fallback(gh: Any, pr_repo: str, pr_sha: str, task_name: str) -> dict | None:
    """
    Fetch CI status, falling back to status API if check-suites returns 403.

    Fine-grained PATs on private repos with zero check-suites return 403 instead of empty array.
    In this case, we fall back to the status API to get CI test results.

    Args:
        gh: Authenticated Github client instance.
        pr_repo: Repository full name.
        pr_sha: Commit SHA.
        task_name: Name of the task for error logging.

    Returns:
        CI status body dict with check_suites or status data, or None if both APIs fail.
    """
    # First, try check-suites API
    endpoint = f"/repos/{pr_repo}/commits/{pr_sha}/check-suites"
    hdrs = {"Accept": "application/vnd.github+json"}
    try:
        _, ci_status = await asyncio.to_thread(
            gh.requester.requestJsonAndCheck, "GET", endpoint, parameters=None, headers=hdrs
        )
        return ci_status
    except GithubException as e:
        if e.status == 403:
            # Check-suites API returned 403 (likely fine-grained PAT on private repo with no suites)
            # Fall back to status API
            # print(f"⚠️  Check-suites API returned 403 for {pr_repo}, falling back to status API")
            endpoint = f"/repos/{pr_repo}/commits/{pr_sha}/status"
            try:
                _, status_body = await asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)
                # Convert status API format to check-suites format for compatibility
                # status API returns: state (success/pending/failure), statuses (list)
                # We convert to check-suites-like format
                return _convert_status_to_check_suites_format(status_body)
            except GithubException as e2:
                print(f"⚠️  Status API fallback also failed for {pr_repo}: {e2}")
                return None
        else:
            print(f"⚠️  Check-suites API failed for {pr_repo}: {e}")
            return None
    except Exception as e:
        print(f"⚠️  CI status fetch failed for {pr_repo}: {e}")
        return None


def _evaluate_ci_status(ci_status_body: dict) -> str | None:
    """
    Evaluate CI status and return merge readiness.

    Checks all check-suites status and conclusion to determine if CI is passing.
    Handles responses from both check-suites API and status API fallback.

    Args:
        ci_status_body: The CI status response from GitHub API.

    Returns:
        "ok-for-merge" if:
            - No CI checks (total_count == 0), OR
            - All check suites have status="completed" and conclusion in ["success", "skipped", "neutral"]
        None if PR should be skipped (pending, failed, or incomplete checks).
    """

    check_suites_total_count = ci_status_body.get("total_count", 0)

    if check_suites_total_count == 0:
        return "ok-for-merge"

    # At this point, check_suites_total_count > 0
    check_suites = ci_status_body.get("check_suites", [])
    if check_suites:
        for suite in check_suites:
            status = suite.get("status")
            conclusion = suite.get("conclusion")

            # Every status MUST be "completed"
            if status != "completed":
                return None

            # Every conclusion must be one of ["success", "skipped", "neutral"]
            if conclusion not in ["success", "skipped", "neutral"]:
                return None

        # All checks passed
        return "ok-for-merge"

    return None  # Skip PR if no check_suites or empty check_suites


async def _fetch_status_ci_fallback(gh: Any, pr_repo: str, pr_sha: str) -> dict | None:
    """
    Fallback to status API when check-suites returns 403.

    Fine-grained PATs on private repos may return 403 from check-suites API
    (even when there are no check suites). We fall back to status API to
    determine CI status. If status API also returns 403, we treat it as
    having no CI checks (ok-for-merge).

    Args:
        gh: Authenticated Github client instance.
        pr_repo: Repository full name.
        pr_sha: Commit SHA.

    Returns:
        CI status body dict in check-suites-like format, or None if API fails.
        Returns {"total_count": 0, "check_suites": []} if both APIs return 403.
    """
    endpoint = f"/repos/{pr_repo}/commits/{pr_sha}/status"
    try:
        _, status_body = await asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)
        # Convert status API format to check-suites-like format for compatibility
        return _convert_status_to_check_suites_format(status_body)
    except GithubException as e:
        if e.status == 403:
            # Status API also returns 403 - treat as "no CI checks" = ok-for-merge
            print(f"⚠️  Status API fallback also returned 403 for {pr_repo}, treating as no CI checks")
            return {"total_count": 0, "check_suites": []}
        print(f"⚠️  Status API fallback also failed for {pr_repo}: {e}")
        return None
    except Exception as e:
        print(f"⚠️  Status API fallback also failed for {pr_repo}: {e}")
        return None


def _convert_status_to_check_suites_format(status_body: dict) -> dict:
    """
    Convert status API response to check-suites-like format for compatibility.

    Status API returns:
    - state: 'success', 'pending', or 'failure'
    - statuses: list of status contexts with state

    Check-suites format:
    - total_count: number of CI checks (0 if no statuses)
    - check_suites: list with conclusion (success, neutral, failure, etc.)

    Args:
        status_body: Response from status API

    Returns:
        Dict in check-suites-like format with total_count and check_suites
    """
    state = status_body.get("state", "failure")
    statuses = status_body.get("statuses", [])

    # Map status state to check-suites conclusion
    # success -> success, pending -> pending, failure -> failure
    if state == "success":
        conclusion = "success"
    elif state == "pending":
        conclusion = "pending"
    else:  # failure or unknown
        conclusion = "failure"

    # Process individual statuses to determine worst outcome
    for s in statuses:
        s_state = s.get("state", "")
        if s_state == "failure":
            conclusion = "failure"
            break
        elif s_state == "pending" and conclusion == "success":
            conclusion = "pending"

    # Determine total_count: if no statuses, treat as no CI checks (0)
    total_count = len(statuses) if statuses else 0

    return {
        "total_count": total_count,
        "check_suites": [
            {
                "conclusion": conclusion,
                "status": conclusion if conclusion in ["success", "neutral", "failure"] else "completed",
            }
        ],
    }


def _evaluate_review_status(pr_reviews_body: list[dict], required_review_count: int, bypass_review_count: bool) -> str:
    """
    Evaluate review status and return merge readiness.

    Analyzes PR reviews to determine if the PR has sufficient approvals:
    - Collects latest review from each reviewer
    - Checks for any "CHANGES_REQUESTED" status (blocks merge)
    - Verifies sufficient "APPROVED" reviews meet required count

    Args:
        pr_reviews_body: List of PR reviews from GitHub API.
        required_review_count: Required number of approving reviews per branch protection.
        bypass_review_count: Whether to bypass required review count.

    Returns:
        "ok-for-merge" if all checks pass,
        "not-ok-for-merge" if blocked by changes requested or insufficient approvals.
    """
    latest_approval_reviews: dict[str, str] = {}

    for review in pr_reviews_body:
        state = review.get("state", "")
        if state in ["APPROVED", "CHANGES_REQUESTED"]:
            user = review["user"]["login"]
            latest_approval_reviews[user] = state

    latest_approval_count = sum(1 for state in latest_approval_reviews.values() if state == "APPROVED")
    has_active_change_request = any(state == "CHANGES_REQUESTED" for state in latest_approval_reviews.values())

    if has_active_change_request:
        return "not-ok-for-merge"

    if latest_approval_count < required_review_count:
        if bypass_review_count:
            return "ok-for-merge"
        return "not-ok-for-merge"

    return "ok-for-merge"
