"""git_watcher_service.py

Follows the structure of ActiveWebService to accept POST requests from
a local/GitHub/GitLab webhook and update ODB accordingly.
"""

import logging
import object_database.web.cells as cells

from dataclasses import dataclass
from flask import Flask, request
from gevent.pywsgi import WSGIServer
from object_database import ServiceBase

from testlooper.utils import setup_logger
from testlooper.schema.schema import engine_schema, repo_schema

from typing import List, Dict


@dataclass(frozen=True)
class GitCommit:
    """Holds the data for a single commit."""

    id: str
    message: str
    url: str
    author: Dict[str, str]

    @property
    def author_and_email(self):
        return f"{self.author['name']} <{self.author['email']}>"


@dataclass(frozen=True)
class GitPayload:
    """Holds the POST request payload.
    NB: post_commit is definitionally sent with a single commit. So the
    before and after, branch deleted and created, etc, is not the same.
    """

    before: str
    after: str
    ref: str
    repository: Dict[str, str]
    commits: List[GitCommit]
    created: str
    deleted: str


def filter_keys(d, cls):
    return {k: v for k, v in d.items() if k in cls.__annotations__}


class GitWatcherService(ServiceBase):
    """Listens for POST requests, generates ODB objects (and maybe Tasks)"""

    def initialize(self):
        self.db.subscribeToSchema(engine_schema, repo_schema)
        self._logger = setup_logger(__name__, level=logging.INFO)
        self.app = Flask(__name__)
        self.app.add_url_rule(
            "/git_updater", view_func=self.catch_git_change, methods=["POST"]
        )
        # self.app.errorhandler(WebServiceError)(self.handleWebServiceError)

    def doWork(self, shouldStop):
        """Spins up a WSGI server. Needs a GitWatcherConfig to have been created."""
        while not shouldStop.is_set():
            try:
                with self.db.view():
                    config = engine_schema.GitWatcherConfig.lookupUnique(
                        service=self.serviceObject
                    )
                    if config is None:
                        raise RuntimeError(f"No config found for service {self.serviceObject}")
                    self._logger.setLevel(config.log_level)
                    host = config.hostname
                    port = config.port
                self._logger.info("Starting Git Watcher Service on %s:%s" % (host, port))
                server = WSGIServer((host, port), self.app)
                server.serve_forever()
            except Exception as e:
                shouldStop.set()
                self._logger.error(str(e))

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        return cells.Card(cells.Text("Git Watcher Service"))

    def catch_git_change(self):
        """Called when we get a POST request. For now, we only get requests on each commit.

        Repo Objects we need to create:
        - Commit
        - Branch
        - commit parents
        -
        Objects that should probably be created in advance:
        - TestConfig
        - Repo


        How do we handle rebases? probably by updating the parents(). We
        know two commits on the same Branch
        can't have the same parent.
        the commit object has:
        - hash
        - repo
        - commit_text
        - author
        - test_config
        - parents


        how do i get the test config? probably via Task
        """
        self._logger.warning("Git change caught!")
        data = request.get_json()
        if not data:
            self._logger.warning("Bad request")
            return {
                "message": "Bad Request",
                "details": "No data provided or not JSON format",
            }, 400
        try:
            self._logger.debug('Received data: "%s"' % data)
            # filter out any keys that aren't in the GitPayload dataclass
            subset_data = filter_keys(data, GitPayload)
            subset_data["commits"] = [
                GitCommit(**filter_keys(commit, GitCommit))
                for commit in subset_data["commits"]
            ]
            self._logger.info(f"dropping keys: {set(data.keys()) - set(subset_data.keys())}")
            payload = GitPayload(**subset_data)

            # get the repo
            repo_name = payload.repository["name"]
            with self.db.view():
                repo = repo_schema.Repo.lookupUnique(name=repo_name)
            if repo is None:
                raise ValueError(f"Repo {repo_name} not found in ODB")

            with self.db.transaction():
                prev_commit = repo_schema.Commit.lookupUnique(hash=payload.before)
                for payload_commit in payload.commits:
                    commit = repo_schema.Commit.lookupUnique(hash=payload_commit.id)
                    if commit is None:
                        # TODO the test config can, in theory, change. Should be added with a
                        # Task. The git watcher should probably not be making said Tasks.
                        test_config = repo_schema.TestConfig.lookupUnique(repo=repo)

                        commit = repo_schema.Commit(
                            hash=payload_commit.id,
                            repo=repo,
                            commit_text=payload_commit.message,
                            author=payload_commit.author_and_email,
                            test_config=test_config,
                        )
                        _ = engine_schema.TestPlanGenerationTask.create(commit=commit)
                        self._logger.info(f"Created commit {commit.hash}")
                        if prev_commit is not None:
                            commit.set_parents([prev_commit])
                    prev_commit = commit

                branch_name = payload.ref.split("/")[-1]
                if payload.created:
                    # make a Branch
                    assert (
                        repo_schema.Branch.lookupUnique(repo_and_name=(repo, branch_name))
                        is None
                    )
                    top_commit = repo_schema.Commit.lookupUnique(hash=payload.after)
                    branch = repo_schema.Branch(
                        repo=repo, name=branch_name, top_commit=top_commit
                    )
                    self._logger.info(f"Created branch {branch.name}")
                else:
                    # update the top commit
                    branch = repo_schema.Branch.lookupUnique(repo_and_name=(repo, branch_name))
                    top_commit = repo_schema.Commit.lookupUnique(hash=payload.after)
                    branch.top_commit = top_commit
                    self._logger.info(
                        f"Updated branch {branch.name} to top commit {top_commit.hash}"
                    )

            message = "ODB updated successfully"
            self._logger.info(message)
            return {"message": message}, 201
        except Exception as e:
            self._logger.exception(e)
            return {"message": "Internal Server Error", "details": str(e)}, 500

    @staticmethod
    def configure(db, service_object, hostname, port, level_name="INFO"):
        """Gets or creats a Configuration ODB object, sets the hostname, port, log level."""
        db.subscribeToSchema(engine_schema)
        with db.transaction():
            c = engine_schema.GitWatcherConfig.lookupAny(service=service_object)
            if not c:
                c = engine_schema.GitWatcherConfig(service=service_object)
            c.hostname = hostname
            c.port = port
            c.log_level = logging.getLevelName(level_name)