"""
Pull request merge execution services.

This module provides functionality for:
- Executing pull request merges across multiple repositories
- Supporting multiple merge methods (merge, rebase, squash)
- Concurrent merge operations using asyncio
- Error handling and logging for batch operations
"""

import asyncio
from typing import List

from github import Github, GithubException


async def put_merge_pr(gh: Github, list_mergeable_prs: List[dict], merge_method: str, dry_run: bool) -> List[dict]:
    """
    Execute merge operations for multiple pull requests.

    Performs concurrent merging of PRs that have been evaluated as mergeable.

    Args:
        gh: Authenticated Github client instance.
        list_mergeable_prs: List of PR data dictionaries ready for merging.
        merge_method: Merge strategy ('merge', 'rebase', or 'squash').
        dry_run: If True, no merges are executed (returns None).

    Returns:
        List of merged PR data dictionaries, or None if dry_run is True.
    """
    if dry_run:
        print("❌ Dry-Run Must Be False to Merge")
        return []

    tasks = [_merge(gh, pr["repo"], pr["number"], pr["title"], pr["html_url"], merge_method) for pr in list_mergeable_prs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    list_merged_prs = []
    for pr_data, result in zip(list_mergeable_prs, results):
        if isinstance(result, GithubException):
            # Log error but continue processing other PRs
            print(f"⚠️  Error processing {pr_data['repo']} (PR #{pr_data['number']}): {result}")
        elif isinstance(result, Exception):
            # Log error but continue processing other PRs
            print(f"⚠️  Error processing {pr_data['repo']} (PR #{pr_data['number']}): {result}")
        else:
            # With return_exceptions=True, result must be a list here (Exception cases handled above)
            # type: ignore - Pylance doesn't understand the type narrowing from isinstance checks above
            list_merged_prs.extend(result)  # type: ignore[arg-type]

    print(f"✅ Final Merged Open PR Info     :: {len(list_merged_prs)}")
    for pr in list_merged_prs:
        print(f"   ▪ PR: {pr["html_url"]} (title: {pr["title"]})")

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
