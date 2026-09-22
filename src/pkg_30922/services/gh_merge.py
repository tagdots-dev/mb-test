"""
Pull request merge execution services.

This module provides functionality for:
- Executing pull request merges across multiple repositories
- Supporting multiple merge methods (merge, rebase, squash)
- Sequential merge operations to handle base branch advances
- Error handling and logging for batch operations
"""

import asyncio
from typing import List

from github import Github, GithubException


async def _get_latest_base_branch_sha(gh: Github, pr_repo: str, base_branch: str) -> str | None:
    """
    Fetch the latest commit SHA for a repository's base branch.

    This is used to detect if the base branch has moved (e.g., after a merge)
    and to refresh the reference before attempting to merge subsequent PRs.

    Args:
        gh: Authenticated Github client instance.
        pr_repo: Repository full name (e.g., "owner/repo").
        base_branch: Target base branch name.

    Returns:
        The latest commit SHA for the base branch, or None if the API call fails.
    """
    try:
        endpoint = f"/repos/{pr_repo}/branches/{base_branch}"
        _, branch_data = await asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)
        return branch_data["commit"]["sha"]
    except GithubException as err:
        print(f"⚠️  Failed to fetch base branch SHA for {pr_repo} (branch: {base_branch}): {err}")
        return None
    except Exception as err:
        print(f"⚠️  Unexpected error fetching base branch SHA for {pr_repo}: {err}")
        return None


async def put_merge_pr(
    gh: Github, list_mergeable_prs: List[dict], merge_method: str, dry_run: bool, base_branch: str = "main"
) -> List[dict]:
    """
    Execute merge operations for multiple pull requests sequentially.

    Merges PRs one at a time to handle the case where merging one PR
    advances the base branch, which would cause subsequent PRs to have
    stale base branch references.

    Args:
        gh: Authenticated Github client instance.
        list_mergeable_prs: List of PR data dictionaries ready for merging.
        merge_method: Merge strategy ('merge', 'rebase', or 'squash').
        dry_run: If True, no merges are executed (returns empty list).
        base_branch: Target base branch name for fetching latest SHA.

    Returns:
        List of merged PR data dictionaries, or empty list if dry_run is True.
    """
    if dry_run:
        print("❌ Dry-Run Must Be False to Merge")
        return []

    list_merged_prs: List[dict] = []

    for pr in list_mergeable_prs:
        pr_repo = pr["repo"]
        pr_number = pr["number"]
        pr_title = pr["title"]
        pr_url = pr["html_url"]

        # Fetch the latest base branch SHA before each merge to handle base branch advances
        latest_base_sha = await _get_latest_base_branch_sha(gh, pr_repo, base_branch)
        if latest_base_sha is None:
            print(f"⚠️  Skipping PR #{pr_number} in {pr_repo} - could not fetch base branch SHA")
            continue

        try:
            result = await _merge(gh, pr_repo, pr_number, pr_title, pr_url, merge_method)

            if isinstance(result, GithubException):
                # Log error but continue processing other PRs
                print(f"⚠️  Error processing {pr_repo} (PR #{pr_number}): {result}")
            elif isinstance(result, Exception):
                # Log error but continue processing other PRs
                print(f"⚠️  Error processing {pr_repo} (PR #{pr_number}): {result}")
            else:
                # Success - result is a list containing the merged PR data
                list_merged_prs.extend(result)  # type: ignore[arg-type]
        except GithubException as err:
            print(f"⚠️  Error processing {pr_repo} (PR #{pr_number}): {err}")
        except Exception as err:
            print(f"⚠️  Error processing {pr_repo} (PR #{pr_number}): {err}")

    print(f"✅ Final Merged Open PR Info     :: {len(list_merged_prs)}")
    for pr in list_merged_prs:
        print(f'   ▪ PR: {pr["html_url"]} (title: {pr["title"]})')

    return list_merged_prs


async def _merge(gh: Github, pr_repo: str, pr_number: int, pr_title: str, pr_url: str, merge_method: str) -> List[dict]:
    """
    Execute merge operation for a single pull request.

    Args:
        gh: Authenticated Github client instance.
        pr_repo: Repository full name (e.g., "owner/repo").
        pr_number: Pull request number to merge.
        pr_title: Pull request title for logging.
        pr_url: Pull request URL for reference.
        merge_method: Merge strategy ('merge', 'rebase', or 'squash').

    Returns:
        List containing the merged PR data dictionary.

    Raises:
        ValueError: If GitHub API error or other exception occurs.
    """
    try:
        list_merged_prs = []

        hdrs = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
        payload = {
            "merge_method": merge_method,
            "commit_title": f"Auto-merge PR #{pr_number}",
        }
        url = f"/repos/{pr_repo}/pulls/{pr_number}/merge"
        resp_hdrs, task_merge = await asyncio.to_thread(
            gh.requester.requestJsonAndCheck, "PUT", url, headers=hdrs, input=payload
        )

        list_merged_prs.append({"html_url": pr_url, "title": pr_title})

        return list_merged_prs

    except GithubException as err:
        error_msg = f"GitHub API error for repo {pr_repo}: {err.status}"
        if err.data:
            error_msg += f" - {err.data}"
        raise ValueError(error_msg)

    except Exception as err:
        raise ValueError(f"Error processing repo {pr_repo}: {err}")
