"""
GitHub authentication and user information services.

This module provides functionality for:
- GitHub token authentication
- User information retrieval
- Organization access listing
"""

import os
from typing import Tuple, cast

from github import (
    Auth,
    AuthenticatedUser,
    BadCredentialsException,
    Github,
    GithubException,
)


def get_auth() -> Tuple[Github, str]:
    """
    Create and validate a GitHub client instance.

    This function reads the GH_TOKEN environment variable, creates a
    Github client with 100 items per page pagination, and verifies
    the token by calling get_rate_limit().

    Note:
        This is a synchronous setup function called once per run.
        It does not use async/await as it performs minimal I/O.

    Args:
        None - reads GH_TOKEN from environment variables

    Returns:
        Tuple of (Github client instance, GitHub token string)

    Raises:
        KeyError: If the GH_TOKEN environment variable is not set.
        BadCredentialsException: If the GitHub token is invalid or has expired.
        GithubException: For other GitHub API errors.
    """
    try:
        gh_token = os.environ["GH_TOKEN"]
        gh = Github(auth=Auth.Token(gh_token), per_page=100)
        gh.get_rate_limit()
        return (gh, gh_token)

    except KeyError:
        raise KeyError("GitHub Token - not found")
    except BadCredentialsException:
        raise PermissionError("GitHub Token - bad credential")


def get_token_user_info(gh: Github, user: AuthenticatedUser.AuthenticatedUser | None = None) -> tuple[str, list[str]]:
    """
    Get user info and organization access.

    Retrieves and displays information about the authenticated GitHub user
    including login name and organization access list.

    Note:
        This is a synchronous utility function called once per run.
        It does not use async/await as it performs minimal I/O.

    Args:
        gh: Authenticated Github client instance.
        user: Optional pre-fetched user object to avoid duplicate API calls.

    Returns:
        Tuple of (login, org_access) where:
        - login: The authenticated user's login name (str)
        - org_access: List of organization names the user has access to (list[str])

    Raises:
        ValueError: If a GitHub API error or other exception occurs.
    """
    try:
        if user is None:
            user = gh.get_user()
        user_login = user.login

        org_access = [org_access.name for org_access in user.get_orgs()]

        print(f"✅ Token Owner User Information  :: login = {user_login}, Org. Access = {org_access}")

        return (user_login, cast(list[str], org_access))

    except GithubException as err:
        raise ValueError(err)
    except Exception as err:
        raise ValueError(err)
