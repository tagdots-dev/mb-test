"""
Pull request retrieval and filtering services.

This module provides functionality for:
- Fetching open pull requests from multiple repositories
- Filtering PRs by base branch, labels, and title prefix
- Concurrent processing using asyncio for efficiency
"""

import asyncio
from typing import List, Sequence

from github import Github, GithubException, Repository


async def get_open_prs(
    gh: Github,
    repos: Sequence[Repository.Repository],
    base_branch: str,
    set_exclude_labels: set,
    set_include_labels: set,
    prefix: str,
) -> List[dict]:
    """
    Get all open pull requests from multiple repositories filtered by PR labels, title prefix, base branch in parallel.

    Uses asyncio.gather to process all repositories concurrently, significantly reducing total execution time compared
    to sequential processing. If a repository fails to process (e.g., API error), it is logged and processing continues
    for other repositories.

    Args:
        gh: Authenticated Github client instance.
        repos: Sequence of Repository objects from PyGithub.
        base_branch: Target base branch name (only PRs targeting this branch are returned).
        set_exclude_labels: Set of label names to exclude to filter by (PRs matching any label are returned).
        set_include_labels: Set of label names to include to filter by (PRs matching any label are returned).
        prefix: Optional title prefix filter (case-insensitive).

    Returns:
        List of dictionaries containing PR data for all open PRs across all repos.
        Each dictionary contains:
        - repo: Repository full name string (e.g., "owner/repo")
        - number: Pull request number
        - title: Pull request title
        - sha: Pull request head commit SHA
        - html_url: Pull request URL

    Raises:
        Exception: Errors are logged but do not stop processing of other repos.
    """
    if not repos:
        return []

    # Process all repos in parallel using gather
    # return_exceptions=True ensures one repo failure doesn't stop processing of all others
    tasks = [_filter_prs(gh, repo, base_branch, set_exclude_labels, set_include_labels, prefix) for repo in repos]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    list_open_prs = []
    for repo, result in zip(repos, results):
        if isinstance(result, GithubException):
            # Log error but continue processing other repos
            print(f"⚠️  Error processing {repo.full_name}: {result}")
        elif isinstance(result, Exception):
            # Log error but continue processing other repos
            print(f"⚠️  Error processing {repo.full_name}: {result}")
        elif isinstance(result, list):
            list_open_prs.extend(result)

    print(f"✅ Starting Open PR Information  :: {len(list_open_prs)}")
    for pr in list_open_prs:
        print(f"   ▪ PR: {pr["html_url"]} (title: {pr["title"]})")

    return list_open_prs


async def _filter_prs(
    gh: Github, repo: Repository.Repository, base_branch: str, set_exclude_labels: set, set_include_labels: set, prefix: str
) -> List[dict] | None:
    """Get open pull requests for a single repository filtered by label using asyncio.to_thread.

    This function wraps blocking PyGithub API calls in asyncio.to_thread to avoid
    blocking the event loop during concurrent processing of multiple repositories.

    Args:
        gh: Authenticated Github client instance.
        repo: Repository object from PyGithub.
        base_branch: Target base branch name.
        set_exclude_labels: Set of label names to exclude to filter by.
        set_include_labels: Set of label names to include to filter by.
        prefix: Optional title prefix filter.

    Returns:
        List of dictionaries containing PR data, or None if no open PRs or no matching labels.
        Each dictionary contains:
        - repo: Repository full name string
        - number: Pull request number
        - title: Pull request title
        - sha: Pull request head commit SHA
        - html_url: Pull request URL

    Raises:
        ValueError: If a GitHub API error or other exception occurs.
    """
    try:
        # Grab up to 100 open PRs targeting base branch in 1 API call per Repository
        endpoint = f"/repos/{repo.full_name}/pulls?state=open&base={base_branch}&per_page=100"
        _, open_repo_prs = await asyncio.to_thread(gh.requester.requestJsonAndCheck, "GET", endpoint)

        pr_list = []
        if not open_repo_prs:
            return

        # Iterate through open_repo_prs
        for pr in open_repo_prs:
            # Access PR title from PR data
            if prefix:
                if not pr["title"].lower().startswith(prefix.lower()):
                    continue

            # Access PR labels from PR data
            list_pr_labels = [pr_label["name"].lower() for pr_label in pr.get("labels", [])]

            # Check if PR has any matching exclude labels (or if no exclude labels filter is set)
            if not set_exclude_labels:
                pr_labels_match = True
            else:
                # Convert set_label to lowercase for case-insensitive comparison
                set_label_lower = {lbl.lower() for lbl in set_exclude_labels}
                pr_labels_match = any(lbl in set_label_lower for lbl in list_pr_labels)
                if pr_labels_match:
                    continue

            # Check if PR has any matching include labels (or if no include labels filter is set)
            if not set_include_labels:
                pr_labels_match = True
            else:
                # Convert set_label to lowercase for case-insensitive comparison
                set_label_lower = {lbl.lower() for lbl in set_include_labels}
                pr_labels_match = any(lbl in set_label_lower for lbl in list_pr_labels)

            if pr_labels_match:
                pr_list.append(
                    {
                        "repo": repo.full_name,
                        "number": pr["number"],
                        "title": pr["title"],
                        "sha": pr["head"]["sha"],
                        "html_url": pr["html_url"],
                    }
                )
                # # DEBUG ONLY
                # for key, value in pr.items():
                #     if key in ["head", "base", "body"]:
                #         continue
                #     print(f"Key: {key} -> Value: {value}")

        if not pr_list:
            return

        return pr_list

    except GithubException as err:
        raise ValueError(f"GitHub API error for repo {repo}: {err.status}")
    except Exception as err:
        raise ValueError(f"Error processing repo {repo}: {err}")
