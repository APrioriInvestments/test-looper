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


def generate_branch_structure(db, branches):
    """
    Generate a repo with a few branches and commits.

    Args:
        db: The odb connection
        branches: A dict from branch name to a list of commit hashes, in order.
            The util will generate all commits and link them together.
    """

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


config_dockerfile = """
version: 1.0
name: testlooper
primary-branch: will-qol
image:
     docker:
       dockerfile: .testlooper/environments/Dockerfile.setup
       with-docker: true

variables:
    PYTHONPATH: ${REPO_ROOT}

command:
    python .testlooper/generate_test_plan.py  --output ${TEST_PLAN_OUTPUT}
"""

config_no_dockerfile = """
version: 1.0
name: testlooper
primary-branch: will-qol
image:
     docker:
       image: testlooper:latest
       with-docker: true

variables:
    PYTHONPATH: ${REPO_ROOT}

command:
    python .testlooper/generate_test_plan.py  --output ${TEST_PLAN_OUTPUT}
"""

config_bad = """
version: 1.0
this doesn't parse
"""

config_bad_command = """
version: 1.0
name: testlooper
primary-branch: will-qol
image:
     docker:
       image: testlooper:latest
       with-docker: true

variables:
    PYTHONPATH: ${REPO_ROOT}

command:
    python .testlooper/this_doesnt_exist.py  --output ${TEST_PLAN_OUTPUT}
"""
generate_test_plan = """

import argparse

TEST_PLAN = \"""
version: 1
environments:
    # linux docker container for running our pytest unit-tests
    linux-pytest:
        image:
            docker:
                # dockerfile: .testlooper/environments/linux-pytest/Dockerfile
                image: testlooper:latest
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
        list-tests: |
            python .testlooper/collect_pytest_tests.py -m 'not docker'
        run-tests: |
            python .testlooper/run_pytest_tests.py -m 'not docker'
        timeout: 30

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            python .testlooper/collect_pytest_tests.py -m 'docker'
        run-tests: |
            python .testlooper/run_pytest_tests.py  -m 'docker'
        timeout: 30

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            .testlooper/collect_matlab_tests.sh
        run-tests: |
            .testlooper/run_matlab_tests.sh
        timeout: 30
\"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a test plan.")
    parser.add_argument("--output", type=str, default="test_plan.yaml")
    args = parser.parse_args()

    with open(args.output, "w") as f:
        f.write(TEST_PLAN)

"""


collect_pytest_tests = """
demo_tests = \"""
test_one:
  path: test_one.py
  labels:
    - slow
test_two:
  path: test_two.py
  labels:
    - fast
\"""
if __name__ == "__main__":
    print(demo_tests)
"""

run_pytest_tests = """
import os
import subprocess
import sys
from typing import Optional


def run_pytest_json_report(args) -> Optional[str]:
    test_output = os.environ.get("TEST_OUTPUT")
    test_input = os.environ.get("TEST_INPUT")

    command = [sys.executable, "-m", "pytest", "--json-report"]

    if test_output:
        command.extend(["--json-report-file", test_output])

    if test_input:
        # we expect a test on each line, with the format path_to_file::test_name
        with open(test_input, "r") as flines:
            test_cases = [
                line.strip()
                for line in flines.readlines()
                if line and not line.startswith("#")
            ]
        command.extend(test_cases)

    command.extend(args)
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        output = e.output
        print(f"Error occurred: {e}")
        return None
    return output


def main():
    args = sys.argv[1:]
    output = run_pytest_json_report(args)
    print(output)


if __name__ == "__main__":
    main()
"""


@pytest.fixture(scope="module")
def generate_repo(testlooper_db, local_engine_agent):
    """Generate a temporary repo with a couple of branches and some commits.
    Also generate a tests/ folder with some stuff in it for pytest to run.

    repo structure:

           A---B---C---D   master
                \
                 E---F   feature


    We copy the config_dir from testlooper itself to allow tasks to run.
    We copy the test dir from testlooper to give pytest something to grab.

    Also make the ODB objects.
    """
    repo = local_engine_agent.source_control_store
    repo.init()

    author = "author <author@aprioriinvestments.com>"

    # this holds the various testlooper files we need for our integration tests.
    config_dir_contents = {
        ".testlooper/config_dockerfile.yaml": config_dockerfile,
        ".testlooper/config_no_dockerfile.yaml": config_no_dockerfile,
        ".testlooper/config_bad.yaml": config_bad,
        ".testlooper/config_bad_command.yaml": config_bad_command,
        ".testlooper/generate_test_plan.py": generate_test_plan,
        ".testlooper/collect_pytest_tests.py": collect_pytest_tests,
        ".testlooper/run_pytest_tests.py": run_pytest_tests,
    }

    a = repo.create_commit(None, config_dir_contents, "message1", author=author)

    repo.detach_head()
    dep_repo = Git.get_instance(repo.path_to_repo + "/dep_repo")
    dep_repo.clone_from(repo.path_to_repo)

    b = dep_repo.create_commit(
        a, {"dir1/file1": "contents_1"}, "message2", author=author, on_branch="master"
    )
    assert dep_repo.push_commit(b, branch="master", force=False, create_branch=True)

    c = dep_repo.create_commit(b, {"dir1/file2": "contents_2"}, "message3", author)
    d = dep_repo.create_commit(c, {"dir2/file2": "contents_2"}, "message4", author)
    assert dep_repo.push_commit(d, branch="master", force=False)

    e = dep_repo.create_commit(b, {"dir1/file2": "contents_3"}, "message5", author)
    f = dep_repo.create_commit(e, {"dir2/file2": "contents_3"}, "message6", author)
    assert dep_repo.push_commit(f, branch="feature", force=False, create_branch=True)

    # make the ODB objects.
    branches = {"master": [a, b, c, d], "feature": [b, e, f]}
    generate_branch_structure(testlooper_db, branches)

    return branches


@pytest.fixture(scope="function")
def clear_tasks(testlooper_db):
    yield
    with testlooper_db.transaction():
        for task_type in [
            engine_schema.TestPlanGenerationTask,
            engine_schema.TestSuiteGenerationTask,
            engine_schema.BuildDockerImageTask,
            engine_schema.TestRunTask,
            engine_schema.CommitTestDefinitionGenerationTask,
            engine_schema.GenerateTestConfigTask,
            engine_schema.TestPlanGenerationResult,
            engine_schema.TestSuiteGenerationResult,
            repo_schema.TestConfig,
            test_schema.TestPlan,
            test_schema.TestSuite,
            test_schema.CommitTestDefinition,
        ]:
            for task in task_type.lookupAll():
                task.delete()
        for commit in repo_schema.Commit.lookupAll():
            commit.test_config = None
