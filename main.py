#!/usr/bin/env python
"""Quick test of the test runner for a single repo"""
import pathlib
import uuid
import click
import shutil

from object_database import connect

from test_looper import test_looper_schema
from test_looper.service import LooperService
from test_looper.parser import ParserService
from test_looper.runner import RunnerService, DispatchService
from test_looper.test_schema import TestResults
from test_looper.tl_git import GIT


def init_test_repo():
    # copy template repo and turn it into a git repo
    tmp_path = pathlib.Path('/tmp') / str(uuid.uuid4())
    dst_path = str(tmp_path / '_template_repo')
    repo = str(pathlib.Path(__file__).parent / "tests" / "_template_repo")
    shutil.copytree(repo, dst_path)
    GIT().init_repo(dst_path)
    return dst_path


@click.command()
@click.option('-h', '--host', default='localhost')
@click.option('-p', '--port', default='8000')
@click.option('-t', '--token', default='TOKEN')
def main(host, port, token):
    repo_path = init_test_repo()
    odb = connect(host, port, token)
    odb.subscribeToSchema(test_looper_schema)

    # the idea here is that these different services
    # implement their own event loops and could run
    # in a distributed fashion as long as they're
    # all interacting with the same ODB

    # Register a repo and scan all branches for commits
    looper = LooperService(odb)
    looper.add_repo('template_repo', repo_path)
    looper.scan_repo('template_repo', branch="*")

    # Parse commits and create test plan
    parser = ParserService(odb)
    parser.parse_commits()

    # create a dispatcher to assign TestNodes
    dispatch = DispatchService(odb)
    # register a worker
    runner = RunnerService(odb, "tout seul")

    dispatch.assign_nodes()  # this will assign it to the runner
    runner.run_test()

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
