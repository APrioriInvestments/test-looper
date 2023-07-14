"""Tests for the GitWatcherService class."""
import requests

from testlooper.schema.schema import engine_schema
from .utils import git_service, testlooper_db


git_service = git_service  # required by flake8
testlooper_db = testlooper_db


def get_url(db):
    with db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        port = gwc.port
        hostname = gwc.hostname
    return f"http://{hostname}:{port}/git_updater"


def test_git_watcher_service_rejects_empty_post(git_service, testlooper_db):
    resp = requests.post(get_url(testlooper_db), json={})
    assert resp.status_code == 400


def test_git_watcher_unexpected_fields(git_service, testlooper_db):
    """If the POST has unexpected fields, we reject it."""
    pass


def test_git_watcher_fields_missing(git_service, testlooper_db):
    """Ensure if we're missing a field, we reject the whole request."""
    pass


def test_git_watcher_incorrect_repo(git_service, testlooper_db):
    """If the repository name doesn't match any of the repos TL knows about,
    reject."""
    with testlooper_db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        port = gwc.port
        hostname = gwc.hostname

        data = {
            "ref": "refs/heads/dev",
            "before": "abcdefg",
            "after": "1234567",
            "created": True,
            "deleted": False,
            "repository": {
                "name": "different_repo",
                "url": "http://different_repo.com",
            },
            "pusher": {
                "name": "Gary",
                "email": "Gary@garymail.com",
            },
            "commits": [
                {
                    "id": "1234567",
                    "message": "commit message",
                    "url": "http://commit_url.com",
                    "author": {"name": "Gary", "email": "gary@garymail.com"},
                }
            ],
        }

        resp = requests.post(f"http://{hostname}:{port}/git_updater", json=data)
        assert resp.status_code == 400


def test_git_watcher_empty_commits(git_service, testlooper_db):
    """If the commits list is empty, then handle that sensibly."""
    # if the branch is created, still create the branch.
    # ditto if deleted
    # ditto if no action, take no action.
    pass


def test_git_watcher_commits_already_found(git_service, testlooper_db):
    """If their are commits we already know about, that's fine, but don't double-add."""
    pass


def test_git_watcher_branch_created(git_service, testlooper_db):
    """Test we can create a new Branch with a POST."""
    pass


def test_git_watcher_branch_deleted(git_service, testlooper_db):
    """Test we can delete a branch with a POST."""
    pass


def test_git_watcher_linear_commits(git_service, testlooper_db):
    """Test we can handle normal operation - a linear series of commits."""
    pass
