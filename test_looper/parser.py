"""Service to parse commits and create a test plan"""
import json
import os
import threading

from object_database import ServiceBase, Reactor
from object_database.database_connection import DatabaseConnection

from test_looper import test_looper_schema
from test_looper.repo_schema import Commit, Repository
from test_looper.service import LooperService
from test_looper.test_schema import TestNode, Command, TestNodeDefinition, Worker
from test_looper.tl_git import GIT
from test_looper.utils.db import transaction, logger


class ParserService(ServiceBase):
    """
    Every 10s, scan the repositories we know about for new commits.
    Separately, two reactors will be running:
    1. When new commits are added from the scan repo operation, parse
       the commits and add TestNodes
    2. If there are unexecuted TestNodes, assign them to free workers
    """

    def __init__(self,
                 db: DatabaseConnection,
                 serviceObject,
                 serviceRuntimeConfig,
                 repo_url: str = "/tmp/test_looper/repos"):
        super(ParserService, self).__init__(db, serviceObject, serviceRuntimeConfig)
        # TODO configure the following via ODB
        #      repo_url
        #      scan_repo poll interval
        self.repo_url = repo_url
        self._looper = LooperService(self.db, repo_url=repo_url)

    def initialize(self):
        self.db.subscribeToSchema(test_looper_schema)
        # keep parsing commits until we're done
        commit_reactor = Reactor(self.db, self.parse_commits)
        self.registerReactor(commit_reactor)
        # assign TestNode's to workers when available
        dispatch_reactor = Reactor(self.db, self.assign_nodes)
        self.registerReactor(dispatch_reactor)
        print("Initialized parser service reactor", flush=True)
        self.startReactors()

    def doWork(self, shouldStop: threading.Event):
        print("In doWork")
        with self.reactorsRunning():
            with self.db.transaction():
                print("Checking repositories")
                for repo in Repository.lookupAll():
                    print(f"Scanning {repo.name}")
                    self._looper.scan_repo(repo, "*")
            print("Reactor running")
            shouldStop.wait(10)

    @transaction
    def parse_commits(self, max_num_commits: int = None) -> int:
        """

        Parameters
        ----------
        max_num_commits: int, default None
            Parse up to this many commits. If unspecified then parse all commits where `is_parsed=False`

        Returns
        -------
        num_parsed: number of commits successfully parsed
        """
        print("Parsing commits")
        num_parsed = 0
        for i, c in enumerate(Commit.lookupAll(is_parsed=False)):
            num_parsed += self._parse(c)
            if max_num_commits is not None and 0 < max_num_commits <= i:
                break
        print(f"Parsed {num_parsed} commits")
        return num_parsed

    @transaction
    def assign_nodes(self):
        """Find TestNode's the needs more work and assign them to workers"""
        print("Running assign_nodes")
        nodes = [n for n in TestNode.lookupAll(needsMoreWork=True) if not n.isAssigned]
        workers = Worker.lookupAll(currentAssignment=None)
        if len(nodes) > 0 and len(workers) > 0:
            logger.debug(f"Assigning {len(nodes)} TestNodes to {len(workers)} available workers")
        for i in range(min(len(nodes), len(workers))):
            workers[i].currentAssignment = nodes[i]
            nodes[i].isAssigned = True
            print(f"Assigned {nodes[i].commit.sha} to {workers[i].workerId}")

    def _parse(self, commit: Commit):
        is_found, clone_path = self.get_clone(commit.repo)
        if not is_found:
            raise FileNotFoundError(f"{clone_path} not found; "
                                    f"can't parse commits")
        tl_conf = self._parse_tl_json(commit.sha, clone_path)
        if tl_conf is None:
            return False
        self._create_test_plan(commit, tl_conf)
        commit.is_parsed = True
        return True

    def get_clone(self, repo: Repository):
        clone_path = os.path.join(self.repo_url, repo.name)
        is_found = os.path.exists(clone_path)
        return is_found, clone_path

    @staticmethod
    def _parse_tl_json(sha: str, repo_path: str) -> dict:
        try:
            tl_json_str = GIT().read_file(repo_path, 'test_looper.json', ref=sha)
            return json.loads(tl_json_str)
        except (FileNotFoundError, ValueError):
            # TODO add some schema objects to record unparseable commits?
            pass

    def _create_test_plan(self, commit: Commit, conf: dict):
        keys = ["build_commands", "docker_commands", "test_commands"]
        for k in keys:
            commands = conf.get(k)
            if commands is not None:
                getattr(self, f'_parse_{k}')(commit, commands)

    @staticmethod
    def _parse_test_commands(commit: Commit, cmd_conf: list):
        i = 0
        for i, cmd in enumerate(cmd_conf):
            c = Command(bashCommand=f"{cmd['command']} {' '.join(cmd['args'])}")
            test_def = TestNodeDefinition.Test(runTests=c)
            TestNode(commit=commit,
                     name=f"{commit.repo.name}-tests-{i}",
                     definition=test_def,
                     needsMoreWork=True)
        print(f"Created {i} new TestNodes")

    @staticmethod
    def _parse_build_commands(commit: Commit, cmd_txt: list):
        # TODO decide on the format and implement
        raise NotImplementedError()

    @staticmethod
    def _parse_docker_image(commit: Commit, cmd_txt: list):
        # TODO decide on the format and implement
        raise NotImplementedError()

