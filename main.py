#!/usr/bin/env python
"""Quick test of the test runner for a single repo"""
import click

from test_looper.runner import TestRunner


@click.command()
@click.option('-r', '--repo', default='.')
@click.option('-f', '--file', default='test_looper.json')
def run(repo, file):
    runner = TestRunner(repo_dir=repo, runner_file_name=file)
    runner.setup()
    runner.run()


if __name__ == '__main__':
    run()
