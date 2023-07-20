"""
Utilities for running the tests.
"""

import tempfile
import pytest
import requests
import time
from object_database import connect, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken

from testlooper.engine.git_watcher_service import GitWatcherService
from testlooper.engine.local_engine_agent import LocalEngineAgent
from testlooper.engine.local_engine_service import LocalEngineService
from testlooper.schema.repo_schema import RepoConfig
from testlooper.schema.schema import repo_schema, engine_schema, test_schema
from testlooper.vcs import Git

GIT_WATCHER_PORT = 1234


TEST_PLAN = """
version: 1
environments:
    # linux docker container for running our pytest unit-tests
    linux-pytest:
        image:
            docker:
                dockerfile: .testlooper/environments/linux-pytest/Dockerfile
        variables:
            PYTHONPATH: ${REPO_ROOT}
            TP_COMPILER_CACHE: /tp_compiler_cache
            IS_TESTLOOPER: true
        min-ram-gb: 10
        custom-setup: |
            python -m pip install --editable .

    # native linux image necessary for running unit-tests that need to boot docker containers.
    linux-native:
        image:
            base_ami: ami-0XXXXXXXXXXXXXXXX  # ubuntu-20.04-ami
        min-ram-gb: 10
        custom-setup: |
            sudo apt-get --yes install python3.8-venv
            make install  # install pinned dependencies
builds:
    # skip

suites:
    pytest:
        kind: unit
        environment: linux-pytest
        dependencies:
        timeout:
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'not docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        timeout:
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        timeout:
        list-tests: |
            .testlooper/collect-matlab-tests.sh
        run-tests: |
            .testlooper/run-matlab-tests.sh
"""


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
                service_schema,
                repo_schema,
                test_schema,
                engine_schema,
            )
            yield database

        finally:
            if server is not None:
                server.terminate()
                server.wait()


@pytest.fixture(scope="module")
def git_service(testlooper_db):
    max_retries = 10
    with testlooper_db.transaction():
        git_service = ServiceManager.createOrUpdateService(
            GitWatcherService, "GitWatcherService", target_count=0
        )

    GitWatcherService.configure(
        testlooper_db, git_service, hostname="localhost", port=GIT_WATCHER_PORT
    )

    with testlooper_db.transaction():
        ServiceManager.startService("GitWatcherService", 1)

    # wait for the service to start by pinging it a few times.

    for _ in range(max_retries):
        try:
            resp = requests.post(f"http://localhost:{GIT_WATCHER_PORT}/git_updater", json={})
            if resp.status_code == 400:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
            pass

    yield git_service


@pytest.fixture(scope="module")
def local_engine_service(testlooper_db):
    with tempfile.TemporaryDirectory() as tmp_dirname:
        repo_path = tmp_dirname
    with testlooper_db.transaction():
        _ = engine_schema.LocalEngineConfig(path_to_git_repo=repo_path)
        service = ServiceManager.createOrUpdateService(
            LocalEngineService, "LocalEngineService", target_count=1
        )
    yield service


@pytest.fixture(scope="module")
def local_engine_agent(testlooper_db):
    """The service runs out-of-process so if we want to use the agent attributes
    we need to instantiate it ourselves."""

    with tempfile.TemporaryDirectory() as tmp_dirname:
        repo_path = tmp_dirname
        git_repo = Git.get_instance(repo_path)
        agent = LocalEngineAgent(
            testlooper_db, source_control_store=git_repo, artifact_store=None
        )
        yield agent


@pytest.fixture(scope="function")
def make_and_clear_repo(testlooper_db):
    """Makes a demo repo, then destroys it after the test."""
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(testlooper_db, branches)
    yield
    clear_branch_structure(testlooper_db)


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
