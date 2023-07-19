"""Tests for the GitWatcherService class."""
import requests

from testlooper.schema.schema import engine_schema, repo_schema
from ..utils import git_service, testlooper_db, make_and_clear_repo


git_service = git_service  # required by flake8
testlooper_db = testlooper_db
make_and_clear_repo = make_and_clear_repo
# ^ above generates two branches with 3 commits each (one shared):
#   {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}


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


def test_git_watcher_incorrect_repo(git_service, testlooper_db, make_and_clear_repo):
    """If the repository name doesn't match any of the repos TL knows about,
    reject the request, don't add the repo or the commits."""

    with testlooper_db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        port = gwc.port
        hostname = gwc.hostname

    data = {
        "ref": "refs/heads/dev",
        "before": "abcdefg",
        "after": "1234567",
        "created": False,
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

    with testlooper_db.view():
        assert repo_schema.Repo.lookupAny(name="different_repo") is None
        assert repo_schema.Commit.lookupUnique(hash="1234567") is None


def test_git_watcher_empty_commits(git_service, testlooper_db, make_and_clear_repo):
    """If the commits list is empty, then handle that sensibly."""
    with testlooper_db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        hostname = gwc.hostname
        port = gwc.port

    # if the branch is created, still create the branch.
    data = {
        "ref": "refs/heads/new-dev",
        "before": "e",
        "after": "e",
        "created": True,
        "deleted": False,
        "repository": {
            "name": "test_repo",
            "url": "http://different_repo.com",
        },
        "pusher": {
            "name": "Gary",
            "email": "Gary@garymail.com",
        },
        "commits": [],
    }

    resp = requests.post(f"http://{hostname}:{port}/git_updater", json=data)
    assert resp.status_code == 201

    with testlooper_db.view():
        repo = repo_schema.Repo.lookupAny(name="test_repo")
        assert repo_schema.Branch.lookupUnique(repo_and_name=(repo, "new-dev")) is not None

        prev_num_branches = len(repo_schema.Branch.lookupAll(repo=repo))
        prev_num_commits = len(repo_schema.Commit.lookupAll(repo=repo))

    # TODO process deletions properly

    # If nothing has changed, don't do anything.
    data = {
        "ref": "refs/heads/new-dev",
        "before": "e",
        "after": "e",
        "created": False,
        "deleted": False,
        "repository": {
            "name": "test_repo",
            "url": "http://different_repo.com",
        },
        "pusher": {
            "name": "Gary",
            "email": "Gary@garymail.com",
        },
        "commits": [],
    }

    resp = requests.post(f"http://{hostname}:{port}/git_updater", json=data)
    assert resp.status_code == 201
    with testlooper_db.view():
        assert len(repo_schema.Branch.lookupAll(repo=repo)) == prev_num_branches
        assert len(repo_schema.Commit.lookupAll(repo=repo)) == prev_num_commits


def test_git_watcher_commits_already_found(git_service, testlooper_db, make_and_clear_repo):
    """If there are commits we already know about, that's fine, but don't double-add."""
    with testlooper_db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        port = gwc.port
        hostname = gwc.hostname

    data = {
        "ref": "refs/heads/dev",
        "before": "e",
        "after": "g",
        "created": False,
        "deleted": False,
        "repository": {
            "name": "test_repo",
            "url": "http://different_repo.com",
        },
        "pusher": {
            "name": "Gary",
            "email": "Gary@garymail.com",
        },
        "commits": [
            {
                "id": "a",
                "message": "commit message",
                "url": "http://commit_url.com",
                "author": {"name": "Gary", "email": "gary@garymail.com"},
            },
            {
                "id": "c",
                "message": "commit message",
                "url": "http://commit_url.com",
                "author": {"name": "Gary", "email": "gary@garymail.com"},
            },
            {
                "id": "g",
                "message": "commit message",
                "url": "http://commit_url.com",
                "author": {"name": "Gary", "email": "gary@garymail.com"},
            },
        ],
    }

    resp = requests.post(f"http://{hostname}:{port}/git_updater", json=data)
    assert resp.status_code == 201

    with testlooper_db.view():
        for commit_hash in ["a", "c", "g"]:
            assert repo_schema.Commit.lookupUnique(hash=commit_hash) is not None
        # TODO handle the deleted 'b' commit.


def test_git_watcher_branch_created(git_service, testlooper_db, make_and_clear_repo):
    """Test we can create a new Branch with a POST."""
    with testlooper_db.view():
        assert (gwc := engine_schema.GitWatcherConfig.lookupAny()) is not None
        port = gwc.port
        hostname = gwc.hostname

    data = {
        "ref": "refs/heads/new-dev",
        "before": "e",
        "after": "g",
        "created": True,
        "deleted": False,
        "repository": {
            "name": "test_repo",
            "url": "http://different_repo.com",
        },
        "pusher": {
            "name": "Gary",
            "email": "Gary@garymail.com",
        },
        "commits": [
            {
                "id": "f",
                "message": "commit message",
                "url": "http://commit_url.com",
                "author": {"name": "Gary", "email": "gary@garymail.com"},
            },
            {
                "id": "g",
                "message": "commit message",
                "url": "http://commit_url.com",
                "author": {"name": "Gary", "email": "gary@garymail.com"},
            },
        ],
    }

    resp = requests.post(f"http://{hostname}:{port}/git_updater", json=data)
    assert resp.status_code == 201

    with testlooper_db.view():
        assert len(repo_schema.Commit.lookupAll()) == 7
        assert len(repo_schema.Branch.lookupAll()) == 3


# def test_git_watcher_branch_deleted(git_service, testlooper_db):
#     """Test we can delete a branch with a POST."""
#     pass
