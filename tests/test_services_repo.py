from unittest.mock import Mock, patch

import pytest

from pkg_30922.services.gh_repo import (
    GithubException,
    UnknownObjectException,
    get_repos_from_all,
    get_repos_from_owner,
)


class TestGetReposFromAll:
    """Tests for get_repos_from_all function."""

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_success(self, mock_repo_class: Mock) -> None:
        """Test successful retrieval of repositories."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]

        mock_repo1 = Mock()
        mock_repo1.full_name = "org/repo1"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.owner.login = "org"

        mock_repo2 = Mock()
        mock_repo2.full_name = "org/repo2"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.owner.login = "org"

        mock_repo3 = Mock()
        mock_repo3.full_name = "org/repo3_archived"
        mock_repo3.archived = True
        mock_repo3.disabled = False
        mock_repo3.owner.login = "org"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2, mock_repo3]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        mock_user.get_repos.assert_called_once_with(type="all", sort="full_name", direction="asc")
        assert len(repos_obj) == 2
        assert len(repos_str) == 2
        assert "org/repo1" in repos_str
        assert "org/repo2" in repos_str
        assert "org/repo3_archived" not in repos_str

    def test_get_repos_from_all_empty_repos(self) -> None:
        """Test user with no repositories."""
        mock_user = Mock()
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]
        mock_user.get_repos.return_value = []

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        assert repos_obj == []
        assert repos_str == []

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_disabled_repos(self, mock_repo_class: Mock) -> None:
        """Test that disabled repositories are filtered out."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]

        mock_repo1 = Mock()
        mock_repo1.full_name = "org/active_repo"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.owner.login = "org"

        mock_repo2 = Mock()
        mock_repo2.full_name = "org/disabled_repo"
        mock_repo2.archived = False
        mock_repo2.disabled = True
        mock_repo2.owner.login = "org"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        assert len(repos_str) == 1
        assert "org/active_repo" in repos_str
        assert "org/disabled_repo" not in repos_str

    def test_get_repos_from_all_github_exception(self) -> None:
        """Test handling of GithubException."""
        mock_user = Mock()
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]
        mock_user.get_repos.side_effect = GithubException(status=403, data={"message": "Rate limit exceeded"})

        with pytest.raises(ValueError, match="GitHub API error occurred: 403"):
            get_repos_from_all(Mock(), mock_user, "all")

    def test_get_repos_from_all_general_exception(self) -> None:
        """Test handling of general exceptions."""
        mock_user = Mock()
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]
        mock_user.get_repos.side_effect = Exception("Unexpected error")

        with pytest.raises(ValueError, match="Unexpected error"):
            get_repos_from_all(Mock(), mock_user, "all")

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_org_filtering(self, mock_repo_class: Mock) -> None:
        """Test that repos from orgs not in access list are filtered out."""
        mock_user = Mock()
        mock_user.login = "testuser"
        # Token only has access to 'allowed-org', not 'denied-org'
        mock_allowed_org = Mock()
        mock_allowed_org.login = "allowed-org"
        mock_user.get_orgs.return_value = [mock_allowed_org]

        # Repo in allowed org
        mock_repo1 = Mock()
        mock_repo1.full_name = "allowed-org/repo1"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.owner.login = "allowed-org"

        # Repo in denied org (should be filtered out)
        mock_repo2 = Mock()
        mock_repo2.full_name = "denied-org/repo2"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.owner.login = "denied-org"

        # User's own repo (should be included)
        mock_repo3 = Mock()
        mock_repo3.full_name = "testuser/repo3"
        mock_repo3.archived = False
        mock_repo3.disabled = False
        mock_repo3.owner.login = "testuser"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2, mock_repo3]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        # Only repos from allowed org and user's own repos should be included
        assert len(repos_str) == 2
        assert "allowed-org/repo1" in repos_str
        assert "testuser/repo3" in repos_str
        assert "denied-org/repo2" not in repos_str

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_user_owned_repo_not_in_org(self, mock_repo_class: Mock) -> None:
        """Test that user-owned repos not in orgs are included."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_user.get_orgs.return_value = []  # No org access

        # User's own repo (should be included even without org access)
        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/repo1"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.owner.login = "testuser"

        # Repo in an org (should be filtered out)
        mock_repo2 = Mock()
        mock_repo2.full_name = "some-org/repo2"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.owner.login = "some-org"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        # Only user's own repo should be included
        assert len(repos_str) == 1
        assert "testuser/repo1" in repos_str
        assert "some-org/repo2" not in repos_str

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_user_owned_archived_repo(self, mock_repo_class: Mock) -> None:
        """Test that archived user-owned repos are filtered out."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]

        # User's own archived repo (should be filtered out)
        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/archived_repo"
        mock_repo1.archived = True
        mock_repo1.disabled = False
        mock_repo1.owner.login = "testuser"

        # User's own active repo (should be included)
        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/active_repo"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.owner.login = "testuser"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        # Only active user repo should be included
        assert len(repos_str) == 1
        assert "testuser/active_repo" in repos_str
        assert "testuser/archived_repo" not in repos_str

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_all_user_owned_disabled_repo(self, mock_repo_class: Mock) -> None:
        """Test that disabled user-owned repos are filtered out."""
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_org = Mock()
        mock_org.login = "org"
        mock_user.get_orgs.return_value = [mock_org]

        # User's own disabled repo (should be filtered out)
        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/disabled_repo"
        mock_repo1.archived = False
        mock_repo1.disabled = True
        mock_repo1.owner.login = "testuser"

        # User's own active repo (should be included)
        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/active_repo"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.owner.login = "testuser"

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_all(Mock(), mock_user, "all")

        # Only active user repo should be included
        assert len(repos_str) == 1
        assert "testuser/active_repo" in repos_str
        assert "testuser/disabled_repo" not in repos_str


class TestGetReposFromOwner:
    """Tests for get_repos_from_owner function."""

    @patch("pkg_30922.services.gh_repo.Repository")
    def test_get_repos_from_org_success(self, mock_repo_class: Mock) -> None:
        """Test successful retrieval of organization repositories."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "Organization"
        mock_gh.get_user.return_value = mock_entity

        mock_org = Mock()
        mock_repo1 = Mock()
        mock_repo1.full_name = "org/repo1"
        mock_repo1.archived = False
        mock_repo1.disabled = False

        mock_repo2 = Mock()
        mock_repo2.full_name = "org/repo2"
        mock_repo2.archived = True
        mock_repo2.disabled = False

        mock_org.get_repos.return_value = [mock_repo1, mock_repo2]
        mock_gh.get_organization.return_value = mock_org

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testorg", "all")

        mock_gh.get_user.assert_called_once_with("testorg")
        mock_gh.get_organization.assert_called_once_with("testorg")
        mock_org.get_repos.assert_called_once_with(type="all", sort="full_name", direction="asc")
        assert len(repos_str) == 1
        assert "org/repo1" in repos_str
        assert "org/repo2" not in repos_str

    def test_get_repos_from_user_owner_filtering(self) -> None:
        """Test that user repo filtering only includes repos owned by the user."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo = Mock()
        mock_repo.full_name = "otheruser/repo"
        mock_repo.archived = False
        mock_repo.disabled = False
        mock_repo.private = False

        mock_user.get_repos.return_value = [mock_repo]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "all")

        assert repos_str == []

    def test_get_repos_from_owner_unknown_exception(self) -> None:
        """Test handling of UnknownObjectException for non-existent owner."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_gh.get_user.side_effect = UnknownObjectException(status=404, data={"message": "Not Found"})

        with pytest.raises(ValueError, match="Owner \\(nonexistent\\) not found 404"):
            get_repos_from_owner(mock_gh, mock_user, "nonexistent", "all")

    def test_get_repos_from_owner_github_exception(self) -> None:
        """Test handling of GithubException."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "Organization"
        mock_gh.get_user.return_value = mock_entity

        mock_org = Mock()
        mock_org.get_repos.side_effect = GithubException(status=500, data={"message": "Server error"})
        mock_gh.get_organization.return_value = mock_org

        with pytest.raises(ValueError, match="GitHub API error occurred: 500"):
            get_repos_from_owner(mock_gh, mock_user, "testorg", "all")

    def test_get_repos_from_owner_general_exception(self) -> None:
        """Test handling of general exceptions."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "Organization"
        mock_gh.get_user.side_effect = Exception("Unexpected error")

        with pytest.raises(ValueError, match="Unexpected error"):
            get_repos_from_owner(mock_gh, mock_user, "testorg", "all")

    def test_get_repos_from_user_owner_with_matching_repos(self) -> None:
        """Test user repo filtering when repos are owned by the user."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo = Mock()
        mock_repo.full_name = "testuser/repo"
        mock_repo.archived = False
        mock_repo.disabled = False
        mock_repo.private = False

        mock_user.get_repos.return_value = [mock_repo]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "all")

        assert len(repos_str) == 1
        assert "testuser/repo" in repos_str

    def test_get_repos_from_user_owner_archived_filtering(self) -> None:
        """Test that archived repos are filtered for user owner."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/active"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.private = False

        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/archived"
        mock_repo2.archived = True
        mock_repo2.disabled = False
        mock_repo2.private = False

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "all")

        assert len(repos_str) == 1
        assert "testuser/active" in repos_str
        assert "testuser/archived" not in repos_str

    def test_get_repos_from_user_owner_disabled_filtering(self) -> None:
        """Test that disabled repos are filtered for user owner."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/active"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.private = False

        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/disabled"
        mock_repo2.archived = False
        mock_repo2.disabled = True
        mock_repo2.private = False

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "all")

        assert len(repos_str) == 1
        assert "testuser/active" in repos_str
        assert "testuser/disabled" not in repos_str

    def test_get_repos_from_user_owner_private_filtering(self) -> None:
        """Test that private repos are filtered when repo_type is 'public'."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/public"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.private = False

        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/private"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.private = True

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "public")

        assert len(repos_str) == 1
        assert "testuser/public" in repos_str
        assert "testuser/private" not in repos_str

    def test_get_repos_from_user_owner_public_filtering(self) -> None:
        """Test that public repos are filtered when repo_type is 'private'."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "User"
        mock_entity.login = "testuser"
        mock_gh.get_user.return_value = mock_entity

        mock_repo1 = Mock()
        mock_repo1.full_name = "testuser/private"
        mock_repo1.archived = False
        mock_repo1.disabled = False
        mock_repo1.private = True

        mock_repo2 = Mock()
        mock_repo2.full_name = "testuser/public"
        mock_repo2.archived = False
        mock_repo2.disabled = False
        mock_repo2.private = False

        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "testuser", "private")

        assert len(repos_str) == 1
        assert "testuser/private" in repos_str
        assert "testuser/public" not in repos_str

    def test_get_repos_from_owner_unknown_type(self) -> None:
        """Test handling of unknown entity type (neither Organization nor User)."""
        mock_gh = Mock()
        mock_user = Mock()

        mock_entity = Mock()
        mock_entity.type = "Enterprise"  # Unknown type
        mock_entity.login = "test"
        mock_gh.get_user.return_value = mock_entity

        repos_obj, repos_str = get_repos_from_owner(mock_gh, mock_user, "test", "all")

        # Should return empty since neither branch executes
        assert repos_obj == []
        assert repos_str == []
