#!/usr/bin/env python
"""Quick test of the test runner for a single repo"""
import click

from test_looper.runner import TestRunner, TestRunnerResult


@click.command()
@click.option('-r', '--repo', default='.')
@click.option('-f', '--file', default='test_looper.json')
def run(repo, file):
    """Run tests for a given repo"""
    runner = TestRunner(repo_dir=repo, runner_file_name=file)
    runner.setup()
    all_results = runner.run()
    command, results = all_results[0]

    assert set(command.keys()) == set(['command', 'args'])
    assert isinstance(results['retcode'].value, int)
    assert isinstance(results['results'], TestRunnerResult)


if __name__ == '__main__':
    run()
