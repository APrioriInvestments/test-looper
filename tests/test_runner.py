"""Test the test runner service"""
import pathlib

import pytest
from object_database.database_connection import DatabaseConnection

from test_looper.repo_schema import Commit
from test_looper.runner import RunnerService, DispatchService
from test_looper.test_schema import TestNode as TNode, TestResults as TResults
from test_looper.test_schema import Worker
from test_looper.tl_git import GIT
from test_parser import parser_service


@pytest.fixture
def dispatcher(odb_conn: DatabaseConnection,
               tl_config: dict) -> DispatchService:
    return DispatchService(odb_conn)


@pytest.fixture
def runner(odb_conn: DatabaseConnection,
           tl_config: dict) -> RunnerService:
    return RunnerService(odb_conn, "tout seul")


def test_assign_nodes(parser_service, dispatcher, runner):
    parser_service.parse_commits()
    with dispatcher.db.view():
        nodes = TNode.lookupAll()
        for n in nodes:
            assert n.needsMoreWork
            assert not n.isAssigned
        w = Worker.lookupUnique()
        assert w.currentAssignment is None

    dispatcher.assign_nodes()

    with dispatcher.db.view():
        active_node = None
        nodes = TNode.lookupAll()
        total_assigned = 0
        for n in nodes:
            if n.isAssigned:
                active_node = n
                total_assigned += 1
        assert total_assigned == 1

        w = Worker.lookupUnique()
        assert w.currentAssignment == active_node


def test_heartbeat(runner):
    ts = runner.heartbeat()
    ts2 = runner.heartbeat()
    assert ts2 > ts


def test_run_test(parser_service, dispatcher, runner):
    parser_service.parse_commits()
    repo_root = pathlib.Path(__file__).parent.parent
    curr_sha = GIT().get_head(repo_root).commit.hexsha
    with runner.db.transaction():
        node = TNode.lookupOne(commit=Commit.lookupOne(sha=curr_sha))
        name = node.name
        assert node.executionResultSummary is None
        node.isAssigned = True
        w = Worker.lookupOne(workerId=runner.worker_id)
        w.currentAssignment = node
    runner.run_test()
    with runner.db.view():
        c = Commit.lookupOne(sha=curr_sha)
        node = TNode.lookupOne(commitAndName=(c, name))
        assert node.executionResultSummary == "Success"
        assert node.testsDefined > 0

        results = TResults.lookupOne(node)



