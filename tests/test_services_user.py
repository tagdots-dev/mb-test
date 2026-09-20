import os
from unittest.mock import Mock, patch

import pytest

from pkg_30922.services.gh_user import (
    BadCredentialsException,
    Github,
    GithubException,
    get_auth,
    get_token_user_info,
)


class TestGetAuth:
    """Tests for get_auth function."""

    @patch("pkg_30922.services.gh_user.Github")
    @patch.dict(os.environ, {"GH_TOKEN": "fake-token"})  # checkov:skip=CKV_SECRET_6
    def test_get_auth_success(self, mock_github: Mock) -> None:
        """Test successful authentication with valid token."""
        mock_gh_instance = Mock()
        mock_github.return_value = mock_gh_instance
        mock_gh_instance.get_rate_limit.return_value = None

        gh, token = get_auth()

        # Verify Github was called with Auth.Token and per_page=100
        assert mock_github.call_count == 1
        call_args = mock_github.call_args
        assert call_args.kwargs["per_page"] == 100
        assert "auth" in call_args.kwargs
        # Verify the auth is an Auth.Token instance
        from github import Auth

        assert isinstance(call_args.kwargs["auth"], Auth.Token)
        assert token == "fake-token"
        assert gh == mock_gh_instance

    @patch.dict(os.environ, {}, clear=True)
    def test_get_auth_missing_token(self) -> None:
        """Test that KeyError is raised when GH_TOKEN is not set."""
        with pytest.raises(KeyError, match="GitHub Token - not found"):
            get_auth()

    @patch("pkg_30922.services.gh_user.Github")
    @patch.dict(os.environ, {"GH_TOKEN": "invalid-token"})  # checkov:skip=CKV_SECRET_6
    def test_get_auth_bad_credentials(self, mock_github: Mock) -> None:
        """Test that PermissionError is raised for invalid token."""
        mock_github.side_effect = BadCredentialsException(status=401, data={"message": "Bad credentials"})

        with pytest.raises(PermissionError, match="GitHub Token - bad credential"):
            get_auth()


class TestGetTokenUserInfo:
    """Tests for get_token_user_info function."""

    @patch("pkg_30922.services.gh_user.Github")
    def test_get_token_user_info_with_none_user(self, mock_github: Mock) -> None:
        """Test fetching user info when user is None."""
        mock_gh_instance = Mock(spec=Github)
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_org1 = Mock()
        mock_org1.name = "org1"
        mock_org2 = Mock()
        mock_org2.name = "org2"
        mock_user.get_orgs.return_value = [mock_org1, mock_org2]
        mock_gh_instance.get_user.return_value = mock_user

        login, org_access = get_token_user_info(mock_gh_instance)

        mock_gh_instance.get_user.assert_called_once()
        mock_user.get_orgs.assert_called_once()
        assert login == "testuser"
        assert org_access == ["org1", "org2"]

    @patch("pkg_30922.services.gh_user.Github")
    def test_get_token_user_info_with_pre_fetched_user(self, mock_github: Mock) -> None:
        """Test using pre-fetched user object."""
        mock_user = Mock()
        mock_user.login = "pre_fetched_user"
        mock_org = Mock()
        mock_org.name = "pre_fetched_org"
        mock_user.get_orgs.return_value = [mock_org]

        login, org_access = get_token_user_info(Mock(), user=mock_user)

        assert login == "pre_fetched_user"
        assert org_access == ["pre_fetched_org"]

    @patch("pkg_30922.services.gh_user.Github")
    def test_get_token_user_info_with_github_exception(self, mock_github: Mock) -> None:
        """Test handling of GithubException."""
        mock_gh_instance = Mock(spec=Github)
        mock_gh_instance.get_user.side_effect = GithubException(status=500, data={"message": "Server error"})

        with pytest.raises(ValueError, match="Server error"):
            get_token_user_info(mock_gh_instance)

    @patch("pkg_30922.services.gh_user.Github")
    def test_get_token_user_info_with_general_exception(self, mock_github: Mock) -> None:
        """Test handling of general exceptions."""
        mock_gh_instance = Mock(spec=Github)
        mock_gh_instance.get_user.side_effect = Exception("Unexpected error")

        with pytest.raises(ValueError, match="Unexpected error"):
            get_token_user_info(mock_gh_instance)

    @patch("pkg_30922.services.gh_user.Github")
    def test_get_token_user_info_empty_orgs(self, mock_github: Mock) -> None:
        """Test user with no organization access."""
        mock_gh_instance = Mock(spec=Github)
        mock_user = Mock()
        mock_user.login = "user_no_orgs"
        mock_user.get_orgs.return_value = []
        mock_gh_instance.get_user.return_value = mock_user

        login, org_access = get_token_user_info(mock_gh_instance)

        assert login == "user_no_orgs"
        assert org_access == []
