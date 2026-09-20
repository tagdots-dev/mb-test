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

    print(f"✅ Open PR Ready For Merge Info  :: {len(list_mergeable_prs)}")
    for mpr in list_mergeable_prs:
        print(
            f"   ▪ Repo: {mpr["repo"]} (PR #{mpr["number"]}) -> "
            f"Mergeable: True, "
            f"Rebaseable: {mpr["rebaseable"]}, "
            f"CI status checks: {mpr["ci_chk_suites_status"]}, "
            f"Approval Review checks: {mpr["pr_req_review_status"]}"
        )

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
        ci_status_body = _extract_result_or_handle_error(results[1], "CI status fetch", pr_repo)

        # Task C result (index 2)
        # Handle req_reviews result - if it fails with 404/403, it means no branch protection
        # GitHub returns 404 when no protection rules exist on the branch
        # Suppress warning for Task C since 404/403 is expected for non-protected branches
        req_reviews_body = _extract_result_or_handle_error(
            results[2], "Required review count fetch", pr_repo, suppress_warning=True
        )
        if not req_reviews_body:
            req_reviews_body = {"required_approving_review_count": 0}

        # Task D result (index 3)
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


def _evaluate_ci_status(ci_status_body: dict) -> str | None:
    """
    Evaluate CI status and return merge readiness.

    Checks the latest check-suite conclusion to determine if CI is passing.

    Args:
        ci_status_body: The CI status response from GitHub API (check-suites endpoint).

    Returns:
        "ok-for-merge" if CI passed (no check-suites or latest is success),
        None if PR should be skipped (pending approval or CI failed).
    """
    check_suites_total_count = ci_status_body.get("total_count", 0)

    if check_suites_total_count == 0:
        return "ok-for-merge"

    if check_suites_total_count == 1:
        return None  # check-suites pending approval to run

    # check_suites_total_count: 2 - check the last one's conclusion
    conclusion = ci_status_body["check_suites"][-1].get("conclusion")
    if conclusion == "success":
        return "ok-for-merge"

    return None  # Skip PR


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
