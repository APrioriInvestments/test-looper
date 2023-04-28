"""
Tests for Repo, Commit, Branch etc.
"""
import tempfile

import object_database.web.cells as cells
import pytest
from object_database import connect
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.util import genToken

from testlooper.repo_schema import RepoConfig
from testlooper.schema_declarations import repo_schema


@pytest.fixture(scope="module")
def testlooper_db():
    """Start an ODB server, maintain it while all tests in this file run, shut down."""
    with tempfile.TemporaryDirectory() as tmp_dirname:
        server = None
        token = genToken()
        odb_port = 8021
        loglevel_name = "ERROR"
        try:
            server = startServiceManagerProcess(
                tmp_dirname, odb_port, token, loglevelName=loglevel_name, logDir=False
            )

            database = connect("localhost", odb_port, token, retry=True)
            database.subscribeToSchema(repo_schema)

            yield database

        finally:
            if server is not None:
                server.terminate()
                server.wait()


def generate_branch_structure(db, branches):
    """
    Generate a repo with a few branches and commits.

    Args:
        db: The odb connection
        branches: A dict from branch name to a list of commit hashes, in order.
            The util will generate all commits and link them together.
    """

    def find_or_create_commit(hash, repo):
        if commit := repo_schema.Commit.lookupUnique(hash=hash):
            return commit
        else:
            return repo_schema.Commit(
                hash=hash, repo=repo, commit_text="test commit", author="test author"
            )

    def find_or_create_link(parent, child):
        if commit_parent := repo_schema.CommitParent.lookupUnique(
            parent_and_child=(parent, child)
        ):
            return commit_parent
        else:
            return repo_schema.CommitParent(parent=parent, child=child)

    with db.transaction():
        cells.ensureSubscribedSchema(repo_schema)
        repo_config = RepoConfig.Local(path="/tmp/test_repo")
        repo = repo_schema.Repo(name="test_repo", config=repo_config)

        for branch_name, branch_commits in branches.items():
            # chain the commits together.
            parent_commit = find_or_create_commit(branch_commits[0], repo=repo)
            for commit_hash in branch_commits[1:]:
                commit = find_or_create_commit(commit_hash, repo=repo)
                _ = find_or_create_link(parent_commit, commit)
                parent_commit = commit

            _ = repo_schema.Branch(repo=repo, name=branch_name, top_commit=parent_commit)


def clear_branch_structure(db):
    with db.transaction():
        for obj in [
            repo_schema.Commit,
            repo_schema.CommitParent,
            repo_schema.Branch,
            repo_schema.Repo,
        ]:
            for o in obj.lookupAll():
                o.delete()


def test_commit_get_closest_branch_top_commit(testlooper_db):
    """
    Correctly return the branch with top_commit == the commit in question
    """
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.view():
        commit = repo_schema.Commit.lookupUnique(hash="e")
        nearest_branch = commit.get_closest_branch()
        assert nearest_branch.name == "feature"
        commit = repo_schema.Commit.lookupUnique(hash="c")
        nearest_branch = commit.get_closest_branch()
        assert nearest_branch.name == "dev"

    clear_branch_structure(db=testlooper_db)


def test_commit_get_closest_branch_too_far(testlooper_db):
    """
    If the commit we're interested in is too deep, return None
    """
    branches = {
        "dev": "abcdefghijklmnopqrstuvwxyz",
        "feature": "abcdefghijklmnopqrstuvwxyz1234",
    }
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.view():
        commit = repo_schema.Commit.lookupUnique(hash="a")
        nearest_branch = commit.get_closest_branch(max_depth=10)
        assert nearest_branch is None

    clear_branch_structure(db=testlooper_db)


def test_commit_get_closest_branch_no_branches(testlooper_db):
    """
    If we can't find any matching branch at all, return None.
    (unclear how this would happen)
    """
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.transaction():
        _ = repo_schema.Commit(
            hash="f",
            repo=repo_schema.Repo.lookupUnique(name="test_repo"),
            commit_text="test commit",
            author="test author",
        )
    with testlooper_db.view():
        commit = repo_schema.Commit.lookupUnique(hash="f")
        nearest_branch = commit.get_closest_branch()
        assert nearest_branch is None

    clear_branch_structure(db=testlooper_db)


def test_commit_get_closest_branch_multiple_branches(testlooper_db):
    """
    If we have multiple branches containing this commit, split the tie randomly.
    """
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.view():
        commit = repo_schema.Commit.lookupUnique(hash="a")
        nearest_branch = commit.get_closest_branch()
        assert nearest_branch.name in ("dev", "feature")
    clear_branch_structure(db=testlooper_db)


def test_commit_get_closest_branch_test_shortest(testlooper_db):
    """
    If we have multiple branches but one has a closer top commit, return that one.
    """
    branches = {"dev": ["a", "b", "c", "d", "e", "f"], "feature": ["a", "b", "c", "g"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.view():
        for commit_hash in "abc":
            commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
            nearest_branch = commit.get_closest_branch()
            assert nearest_branch.name == "feature"

    clear_branch_structure(db=testlooper_db)
