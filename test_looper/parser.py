"""Service to parse commits and create a test plan"""
import json

from test_looper.repo_schema import Commit, RepoConfig
from test_looper.test_schema import TestNode, Command, TestNodeDefinition
from test_looper.tl_git import GIT
from test_looper.utils.db import transaction, ServiceMixin


class ParserService(ServiceMixin):

    def start(self):
        self.start_threadloop(self.parse_commits)

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
        num_parsed = 0
        for i, c in enumerate(Commit.lookupAll(is_parsed=False)):
            num_parsed += self._parse(c)
            if max_num_commits is not None and 0 < max_num_commits <= i:
                break
        return num_parsed

    def _parse(self, commit: Commit):
        conf = commit.repo.config
        assert(isinstance(conf, RepoConfig.Local))
        tl_conf = self._parse_tl_json(commit.sha, conf.path)
        if tl_conf is None:
            return False
        self._create_test_plan(commit, tl_conf)
        commit.is_parsed = True
        return True

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
        for i, cmd in enumerate(cmd_conf):
            c = Command(bashCommand=f"{cmd['command']} {' '.join(cmd['args'])}")
            test_def = TestNodeDefinition.Test(runTests=c)
            TestNode(commit=commit,
                     name=f"{commit.repo.name}-tests-{i}",
                     definition=test_def,
                     needsMoreWork=True)

    @staticmethod
    def _parse_build_commands(commit: Commit, cmd_txt: list):
        # TODO decide on the format and implement
        raise NotImplementedError()

    @staticmethod
    def _parse_docker_image(commit: Commit, cmd_txt: list):
        # TODO decide on the format and implement
        raise NotImplementedError()

