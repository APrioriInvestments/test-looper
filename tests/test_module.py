"""
General Tests for Test Looper
"""
import os
# import sys
import shutil
import pytest

# from test_looper.git import GIT
from test_looper.runner import TestRunner as TRunner
from test_looper.runner import TestList as TList
from test_looper.runner import TestRunnerResult as TRunnerResult

# GLOBALS
repo_path = '/tmp/test_repo'


class TestTestLooper:
    def setup_class(cls):
        # git = GIT()
        # create a repo where tests will run
        # status = git.clone('tests/_template_repo', repo_path)
        # if status:
        #    sys.exit("Could not clone test repo")
        # copy the a template directory "repo" with tests
        shutil.copytree('tests/_template_repo', repo_path, dirs_exist_ok=True)

    @pytest.fixture(autouse=True)
    def runner(self):
        # NOTE: rename TestRunner to TRunner or pytest gets confused
        self.runner = TRunner(repo_path)

    def test_runner_setup(self):
        assert self.runner._test_commands is None
        self.runner.setup()
        assert self.runner._test_commands

    def test_runner_list(self):
        results = self.runner.list()
        # TODO: need better inspection here once tests stabilize
        assert isinstance(results[0][1]['retcode'].value, int)
        assert isinstance(results[0][1]['results'], TList)

    def test_runner_run(self):
        all_results = self.runner.run()
        # TODO: need better inspection here once tests stabilize
        command, results = all_results[0]
        assert set(command.keys()) == set(['command', 'args'])
        assert isinstance(results['retcode'].value, int)
        assert isinstance(results['results'], TRunnerResult)

    def test_runner_repeat(self):
        all_results = self.runner.run()
        assert len(
            [item for item in all_results if item[0]['args'] == [
                'tests/test.py::TestTest::test_success']]) == 3

    @classmethod
    def teardown_class(cls):
        os.system(f'rm -rf {repo_path}')
