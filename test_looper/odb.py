#!/usr/bin/env python
"""Integration with object database"""
from collections import defaultdict

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
                needsMoreWork=True
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


if __name__ == '__main__':
    from test_looper.runner import TestRunner

    runner = TestRunner(repo_dir='..',
                        runner_file_name='test_looper.json')
    runner.setup()
    all_tests = runner.list()

    from object_database import connect
    db = connect('localhost', 8000, 'TOKEN')
    reporter = OdbReporter(db)
    [reporter.report_tests(test_list['results'].tests)
     for command, test_list in all_tests]
