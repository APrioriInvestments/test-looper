
import json
import pytest
import uuid

from .runner import CommandRunner, TestRunnerResult, TestSummary, TestCaseResult, TestStep


class PytestRunner(CommandRunner):

    def __init__(self, repo_dir: str, pytest_args: list[str]):
        super().__init__(repo_dir, pytest_args)

    def run_tests(self):
        report_file_name = f'.test-looper-report-{uuid.uuid4()}'
        full_args = self.args
        full_args.append('--json-report')
        full_args.append('--json-report-file')
        full_args.append(report_file_name)
        with self.chdir():
            retcode = pytest.main(full_args)
            return {
                'retcode': retcode,
                'results': parse_report(report_file_name)
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
            num_succeeded=summary['passed'],
            num_failed=summary['failed']
        )
        test_case_results = [
            parse_testcase_results(rs) for rs in data['tests']
        ]
        return TestRunnerResult(summary, test_case_results)


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