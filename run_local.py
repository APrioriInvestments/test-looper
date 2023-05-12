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

import sys
import tempfile
import time

from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.LoginPlugin import LoginIpPlugin

from testlooper.utils import TL_SERVICE_NAME
from testlooper.repo_schema import Branch, Commit, Repo, RepoConfig, TestConfig
from testlooper.engine_schema import Status
from testlooper.schemas import repo_schema, engine_schema
from testlooper.service import TestlooperService


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
            .testlooper/collect-pytest-tests.sh -m 'not docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            .testlooper/collect-matlab-tests.sh
        run-tests: |
            .testlooper/run-matlab-tests.sh
"""


def main(argv=None):
    if argv is None:
        argv = sys.argv

    token = genToken()
    http_port = 8001
    odb_port = 8021
    loglevel_name = "INFO"

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
                test_config = TestConfig(config="test_config_here", repo=repo)
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
                result = engine_schema.TestPlanGenerationResult(commit=commits[0],
                                                                data=TEST_PLAN)
                print(result.data)
                task.status.completed()
                # TODO generate some test results

            while True:
                time.sleep(0.1)

        finally:
            if server is not None:
                server.terminate()
                server.wait()


if __name__ == "__main__":
    sys.exit(main())
