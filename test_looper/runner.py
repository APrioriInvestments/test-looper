# The TestRunner class provides methods for running tests
# capturing and processing output
import contextlib
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime


class TestRunner:
    """
    Run the tests for a given repo (excluding repo dependencies)
    """

    def __init__(self, repo_dir: str, runner_file_name='test_looper.json'):
        self.repo_dir = repo_dir
        self.runner_file = os.path.join(repo_dir, runner_file_name)
        self._test_commands = None

    @property
    def test_commands(self):
        if self._test_commands is None:
            self.setup()
        return self._test_commands

    def setup(self):
        """
        I read in the test commands from self.runner_file
        and setup capture of test output
        """
        if not os.path.isfile(self.runner_file):
            raise FileNotFoundError(
                f"Test runner file {self.runner_file} not found: exiting!"
            )
        command_data = json.loads(open(self.runner_file).read())
        self._test_commands = command_data["test_commands"]

    def run(self):
        results = []
        for command in self.test_commands:
            runner = get_command_runner(self.repo_dir,
                                        command["command"].lower().strip(),
                                        command["args"])
            results.append((command, runner.run_tests()))
        return results


def get_command_runner(repo_dir, command, args):
    if command == 'pytest':
        from .pytest import PytestRunner
        return PytestRunner(repo_dir, args)
    raise NotImplementedError(f"{command} is not yet supported")


class CommandRunner(ABC):
    """Abstract class to run a given test command"""

    def __init__(self, repo_dir: str, args: list[str]):
        self.repo_dir = repo_dir
        self.args = args

    @contextlib.contextmanager
    def chdir(self):
        old_dir = os.getcwd()
        os.chdir(self.repo_dir)
        try:
            yield
        finally:
            os.chdir(old_dir)

    @abstractmethod
    def run_tests(self):
        pass


class TestSummary:
    """Summary statistics for a given test command invocation"""

    def __init__(self,
                 environment: dict,
                 root: str,
                 retcode: int,
                 started: float,
                 duration: float,
                 num_tests: int,
                 num_succeeded: int,
                 num_failed: int):
        self.environment = environment
        self.root = root
        self.retcode = retcode
        self.started = datetime.fromtimestamp(started)
        self.duration = duration
        self.num_tests = num_tests
        self.num_succeeded = num_succeeded
        self.num_failed = num_failed


class TestStep:
    """Stats for a given step of a test case (setup, test case call, teardown)"""

    def __init__(self, status: str, duration: float, msg: str, info: dict):
        self.status = status
        self.duration = duration
        self.msg = msg
        self.info = info


class TestCaseResult:
    """Results for a single test case"""
    def __init__(self,
                 name: str,
                 status: str,
                 duration: float,
                 setup: TestStep,
                 testcase: TestStep,
                 teardown: TestStep):
        self.name = name
        self.status = status
        self.duration = duration
        self.setup = setup
        self.testcase = testcase
        self.teardown = teardown


class TestRunnerResult:
    """Result wrapper for a single test command invocation"""
    def __init__(self, summary: TestSummary, tests: list[TestCaseResult]):
        self.summary = summary
        self.results = tests

