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
import sys
import tempfile
import time
import uuid

from numpy.random import default_rng
from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken
from object_database.view import MultipleViewError
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.LoginPlugin import LoginIpPlugin
from object_database.database_connection import DatabaseConnection
from testlooper.engine.local_engine_service import LocalEngineService
from testlooper.engine.git_watcher_service import GitWatcherService
from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.repo_schema import RepoConfig
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.schema.test_schema import (
    DesiredTesting,
    StageResult,
    TestFilter,
    TestRunResult,
)
from testlooper.service import TestlooperService
from testlooper.utils import TL_SERVICE_NAME, setup_logger

from testlooper.vcs import Git

rng = default_rng()

# setupLogging()
logger = setup_logger(__name__, level=logging.INFO)


PATH_TO_CONFIG = ".testlooper/config.yaml"
TOKEN = genToken()
HTTP_PORT = 8001
ODB_PORT = 8021
LOGLEVEL_NAME = "ERROR"
GIT_WATCHER_PORT = 9999

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
                git_service = ServiceManager.createOrUpdateService(
                    GitWatcherService, "GitWatcherService", target_count=0
                )

            # config
            GitWatcherService.configure(
                database, git_service, hostname="localhost", port=GIT_WATCHER_PORT
            )

            with database.transaction():
                ServiceManager.startService("ActiveWebService", 1)
                # TL frontend - tests and repos
                _ = ServiceManager.createOrUpdateService(
                    TestlooperService, TL_SERVICE_NAME, target_count=1
                )
                # local engine - will eventually do all the below work.
                _ = engine_schema.LocalEngineConfig(path_to_git_repo=repo_path)
                _ = ServiceManager.createOrUpdateService(
                    LocalEngineService, "LocalEngineService", target_count=1
                )
                # git watcher - receives post requests from git webhooks and
                # updates ODB accordingly
                ServiceManager.startService("GitWatcherService", 1)

            # for now, need a Repo object so that the watcher knows how to link stuff,
            # and an initial primary branch
            with database.transaction():
                repo_config = RepoConfig.Local(path=repo_path)
                repo = repo_schema.Repo(name=repo_name, config=repo_config)
                _ = repo_schema.TestConfig(config=TEST_CONFIG, repo=repo)
                _ = repo_schema.Branch(repo=repo, name="master")

            # first, make a Git object for our DB, generate a repo with branches and commits.
            # then run a script to populate the db with schema objects.
            _ = generate_repo(path_to_root=repo_path)

            # TODO get the primary branch from a config file
            with database.transaction():
                if (
                    branch := repo_schema.Branch.lookupUnique(repo_and_name=(repo, "master"))
                ) is not None:
                    repo.primary_branch = branch
                elif (
                    branch := repo_schema.Branch.lookupUnique(repo_and_name=(repo, "main"))
                ) is not None:
                    repo.primary_branch = branch
                else:
                    raise ValueError("No primary branch found")

            with database.transaction():
                tasks = engine_schema.TestPlanGenerationTask.lookupAll()

            # TODO make a Reactor to block until the test_plan is generated instead of polling.
            plan_results = wait_for_result(
                database, tasks, engine_schema.TestPlanGenerationResult
            )

            # set desired testing for all our branches
            with database.transaction():
                branches = repo_schema.Branch.lookupAll(repo=repo)
                for branch in branches:
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
                    logger.info("Generated desired testing for branch %s", branch.name)
                # TODO generate CommitDesiredTestings
                for plan_result in plan_results:
                    commit = plan_result.commit
                    commit_test_definition = test_schema.CommitTestDefinition(commit=commit)
                    logger.info("Generated commit test definition for commit %s", commit.hash)
                    commit_test_definition.set_test_plan(
                        plan_result.data
                    )  # here is where the suite generation tasks are created

            # wait for suites, then assign test results
            with database.transaction():
                tasks = engine_schema.TestSuiteGenerationTask.lookupAll()

            suite_results = wait_for_result(
                database, tasks, engine_schema.TestSuiteGenerationResult
            )
            # add the suites to the commit test definition once finished.
            with database.transaction():
                for result in suite_results:
                    commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(
                        commit=result.commit
                    )
                    suites_dict = commit_test_definition.test_suites
                    if suites_dict is None:
                        suites_dict = {}
                    suites_dict[result.suite.name] = result.suite
                    commit_test_definition.test_suites = suites_dict

            with database.transaction():
                # Pretend to run all our tests (would be run via run_tests_command),
                # ignoring suites, for all commits with a test definition
                # For now we only run on the top commits of each branch (see 29k)
                for commit_test_definition in test_schema.CommitTestDefinition.lookupAll():
                    commit = commit_test_definition.commit
                    logger.info("Running tests for commit %s", commit.hash)
                    for test in test_schema.Test.lookupAll():
                        assert (
                            test_schema.TestResults.lookupAny(test_and_commit=(test, commit))
                            is None
                        )
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
                        logger.info(
                            f"Adding test result '{result.outcome}' for test: {test.name}"
                        )

            while True:
                time.sleep(0.1)

        finally:
            if server is not None:
                server.terminate()
                server.wait()


def generate_repo(
    path_to_root: str, path_to_config_dir=".testlooper", path_to_test_dir="tests"
) -> Git:
    """Generate a temporary repo with a couple of branches and some commits.
    Also generate a tests/ folder with some stuff in it for pytest to run.

    repo structure:

           A---B---C---D   master
                \
                 E---F   feature


    We copy the config_dir from testlooper itself to allow tasks to run.
    We copy the test dir from testlooper to give pytest something to grab.
    """
    author = "author <author@aprioriinvestments.com>"
    repo = Git.get_instance(path_to_root)
    repo.init()

    config_dir_contents = {}
    for filename in os.listdir(path_to_config_dir):
        new_path = os.path.join(path_to_config_dir, filename)
        with open(os.path.abspath(new_path)) as flines:
            config_dir_contents[new_path] = flines.read()

    # check for a post-receive hook in the config dir. If it exists, stick it
    # in .git/hooks
    if os.path.exists(os.path.join(path_to_config_dir, "post-receive")):
        with open(os.path.join(path_to_config_dir, "post-receive")) as flines:
            post_commit = flines.read()
        with open(os.path.join(path_to_root, ".git/hooks/post-receive"), "w") as flines:
            flines.write(post_commit)
        os.chmod(os.path.join(path_to_root, ".git/hooks/post-receive"), 0o755)

    a = repo.create_commit(None, config_dir_contents, "message1", author=author)

    # need to use a dependent repo for the push hooks to work
    repo.detach_head()
    dep_repo = Git.get_instance(path_to_root + "/dep_repo")
    dep_repo.clone_from(path_to_root)

    test_dir_contents = {}
    for filename in os.listdir(path_to_test_dir):
        new_path = os.path.join(path_to_test_dir, filename)
        if os.path.isfile(new_path):
            with open(os.path.abspath(new_path)) as flines:
                test_dir_contents[new_path] = flines.read()
    b = dep_repo.create_commit(
        a,
        test_dir_contents,
        "message2",
        author,
        on_branch="master",
    )
    assert dep_repo.push_commit(b, branch="master", force=False, create_branch=True)

    c = dep_repo.create_commit(b, {"dir1/file2": "contents_2"}, "message3", author)
    d = dep_repo.create_commit(c, {"dir2/file2": "contents_2"}, "message4", author)
    assert dep_repo.push_commit(d, branch="master", force=False)

    e = dep_repo.create_commit(b, {"dir1/file2": "contents_3"}, "message5", author)
    f = dep_repo.create_commit(e, {"dir2/file2": "contents_3"}, "message6", author)
    assert dep_repo.push_commit(f, branch="feature", force=False, create_branch=True)

    return repo


def wait_for_result(db: DatabaseConnection, tasks, result_type, max_loops=10):
    """Repeatedly poll the db until all <tasks> have a result."""
    results = set()
    tasks = set(tasks)
    failed_tasks = set()
    loop = 0
    while len(results) + len(failed_tasks) != len(tasks) and loop < max_loops:
        time.sleep(1)
        loop += 1
        try:
            with db.view():
                for task in tasks:
                    if task not in failed_tasks:
                        status, _ = task.status
                        if status == StatusEvent.FAILED:
                            failed_tasks.add(task)
                            continue
                        result = result_type.lookupUnique(task=task)
                        if result is not None:
                            results.add(result)

        except MultipleViewError:
            logger.error("multiple view error")
            continue

    if loop == max_loops:
        raise ValueError(f"found {len(results)} results for {len(tasks)} tasks")

    return list(results)


if __name__ == "__main__":
    sys.exit(main())
