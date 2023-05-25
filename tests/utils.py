"""
Utilities for running the tests.
"""

import tempfile
import object_database.web.cells as cells
import pytest
from object_database import connect
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.util import genToken

from testlooper.schema.repo_schema import RepoConfig
from testlooper.schema.schema import repo_schema, engine_schema, test_schema


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
            database.subscribeToSchema(
                repo_schema,
                test_schema,
                engine_schema,
            )
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
