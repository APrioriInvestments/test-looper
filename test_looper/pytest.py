
import json
import pytest
import uuid

from collections import defaultdict

from .runner import (
    CommandRunner,
    TestRunnerResult,
    TestSummary,
    TestCaseResult,
    TestStep,
    TestList
)


class PytestRunner(CommandRunner):

    def __init__(self, repo_dir: str, pytest_args: list[str]):
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
        duration=duration,
        setup=parse_step(data['setup']),
        testcase=parse_step(data['call']),
        teardown=parse_step(data['teardown'])
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
                module_name, class_name, test_name = test_item[
                    'nodeid'].split("::")
                try:
                    module_dict = tests_dict[module_name]
                except KeyError:
                    module_dict = defaultdict(list)
                    tests_dict[module_name] = module_dict
                module_dict[class_name].append(test_name)
    return tests_dict
