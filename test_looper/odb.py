#!/usr/bin/env python
"""Integration with object database"""
import click
from collections import defaultdict
from object_database import connect
from test_looper.runner import TestRunner
from test_looper.reporter import TestReporter
from test_looper.schema import *


class OdbReporter(TestReporter):

    def __init__(self, db):
        self.db = db
        self.db.subscribeToSchema(test_looper_schema)

    def report_tests(self, tests: dict):
        flattened_tests = _flatten(tests)
        with self.db.transaction():
            node = TestNode(
                name="test",
                executionResultSummary=None,
                testsDefined=len(flattened_tests),
                needsMoreWork=False
            )
            print(node)


def _flatten(tests):
    results = []
    for k, v in tests.items():
        if isinstance(v, list):  # leaf
            results.extend([f'{k}.{c}' for c in v])
        elif isinstance(v, defaultdict):
            results.extend([f'{k}::{c}' for c in _flatten(v)])
        else:
            raise NotImplementedError(f'{type(v)} not supported')
    return results

@click.command()
@click.option('-h', '--host', default='localhost')
@click.option('-p', '--port', default='8000')
@click.option('-t', '--token', default='TOKEN')
def main(host, port, token):

    runner = TestRunner(repo_dir='..',
                        runner_file_name='test_looper.json')
    runner.setup()
    all_tests = runner.list()
    db = connect(host, port, token)
    reporter = OdbReporter(db)
    [reporter.report_tests(test_list['results'].tests)
     for command, test_list in all_tests]

if __name__ == '__main__':
    main()
