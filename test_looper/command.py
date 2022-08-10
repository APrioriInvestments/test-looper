"""Execute test commands"""
import contextlib
import os
from abc import ABC, abstractmethod
from collections import defaultdict
import json
from datetime import datetime

import pytest
from typing import List
import uuid


def get_command_runner(repo_dir, command, args):
    if command == 'pytest':
        return PytestRunner(repo_dir, args)
    raise NotImplementedError(f"{command} is not yet supported")


class CommandRunner(ABC):
    """Abstract class to run a given test command"""

    def __init__(self, repo_dir: str, args: List[str]):
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


class PytestRunner(CommandRunner):

    def __init__(self, repo_dir: str, pytest_args: List[str]):
        super().__init__(repo_dir, pytest_args)

    def run_tests(self):
        report_file_name = f'.test-looper-report-{uuid.uuid4()}'
        full_args = self.args.copy()
        full_args.append('--json-report')
        full_args.append('--json-report-file')
        full_args.append(report_file_name)
        with self.chdir():
            retcode = pytest.main(full_args)
            return {
                'retcode': retcode,
                'results': parse_report(report_file_name)
            }

    def list_tests(self):
        """
        I run the tests commands with the --collect-only flag and
        collect the result
        """
        report_file_name = f'.test-looper-test-list-{uuid.uuid4()}'
        full_args = self.args.copy()
        full_args.append('--json-report')
        full_args.append('--json-report-file')
        full_args.append(report_file_name)
        full_args.append('--collect-only')
        with self.chdir():
            retcode = pytest.main(full_args)
            return {
                'retcode': retcode,
                'results': parse_list_report(report_file_name)
            }


def parse_report(file_name):
    with open(file_name) as fh:
        data = json.load(fh)
        summary = data['summary']
        summary = TestSummary(
            environment=data['environment'],
            root=data['root'],
            retcode=data['exitcode'],
            started=data['created'],
            duration=data['duration'],
            num_tests=summary['total'],
            num_succeeded=summary.get('passed', 0),  # for nodeid specified
            num_failed=summary.get('failed', 0)  # tests pytest does not list
        )
        test_case_results = [
            parse_testcase_results(rs) for rs in data['tests']
        ]
        return TestRunnerResult(summary, test_case_results)


def parse_list_report(file_name):
    with open(file_name) as fh:
        data = json.load(fh)
        tests = parse_collector(data)
        return TestList(tests)


def parse_testcase_results(data):
    duration = (data.get('setup', {}).get('duration', 0) +
                data.get('call', {}).get('duration', 0) +
                data.get('teardown', {}).get('duration', 0))
    return TestCaseResult(
        name=data['nodeid'],
        status=data['outcome'],
        duration=duration,  # seconds
        setup=parse_step(data['setup']),
        testcase=parse_step(data.get('call', {})),
        teardown=parse_step(data.get('teardown'))
    )


def parse_step(data):
    return TestStep(
        status=data['outcome'],
        duration=data.get('duration', 0),
        msg=data.get('longrepr'),
        info={
            'crash': data.get('crash', {}),
            'traceback': data.get('traceback', [])
        }
    )


def parse_collector(data):
    """I parse the python test collector list."""
    tests_dict = {}
    for item in data['collectors']:
        for test_item in item['result']:
            if test_item['type'] == 'Function':
                nodeid = test_item['nodeid'].split("::")
                item_dict = dict(zip(range(len(nodeid)), nodeid))
                module_name = item_dict.get(0, "")
                class_name = item_dict.get(1, "")
                test_name = item_dict.get(2, "")
                try:
                    module_dict = tests_dict[module_name]
                except KeyError:
                    module_dict = defaultdict(list)
                    tests_dict[module_name] = module_dict
                module_dict[class_name].append(test_name)
    return tests_dict


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
    def __init__(self, summary: TestSummary, tests: List[TestCaseResult]):
        self.summary = summary
        self.results = tests


class TestList:
    """I contain a dictionary {module: {class: [test]}} of all tests"""
    def __init__(self, tests: dict):
        self.tests = tests
