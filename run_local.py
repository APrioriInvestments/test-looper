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

import sys
import tempfile
import time

from object_database.service_manager.ServiceManager import ServiceManager

from testlooper.service import TestlooperService

from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.ActiveWebService import ActiveWebService
from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.util import genToken
from object_database.web.LoginPlugin import LoginIpPlugin
from testlooper.repo_schema import repo_schema, RepoConfig, Repo, Commit, Branch, CommitParent


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
                    TestlooperService, "TestlooperService", target_count=1
                )

            # populate our db.
            commits = []
            with database.transaction():
                # add a repo with branches and commits
                repo_config = RepoConfig.Local(path="/tmp/test_repo")

                repo = Repo(name="test_repo", config=repo_config)

                commits.append(
                    Commit(
                        hash="12abc43a",
                        repo=repo,
                        commit_text="test commit",
                        author="test author",
                        test_plan_generated=False,
                    )
                )

                commits.append(
                    Commit(
                        hash="dada321fed",
                        repo=repo,
                        commit_text="initial commit",
                        author="father of this repo",
                    )
                )

                CommitParent(parent=commits[1], child=commits[0])

                Branch(repo=repo, name="dev", top_commit=commits[0])

                # print("created repo", repo, "commit", commit, "branch", branch)

            while True:
                time.sleep(0.1)
        finally:
            if server is not None:
                server.terminate()
                server.wait()


if __name__ == "__main__":
    sys.exit(main())
