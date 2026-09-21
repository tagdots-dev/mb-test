"""
Repository discovery and listing services.

This module provides functionality for:
- Fetching repositories across all accessible accounts
- Filtering repositories by type (all, private, public)
- Repository validation (excluding archived/disabled repositories)
"""

from typing import List, Set, Tuple

from github import (
    AuthenticatedUser,
    Github,
    GithubException,
    Repository,
    UnknownObjectException,
)


def get_repos_from_all(
    gh: Github, user: AuthenticatedUser.AuthenticatedUser, repo_type: str
) -> Tuple[List[Repository.Repository], List[str]]:
    """
    Get all repositories across all GitHub organizations and user accounts.

    Retrieves repositories from the authenticated user's accounts across
    all organizations and personal repositories the user has access to.
    Filters out archived and disabled repositories.

    Note:
        This is a synchronous setup function called once per run.
        It does not use async/await as it performs sequential pagination.
        For parallel PR processing across repos, see get_open_prs().

    Args:
        gh: Authenticated Github client instance.
        user: Authenticated GitHub user object (for repository listing).
        repo_type: Type of repositories to include: 'all', 'private', or 'public'.

    Returns:
        Tuple of (list of Repository objects, list of repository full names)
        where repository names are in format "owner/repo".

    Raises:
        GithubException: If a GitHub API error occurs.
        Exception: For other unexpected errors.
    """
    try:
        # Get the list of organizations the token has access to
        # This is needed to filter repos for fine-grained PATs which may not
        # properly respect scope restrictions when calling user.get_repos()
        orgs = user.get_orgs()
        org_names: Set[str] = {org.login for org in orgs}

        repos_obj = []
        repos_str = []
        for repo in user.get_repos(type=repo_type, sort="full_name", direction="asc"):
            # Skip repos from orgs the token doesn't have access to
            # This handles the case where fine-grained PATs may return repos
            # from orgs they don't have permission to access
            repo_owner = repo.full_name.split("/")[0]
            if repo_owner in org_names:
                # Repo belongs to an organization the token has access to
                if repo.archived or repo.disabled:
                    continue
                repos_obj.append(repo)
                repos_str.append(repo.full_name)
            elif repo.owner.login == user.login:
                # Repo is owned by the user themselves (not an org)
                if repo.archived or repo.disabled:
                    continue
                repos_obj.append(repo)
                repos_str.append(repo.full_name)

        return repos_obj, repos_str

    except GithubException as err:
        raise ValueError(f"GitHub API error occurred: {err.status}")
    except Exception as err:
        raise ValueError(err)


def get_repos_from_owner(
    gh: Github, user: AuthenticatedUser.AuthenticatedUser, owner: str, repo_type: str
) -> Tuple[List[Repository.Repository], List[str]]:
    """
    Get all repositories from a specific organization or user.

    Retrieves repositories owned by a specific GitHub user or organization.
    For organizations, fetches all repos in the org. For users, fetches
    only repos owned by that user (not contributed to).

    Note:
        This is a synchronous setup function called once per run.
        It does not use async/await as it performs sequential pagination.
        For parallel PR processing across repos, see get_open_prs().

    Args:
        gh: Authenticated Github client instance.
        user: Authenticated GitHub user object (for access verification).
        owner: GitHub username or organization name.
        repo_type: Type of repositories to include: 'all', 'private', or 'public'.

    Returns:
        Tuple of (list of Repository objects, list of repository full names)
        where repository names are in format "owner/repo".

    Raises:
        UnknownObjectException: If the owner is not found (404).
        GithubException: If a GitHub API error occurs.
        Exception: For other unexpected errors.
    """
    try:
        entity = gh.get_user(owner)

        repos_obj = []
        repos_str = []
        if entity.type == "Organization":
            org = gh.get_organization(owner)
            for repo in org.get_repos(type=repo_type, sort="full_name", direction="asc"):
                if repo.archived or repo.disabled:
                    continue
                repos_obj.append(repo)
                repos_str.append(repo.full_name)

        elif entity.type == "User":
            # Get all repos and filter by owner to only include repos owned by this user
            # (user.get_repos() returns all repos the token has access to, including org repos)
            for repo in user.get_repos():
                # Only include repos where the owner matches the entity login
                if repo.full_name.split("/")[0] != entity.login:
                    continue
                if repo.archived or repo.disabled:
                    continue
                # Filter by repo_type: all, private, or public
                if repo_type == "private" and not repo.private:
                    continue
                if repo_type == "public" and repo.private:
                    continue
                repos_obj.append(repo)
                repos_str.append(repo.full_name)

        # Note: entity.type should only be "User" or "Organization".
        # If it's neither, return empty list (safe default for unknown types).
        return repos_obj, repos_str

    except UnknownObjectException as err:
        raise ValueError(f"Owner ({owner}) not found {err.status}")
    except GithubException as err:
        raise ValueError(f"GitHub API error occurred: {err.status}")
    except Exception as err:
        raise ValueError(err)
