"""
Tests for Repo, Commit, Branch etc.
"""

from .utils import testlooper_db, generate_branch_structure, clear_branch_structure
from testlooper.schema.schema import repo_schema

testlooper_db = testlooper_db  # necessary to avoid flake8 errors


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
