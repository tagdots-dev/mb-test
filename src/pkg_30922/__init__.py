"""
Main package entry point.

This package provides automated pull request merging functionality for GitHub,
including repository discovery, PR filtering, merge readiness evaluation, and
batch merging operations.

Submodules:
    - config: Configuration loading and validation
    - services.gh_ci: Merge readiness evaluation with CI and review checks
    - services.gh_merge: PR merge execution
    - services.gh_pr: Open PR retrieval and filtering
    - services.gh_repo: Repository discovery
    - services.gh_user: GitHub authentication and user info
"""

from .config import Config, load_config, merge_config_with_cli
from .services.gh_ci import get_merge_readiness
from .services.gh_merge import put_merge_pr
from .services.gh_pr import get_open_prs
from .services.gh_repo import get_repos_from_all, get_repos_from_owner
from .services.gh_user import get_auth, get_token_user_info

__version__ = "1.0.0"

__all__ = (
    "Config",
    "load_config",
    "merge_config_with_cli",
    "get_auth",
    "get_merge_readiness",
    "put_merge_pr",
    "get_open_prs",
    "get_repos_from_all",
    "get_repos_from_owner",
    "get_token_user_info",
)
