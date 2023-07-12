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
import requests
import shutil
import sys
import tempfile
import time
import yaml

from numpy.random import default_rng
from object_database import connect, core_schema, service_schema
from object_database.database_connection import DatabaseConnection
from object_database.frontends.service_manager import startServiceManagerProcess
from object_database.service_manager.ServiceManager import ServiceManager
from object_database.util import genToken
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.ActiveWebServiceSchema import active_webservice_schema
from object_database.web.LoginPlugin import LoginIpPlugin

from testlooper.engine.git_watcher_service import GitWatcherService
from testlooper.engine.local_engine_service import LocalEngineService
from testlooper.engine.schema_monitor import SchemaMonitorService
from testlooper.schema.repo_schema import RepoConfig
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.service import TestlooperService
from testlooper.utils import TL_SERVICE_NAME, setup_logger
from testlooper.vcs import Git

rng = default_rng()
logger = setup_logger(__name__, level=logging.INFO)


PATH_TO_CONFIG = ".testlooper/config.yaml"
TOKEN = genToken()
HTTP_PORT = 8001
ODB_PORT = 8021
LOGLEVEL_NAME = "ERROR"
GIT_WATCHER_PORT = 9999
REPO_PATH = "."


def main(
    path_to_config=PATH_TO_CONFIG,
    token=TOKEN,
    http_port=HTTP_PORT,
    internal_port=HTTP_PORT + 1,
    odb_port=ODB_PORT,
    log_level=LOGLEVEL_NAME,
    git_watcher_port=GIT_WATCHER_PORT,
):
    with open(path_to_config, "r") as flines:
        test_config = flines.read()

    parsed_test_config = yaml.safe_load(test_config)
    repo_name = parsed_test_config["name"]

    with tempfile.TemporaryDirectory() as tmp_dirname:
        # copy repo to a tmpdir just to be safu
        repo_path = os.path.join(tmp_dirname, repo_name)
        shutil.copytree(REPO_PATH, repo_path)
        server = None
        try:
            # spin up the required TL services
            server = startServiceManagerProcess(
                tmp_dirname, odb_port, token, loglevelName=log_level, logDir=False
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
                    str(internal_port),
                    "--host",
                    "0.0.0.0",
                    "--log-level",
                    log_level,
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

            GitWatcherService.configure(
                database, git_service, hostname="localhost", port=git_watcher_port
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
                # schema monitor - just for admin and testing
                _ = ServiceManager.createOrUpdateService(
                    SchemaMonitorService, "SchemaMonitorService", target_count=1
                )
            time.sleep(2)  # temp - let the services start up before we start hitting them
            scan_repo(
                database,
                post_url=f"http://localhost:{git_watcher_port}/git_updater",
                path_to_repo=repo_path,
                path_to_tl_config=path_to_config,
            )

            while True:
                time.sleep(0.1)

        finally:
            if server is not None:
                server.terminate()
                server.wait()


# def add_to_dict(directory, input_dict):
#     """Walk a dir, adding all files to a dict."""
#     for filename in os.listdir(directory):
#         new_path = os.path.join(directory, filename)
#         if os.path.isfile(new_path):
#             with open(new_path) as file:
#                 input_dict[new_path] = file.read()
#         elif os.path.isdir(new_path):
#             add_to_dict(new_path, input_dict)


def scan_repo(
    database: DatabaseConnection,
    post_url: str,
    path_to_repo: str,
    path_to_tl_config=".testlooper/config.yaml",
    max_depth=5,
    # branch_prefix="will",  # FIXME a temp shim to make rerunning quicker
) -> Git:
    """
    Scan a repo using the repo config path, listing all *local* branches down to
    <max_depth> commits.

    Assumes we are on the top commit of some branch
    """
    tl_config = os.path.join(path_to_repo, path_to_tl_config)
    assert os.path.isfile(tl_config)
    assert os.path.isdir(path_to_repo)
    assert os.path.isdir(os.path.join(path_to_repo, ".git"))
    git_repo = Git.get_instance(path_to_repo)
    # assumption: the repo config is unchanged across commits, so just use the current version
    with open(tl_config, "r") as flines:
        test_config = flines.read()

    parsed_test_config = yaml.safe_load(test_config)
    repo_name = parsed_test_config["name"]
    primary_branch_name = parsed_test_config["primary-branch"]

    with database.transaction():
        # spin up the initial stuff
        repo_config = RepoConfig.Local(path=path_to_repo)
        repo = repo_schema.Repo(name=repo_name, config=repo_config)
        # _ = repo_schema.TestConfig(config_str=test_config, repo=repo)

    for branch_name in git_repo.list_branches():
        # TODO remove
        if branch_name not in ("will-qol", "will-deliberately-failing-tests"):
            continue
        # if not branch_name.startswith(branch_prefix):
        #     continue
        # don't spam the POSTs
        time.sleep(0.1)
        commits = [
            x
            for x in git_repo.get_top_commits_for_branch(branch_name, n=max_depth)
            if x.strip()
        ]
        commit_data = []
        for commit in commits:
            commit_id = commit
            author_name = git_repo.get_commit_author_name(commit_id)
            author_email = git_repo.get_commit_author_email(commit_id)
            commit_message = git_repo.get_commit_short_message(commit_id)
            url = f"http://localhost:{GIT_WATCHER_PORT}/{repo_name}/commit/{commit_id}"
            commit_data.append(
                {
                    "id": commit_id,
                    "message": commit_message,
                    "url": url,  # this is fake
                    "author": {
                        "name": author_name,
                        "email": author_email,
                    },
                }
            )
        data = {
            "ref": f"refs/heads/{branch_name}",
            "before": "0" * 40,
            "after": commits[-1],
            "created": True,
            "deleted": False,
            "repository": {
                "name": repo_name,
                "url": f"http://localhost:{GIT_WATCHER_PORT}/{repo_name}.git",  # this is fake
            },
            "pusher": {
                "name": author_name,
                "email": author_email,
            },
            "commits": commit_data,
        }

        requests.post(post_url, json=data)

    time.sleep(0.1)
    # need to set the repo primary branch, which has now been populated and created.
    with database.transaction():
        repo.primary_branch = repo_schema.Branch.lookupUnique(
            repo_and_name=(repo, primary_branch_name)
        )

    return git_repo


if __name__ == "__main__":
    sys.exit(main())
