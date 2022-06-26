#!/usr/bin/env python
"""Quick test of the test runner for a single repo"""
import click

from test_looper.runner import TestRunner, TestRunnerResult, TestList


@click.command()
@click.option('-r', '--repo', default='.')
@click.option('-f', '--file', default='test_looper.json')
def run(repo, file):
    """Run tests for a given repo"""
    runner = TestRunner(repo_dir=repo, runner_file_name=file)
    runner.setup()
    all_tests = runner.list()
    all_tests_results = all_tests[0][1]
    all_results = runner.run()
    command, results = all_results[0]

    assert set(command.keys()) == set(['command', 'args'])
    assert isinstance(results['retcode'].value, int)
    assert isinstance(results['results'], TestRunnerResult)
    assert len(
        [item for item in all_results if item[0]['args'] == [
            'tests/test_git.py::TestGit::test_success']]) == 3
    assert isinstance(all_tests_results['retcode'].value, int)
    assert isinstance(all_tests_results['results'], TestList)

if __name__ == '__main__':
    run()
