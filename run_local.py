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
import subprocess
import sys
import tempfile
import time
from typing import Dict

from numpy.random import default_rng
import uuid
import yaml
from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken, setupLogging
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.LoginPlugin import LoginIpPlugin

from testlooper.engine_schema import Status
from testlooper.repo_schema import Branch, Commit, Repo, RepoConfig, TestConfig
from testlooper.schemas import engine_schema, repo_schema, test_schema
from testlooper.service import TestlooperService
from testlooper.test_schema import StageResult, TestRunResult
from testlooper.utils import TL_SERVICE_NAME


rng = default_rng()

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
        list-tests: |
            ./collect_pytest_tests.py -m 'not docker'
        run-tests: |
            ./run_pytest_tests.py -m 'not docker'
        timeout:

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            ./collect_pytest_tests.py -m 'docker'
        run-tests: |
            ./run_pytest_tests.py  -m 'docker'
        timeout:

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            .testlooper/collect_matlab_tests.sh
        run-tests: |
            .testlooper/run_matlab_tests.sh
        timeout:
"""

TEST_CONFIG = """
version: 1.0
image:
     docker:
        dockerfile: .testlooper/environments/plan-generation/Dockerfile
        with-docker: true

variables:
    PYTHONPATH: ${REPO_ROOT}

command:
    python .testlooper/generate_test_plan.py  --out ${TEST_PLAN_OUTPUT}
"""

logger = logging.getLogger(__name__)
setupLogging()


def main(argv=None):
    if argv is None:
        argv = sys.argv

    token = genToken()
    http_port = 8001
    odb_port = 8021
    loglevel_name = "ERROR"

    with tempfile.TemporaryDirectory() as tmp_dirname:
        server = None
        try:
            server = startServiceManagerProcess(
                tmp_dirname, odb_port, token, loglevelName=loglevel_name, logDir=False
            )

            database = connect("localhost", odb_port, token, retry=True)
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
                    str(http_port),
                    "--internal-port",
                    "8001",
                    "--host",
                    "0.0.0.0",
                    "--log-level",
                    loglevel_name,
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

            with database.transaction():
                service = ServiceManager.createOrUpdateService(
                    TestlooperService, TL_SERVICE_NAME, target_count=1
                )

            # populate our db.
            commits = []
            with database.transaction():
                # add a repo with branches and commits
                repo_config = RepoConfig.Local(path="/tmp/test_repo")
                repo = Repo(name="test_repo", config=repo_config)
                test_config = TestConfig(config=TEST_CONFIG, repo=repo)
                commits.append(
                    Commit(
                        hash="12abc43a",
                        repo=repo,
                        commit_text="test commit",
                        author="test author",
                        test_config=test_config,
                    )
                )

                commits.append(
                    Commit(
                        hash="dada321fed",
                        repo=repo,
                        commit_text="initial commit",
                        author="father of this repo",
                        test_config=test_config,
                    )
                )

                commits[0].set_parents([commits[1]])

                branch = Branch(repo=repo, name="dev", top_commit=commits[0])
                repo.primary_branch = branch

                # bootstrap the engine with a mock TestPlanGenerationTask and test plan.
                task = engine_schema.TestPlanGenerationTask(commit=commits[0], status=Status())
                plan = test_schema.TestPlan(plan=TEST_PLAN)
                _ = engine_schema.TestPlanGenerationResult(commit=commits[0], data=plan)
                task.status.completed()
                # generate some tests, suites, results
                commit_test_definition = test_schema.CommitTestDefinition(commit=commits[0])
                logging.info("Generated commit test definition for commit %s", commits[0].hash)
                commit_test_definition.set_test_plan(plan)
                # so we have a test plan for a given commit, and testsuitegenerationtasks.
                # Read the tasks, mock the actual results of the suites.
                generate_test_suites(commit=commits[0])
                # Pretend to run our tests (would be run via run_tests_command)
                for test in test_schema.Test.lookupAll():
                    test_results = test_schema.TestResults(
                        test=test, commit=commits[0], runs_desired=1, results=[]
                    )

                    result = TestRunResult(
                        uuid=str(uuid.uuid4()),
                        outcome=rng.choice(["passed", "failed", "skipped"], p=[0.8, 0.1, 0.1]),
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
            test_dict = parse_list_tests_yaml(output)
            suite = test_schema.TestSuite(
                name=test_suite_task.name,
                environment=test_suite_task.environment,
                tests=test_dict,
            )  # TODO parent?
            suites_dict[suite.name] = suite
            logging.info(
                f"Generated test suite {test_suite_task.name} with {len(test_dict)} tests."
            )
        test_suite_generation_result.status.completed()
    # add the suites to the commit test  definition once finished
    commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
    commit_test_definition.test_suites = suites_dict


def parse_list_tests_yaml(list_tests_yaml: str) -> Dict[str, test_schema.Test]:
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
            )  # TODO parent?
        parsed_dict[test_name] = test
    return parsed_dict


if __name__ == "__main__":
    sys.exit(main())
