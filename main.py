#!/usr/bin/env python
"""Quick test of the test runner for a single repo"""
import click

from test_looper.test_schema import TestResults
from test_looper.utils.services import run_tests

@click.command()
@click.option('-h', '--host', default='localhost')
@click.option('-p', '--port', default='8000')
@click.option('-t', '--token', default='TOKEN')
def main(host, port, token):
    odb = run_tests(host, port, token)
    with odb.view():
        for tr in TestResults.lookupAll():
            print(f'{tr.node.name} has {tr.node.testsDefined} tests defined')
            print(f'{tr.node}')
            for tcr in tr.results:
                print(
                    f'{tcr.testName} {"passed" if tcr.success else "failed" } \
                    in {tcr.executionTime}ns'
                )

    # you should see something like:
    # template_repo-tests-0 has 2 tests defined
    # tests/test_cases.py::test_success passed in 409998ns
    # tests/test_cases.py::test_fail failed in 548949ns


if __name__ == '__main__':
    # make sure you start a fresh ODB server
    main()
