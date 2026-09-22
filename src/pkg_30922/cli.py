"""
CLI tool to automate pull request merging.

This module provides functionality to:
- Get a list of repositories across organizations and users
- Filter repositories with open pull requests
- Filter pull requests by label, base branch, title prefix, and owner
- Evaluate merge readiness based on CI status and code review approvals
- Execute batch merge operations across multiple repositories

Key Features:
- Concurrent processing using asyncio for efficiency
- Support for dry-run mode to preview merges without executing
- Filtering by multiple criteria (labels, branch, prefix, owner)
- Merge method selection (merge, rebase, squash)
- Bypass review count option to merge without sufficient approvals
"""

import asyncio
import os
import sys
from typing import Optional

import asyncclick as click

from pkg_30922 import (
    __version__,
    get_auth,
    get_merge_readiness,
    get_open_prs,
    get_repos_from_all,
    get_repos_from_owner,
    get_token_user_info,
    put_merge_pr,
)
from pkg_30922.config import Config, load_config, merge_config_with_cli

ALLOWED_REPO_TYPES = ["all", "private", "public"]
ALLOWED_MERGE_METHODS = ["merge", "rebase", "squash"]


class CustomError(Exception):
    pass


def check_owner(owner: str, orgs: list[str], login: str) -> None:
    """
    Validate that the owner is valid for the authenticated token.

    Args:
        owner: The owner to validate (username or organization name).
        orgs: List of organizations the token has access to.
        login: The authenticated user's login name.

    Raises:
        CustomError: If owner is not in orgs and doesn't match the token owner.
    """
    if owner:
        if owner not in orgs and owner != login:
            raise CustomError("CLI option '--owner' is invalid (mismatch what the token suggests)")


def find_config_file() -> Optional[str]:
    """
    Find configuration file for GitHub Actions users.

    Searches for config file at the default location (./config/default.yaml).

    Returns:
        Path to config file if found, None otherwise.
    """
    config_locations = ["./config/default.yaml"]

    for location in config_locations:
        if os.path.exists(location):
            return location

    return None


def check_repo_type(repo_type: str) -> None:
    """
    Validate the repository type option.

    Args:
        repo_type: The repository type to validate.

    Raises:
        CustomError: If repo_type is not one of 'all', 'private', or 'public'.
    """
    if repo_type:
        if not repo_type.strip().lower() in ALLOWED_REPO_TYPES:
            raise CustomError("CLI option '--repo-type' requires all or private or public")


def check_merge_method(merge_method: str) -> None:
    """
    Validate the merge method option.

    Args:
        merge_method: The merge method to validate.

    Raises:
        CustomError: If merge_method is not one of 'merge', 'rebase', or 'squash'.
    """
    if merge_method:
        if not merge_method.strip().lower() in ALLOWED_MERGE_METHODS:
            raise CustomError("CLI option '--merge-method' requires merge, rebase, or squash")


def print_summary(number_of_open_prs: int, number_of_mergeable_prs: int, number_of_merged_prs: int) -> None:
    """
    Print summary

    Args:
        number_of_open_prs: Number of open pull requests
        number_of_mergeable_prs: Number of mergeable pull requests
        number_of_merged_prs: Number of merged pull requests
    """
    dict_summary = {}
    dict_summary["open-prs"] = number_of_open_prs
    dict_summary["mergeable-prs"] = number_of_mergeable_prs
    dict_summary["merged-prs"] = number_of_merged_prs
    print()
    print(f"🎉 Merge Pull Request Summary :: {dict_summary}")


@click.command()
@click.option("--base-branch", type=str, default="main", help="Restrict to a particular base-branch [case-sensitive]")
@click.option("--bypass-review-count", type=bool, default=False, help="Bypass required review count (default: false)")
@click.option("--exclude-labels", type=str, default="", help="Restrict to particular labels to excldue")
@click.option("--include-labels", type=str, default="", help="Restrict to particular labels to incldue")
@click.option("--merge-method", type=str, default="merge", help="merge|rebase|squash (default: merge)")
@click.option("--owner", type=str, default="", help="Restrict to a particular user/org")
@click.option("--prefix", type=str, default="", help="Restrict to a PR title prefix")
@click.option("--repo-type", type=str, default="all", help="all|private|public (default: all)")
@click.option("--dry-run", type=bool, default=True, help="Show PR ready for merge (default: true)")
@click.version_option(version=__version__)
async def main(
    base_branch: str,
    dry_run: bool,
    exclude_labels: str,
    include_labels: str,
    merge_method: str,
    bypass_review_count: bool,
    owner: str,
    prefix: str,
    repo_type: str,
) -> None:
    """
    Main CLI entry point to merge pull requests

    \f
    Executes the complete workflow:
    1. Load configuration (YAML file or defaults)
    2. Validate and merge CLI arguments with config
    3. Authenticate with GitHub API
    4. Discover repositories
    5. Fetch and filter open pull requests
    6. Evaluate merge readiness (CI + reviews)
    7. Execute merge operations (or dry-run)
    """
    config_file = find_config_file()
    if config_file:
        config, _ = load_config(config_file)
    else:
        config = Config()

    cli_args = {
        "base_branch": base_branch,
        "dry_run": dry_run,
        "exclude_labels": exclude_labels,
        "include_labels": include_labels,
        "merge_method": merge_method,
        "bypass_review_count": bypass_review_count,
        "owner": owner,
        "prefix": prefix,
        "repo_type": repo_type,
    }
    merged_config = merge_config_with_cli(config, cli_args)

    # Display startup message first
    print("🚀 Starting Merge-Pulls (Merge Pull Requests) on GitHub...\n")

    # Load config if available (for display purposes)
    if config_file:
        print(f"📚 Loading configuration from: {config_file}")

    # Display merged configuration
    print("📚 Configuration (merged YAML and CLI):")
    print(f"   base-branch: {merged_config['base_branch']}")
    print(f"   bypass-review-count: {merged_config['bypass_review_count']}")
    print(f"   dry-run: {merged_config['dry_run']}")
    print(f"   exclude-labels: {merged_config['exclude_labels']}")
    print(f"   include-labels: {merged_config['include_labels']}")
    print(f"   merge-method: {merged_config['merge_method']}")
    print(f"   owner: {merged_config['owner']}")
    print(f"   prefix: {merged_config['prefix']}")
    print(f"   repo-type: {merged_config['repo_type']}")

    print()  # Empty line before actual operations

    try:
        # Create a single GitHub client instance for the rest of the process
        gh, gh_token = get_auth()

        # 1. Get Token User Data
        user = gh.get_user()
        login, orgs = get_token_user_info(gh, user)

        # 2. Process Click Inputs (use merged config values)
        owner = merged_config["owner"]
        repo_type = merged_config["repo_type"]
        merge_method = merged_config["merge_method"]
        set_exclude_labels = merged_config["exclude_labels"]
        set_include_labels = merged_config["include_labels"]
        base_branch = merged_config["base_branch"]
        prefix = merged_config["prefix"]
        dry_run = merged_config["dry_run"]
        bypass_review_count = merged_config["bypass_review_count"]

        check_owner(owner=owner, orgs=orgs, login=login)
        check_repo_type(repo_type=repo_type)
        check_merge_method(merge_method=merge_method)

        # 3. Get Repo Data
        if owner:
            repos_obj, repos = get_repos_from_owner(gh, user, owner, repo_type)
        else:
            repos_obj, repos = get_repos_from_all(gh, user, repo_type)

        # 4. Get PR Data
        list_open_prs = await get_open_prs(gh, repos_obj, base_branch, set_exclude_labels, set_include_labels, prefix)

        # 5. Check Merge Readiness
        list_mergeable_prs = await get_merge_readiness(gh, list_open_prs, base_branch, bypass_review_count, merge_method)

        # 6. Merge PRs
        list_merged_prs = await put_merge_pr(gh, list_mergeable_prs, merge_method, dry_run, base_branch)

        print_summary(len(list_open_prs), len(list_mergeable_prs), len(list_merged_prs))

    except CustomError as err:
        print(f"\n❌ Configuration Error: {err}")
        sys.exit(1)
    except (KeyError, PermissionError) as err:
        print(f"\n❌ Authentication Error: {err}")
        sys.exit(1)
    except ValueError as err:
        print(f"\n❌ Error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"\n❌ Unexpected Error: {err}")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
