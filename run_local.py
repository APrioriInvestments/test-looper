#!/usr/bin/env python3

#   Copyright 2023 Braxton Mckee
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

# pyright: reportGeneralTypeIssues=false

import logging
import os
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Dict

import yaml
from numpy.random import default_rng
from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken, setupLogging
from object_database.view import MultipleViewError
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.LoginPlugin import LoginIpPlugin
from object_database.database_connection import DatabaseConnection
from testlooper.engine.local_engine_service import LocalEngineService
from testlooper.schema.engine_schema import Status
from testlooper.schema.repo_schema import RepoConfig
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.schema.test_schema import (
    DesiredTesting,
    StageResult,
    TestFilter,
    TestRunResult,
)
from testlooper.service import TestlooperService
from testlooper.utils import TL_SERVICE_NAME

from testlooper.vcs import Git

rng = default_rng()

logger = logging.getLogger(__name__)
setupLogging()


PATH_TO_CONFIG = ".testlooper/config.yaml"
TOKEN = genToken()
HTTP_PORT = 8001
ODB_PORT = 8021
LOGLEVEL_NAME = "INFO"

with open(PATH_TO_CONFIG, "r") as flines:
    TEST_CONFIG = flines.read()


def main(argv=None):
    if argv is None:
        argv = sys.argv

    with tempfile.TemporaryDirectory() as tmp_dirname:
        server = None
        repo_name = "test_repo"
        repo_path = os.path.join(tmp_dirname, repo_name)
        try:
            server = startServiceManagerProcess(
                tmp_dirname, ODB_PORT, TOKEN, loglevelName=LOGLEVEL_NAME, logDir=False
            )

            database = connect("localhost", ODB_PORT, TOKEN, retry=True)
            database.subscribeToSchema(
                core_schema,
                service_schema,
                active_webservice_schema,
                repo_schema,
                engine_schema,
                test_schema,
            )

            with database.transaction():
                service = ServiceManager.createOrUpdateService(
                    ActiveWebService, "ActiveWebService", target_count=0
                )

            ActiveWebService.configureFromCommandline(
                database,
                service,
                [
                    "--port",
                    str(HTTP_PORT),
                    "--internal-port",
                    str(HTTP_PORT + 1),
                    "--host",
                    "0.0.0.0",
                    "--log-level",
                    LOGLEVEL_NAME,
                ],
            )

            ActiveWebService.setLoginPlugin(
                database,
                service,
                LoginIpPlugin,
                [None],
                config={"company_name": "A Testing Company"},
            )

            with database.transaction():
                ServiceManager.startService("ActiveWebService", 1)
                # TL frontend - tests and repos
                service = ServiceManager.createOrUpdateService(
                    TestlooperService, TL_SERVICE_NAME, target_count=1
                )
                _ = engine_schema.LocalEngineConfig(path_to_git_repo=repo_path)
                # local engine - will eventually do all the below work.
                service = ServiceManager.createOrUpdateService(
                    LocalEngineService, "LocalEngineService", target_count=1
                )

            # first, make a Git object for our DB, generate a repo with branches and commits.
            # then run a script to populate the db with schema objects.
            test_repo = generate_repo(path_to_root=repo_path)
            objects_from_repo(database, test_repo, repo_name)

            with database.transaction():
                tasks = engine_schema.TestPlanGenerationTask.lookupAll()

            # TODO make a Reactor to block until the test_plan is generated instead of polling.
            plan_results = wait_for_test_plans(database, tasks)

            with database.transaction():
                for plan_result in plan_results:
                    # each plan is associated with the top commit of a branch
                    branch = repo_schema.Branch.lookupUnique(top_commit=plan_result.commit)
                    # NB above is only doable because of our specific repo structure)
                    assert branch is not None
                    branch.set_desired_testing(
                        DesiredTesting(
                            runs_desired=1,
                            fail_runs_desired=0,
                            flake_runs_desired=0,
                            new_runs_desired=0,
                            filter=TestFilter(
                                labels="Any", path_prefixes="Any", suites="Any", regex=None
                            ),
                        )
                    )
                    logging.info("Generated desired testing for branch %s", branch.name)
                    commit = branch.top_commit
                    commit_test_definition = test_schema.CommitTestDefinition(commit=commit)
                    logging.info("Generated commit test definition for commit %s", commit.hash)
                    commit_test_definition.set_test_plan(plan_result.data)
                    # TODO have this be Reactored.
                    generate_test_suites(commit=commit)
                    # Pretend to run our tests (would be run via run_tests_command)
                    for test in test_schema.Test.lookupAll():
                        test_results = test_schema.TestResults(
                            test=test, commit=commit, runs_desired=1, results=[]
                        )

                        result = TestRunResult(
                            uuid=str(uuid.uuid4()),
                            outcome=rng.choice(
                                ["passed", "failed", "skipped"], p=[0.5, 0.4, 0.1]
                            ),
                            duration_ms=(duration := rng.uniform(low=50, high=500)),
                            start_time=time.time(),
                            stages={"call": StageResult(duration=duration, outcome="passed")},
                        )
                        test_results.add_test_run_result(result)
                        logging.info(
                            f"Adding test result '{result.outcome}' for test: {test.name}"
                        )

            while True:
                time.sleep(0.1)

        finally:
            if server is not None:
                server.terminate()
                server.wait()


def generate_test_suites(commit):
    test_suite_tasks = engine_schema.TestSuiteGenerationTask.lookupAll(commit=commit)

    suites_dict = {}
    for test_suite_task in test_suite_tasks:
        # manually generate the test suite from the task and results
        test_suite_generation_result = engine_schema.TestSuiteGenerationResult(
            commit=test_suite_task.commit,
            environment=test_suite_task.environment,
            name=test_suite_task.name,
            tests="",
            status=Status(),
        )
        test_suite_generation_result.status.start()

        list_tests_command = test_suite_task.list_tests_command
        # FIXME unsafe execution of arbitrary code, should happen in the container.
        try:
            output = subprocess.check_output(
                list_tests_command, shell=True, stderr=subprocess.DEVNULL, encoding="utf-8"
            )
        except subprocess.CalledProcessError as e:
            logger.error("Failed to list tests: %s", str(e).replace("\n", " "))
            output = None

        if output is not None:
            # parse the output into Tests.
            test_dict = parse_list_tests_yaml(output, perf_test=False)
            suite = test_schema.TestSuite(
                name=test_suite_task.name,
                environment=test_suite_task.environment,
                tests=test_dict,
            )  # TODO this needs a TestSuiteParent
            suites_dict[suite.name] = suite
            logging.info(
                f"Generated test suite {test_suite_task.name} with {len(test_dict)} tests."
            )
        test_suite_generation_result.status.completed()
    # add the suites to the commit test  definition once finished
    commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
    commit_test_definition.test_suites = suites_dict


def parse_list_tests_yaml(
    list_tests_yaml: str, perf_test=False
) -> Dict[str, test_schema.Test]:
    """Parse the output of the list_tests command, and generate Tests if required."""
    yaml_dict = yaml.safe_load(list_tests_yaml)
    parsed_dict = {}
    for test_name, test_dict in yaml_dict.items():
        test = test_schema.Test.lookupUnique(
            name_and_labels=(test_name, test_dict.get("labels", []))
        )
        if test is None:
            test = test_schema.Test(
                name=test_name, labels=test_dict.get("labels", []), path=test_dict["path"]
            )  # TODO this needs a Parent
        parsed_dict[test_name] = test

    if perf_test:
        # add 5000 fake tests to each suite to check ODB performance
        for i in range(5000):
            parsed_dict[f"test_{i}"] = test_schema.Test(
                name=f"test_{i}", labels=[], path="test.py"
            )
    return parsed_dict


def generate_repo(path_to_root: str, path_to_config_dir=".testlooper") -> Git:
    """Generate a temporary repo with a couple of branches and some commits.
    Also generate a tests/ folder with some stuff in it for pytest to run.

    repo structure:

           A---B---C---D   master
                \
                 E---F   feature


    We copy the config_dir from testlooper itself to allow tasks to run.
    """
    author = "author <author@aprioriinvestments.com>"
    repo = Git.get_instance(path_to_root)
    repo.init()

    config_dir_contents = {}
    for filename in os.listdir(path_to_config_dir):
        new_path = os.path.join(path_to_config_dir, filename)
        with open(os.path.abspath(new_path)) as flines:
            config_dir_contents[new_path] = flines.read()

    a = repo.create_commit(None, config_dir_contents, "message1", author=author)

    b = repo.create_commit(
        a,
        {"file1": "hi", "dir1/file2": "contents", "dir2/file3": "contents"},
        "message2",
        author,
    )
    repo.detach_head()
    dep_repo = Git.get_instance(path_to_root + "/dep_repo")
    dep_repo.clone_from(path_to_root)  # have to do this to get proper branch structure (?)
    c = dep_repo.create_commit(b, {"dir1/file2": "contents_2"}, "message3", author)
    d = dep_repo.create_commit(c, {"dir2/file2": "contents_2"}, "message4", author)
    assert dep_repo.push_commit(d, branch="master", force=False, create_branch=True)

    e = dep_repo.create_commit(b, {"dir1/file2": "contents_3"}, "message5", author)
    f = dep_repo.create_commit(e, {"dir2/file2": "contents_3"}, "message6", author)
    assert dep_repo.push_commit(f, branch="feature", force=False, create_branch=True)

    return repo


def objects_from_repo(
    db: DatabaseConnection, git_repo: Git, repo_name: str, primary_branch="master"
) -> None:
    """Commits for all commits, Branches for all branches, etc"""
    with db.transaction():
        repo_config = RepoConfig.Local(path=git_repo.path_to_repo)
        repo = repo_schema.Repo(name=repo_name, config=repo_config)
        test_config = repo_schema.TestConfig(config=TEST_CONFIG, repo=repo)

        branches = git_repo.list_branches()
        for branch_name in branches:
            top_commit_hash = git_repo.get_top_local_commit(branch_name)
            top_commit = lookup_or_create_commit(top_commit_hash, git_repo, repo, test_config)
            branch = repo_schema.Branch(name=branch_name, repo=repo, top_commit=top_commit)
            if branch_name == primary_branch:
                repo.primary_branch = branch

            # we have a Repo. We have the branches. We have the top commits.
            # Now we need to propagate backwards to get the rest of the commits.
            # This will duplicate effort for commits that are on multiple branches, but should
            # be fine for testing/demo purposes.
            commit_chain = git_repo.get_commit_chain(branch_name)[:-1]  # drop the root commit
            for child_hash, parent_hash in commit_chain:
                child = lookup_or_create_commit(child_hash, git_repo, repo, test_config)
                parent = lookup_or_create_commit(parent_hash, git_repo, repo, test_config)
                child.set_parents([parent])
            _ = engine_schema.TestPlanGenerationTask.create(commit=top_commit)


def lookup_or_create_commit(commit_hash, git_repo, repo, test_config) -> repo_schema.Commit:
    """Lookup a commit by hash, or create it if it doesn't exist.

    Args:
        commit_hash: hash of the commit to lookup
        git_repo: a Git object for the repo
        repo: the ODB repo object
        test_config: the ODB test_config object
    """

    commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
    if commit is None:
        author = git_repo.get_commit_author(commit_hash)
        message = git_repo.get_commit_message(commit_hash)
        commit = repo_schema.Commit(
            hash=commit_hash,
            repo=repo,
            commit_text=message,
            author=author,
            test_config=test_config,
        )
    return commit


def wait_for_test_plans(db: DatabaseConnection, tasks, max_loops=5) -> None:
    """Repeatedly poll the db until all <tasks> have a result."""
    task_plans = set()
    loop = 0
    while len(task_plans) != len(tasks) and loop < max_loops:
        time.sleep(0.25)
        loop += 1
        try:
            with db.view():
                for task in tasks:
                    task_plan = engine_schema.TestPlanGenerationResult.lookupUnique(task=task)
                    if task_plan is not None:
                        task_plans.add(task_plan)
        except MultipleViewError:
            print("multiple view error")
            continue
    if loop == max_loops:
        raise ValueError("never generated a test plan")

    return task_plans


if __name__ == "__main__":
    sys.exit(main())
