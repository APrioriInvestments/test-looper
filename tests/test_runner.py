"""Test the test runner service"""

import pytest
from object_database.database_connection import DatabaseConnection

from test_looper.runner import RunnerService
from test_looper.test_schema import TestNode as TNode, TestResults as TResults
from test_looper.test_schema import Worker

from test_parser import parser_service, template_repo


@pytest.fixture
def runner(odb_conn: DatabaseConnection,
           tl_config: dict) -> RunnerService:
    service = RunnerService(odb_conn, None, None,
                            repo_url=tl_config["repo_url"],
                            worker_id="tout seul")
    service._init_worker()
    return service


def test_assign_nodes(parser_service, runner):
    parser_service.parse_commits()
    with parser_service.db.view():
        nodes = TNode.lookupAll()
        for n in nodes:
            assert n.needsMoreWork
            assert not n.isAssigned
        w = Worker.lookupUnique()
        assert w.currentAssignment is None

    parser_service.assign_nodes()

    with parser_service.db.view():
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


def test_run_test(parser_service, runner):
    parser_service.parse_commits()
    with runner.db.transaction():
        node = TNode.lookupUnique()
        assert node.executionResultSummary is None
        node.isAssigned = True
        w = Worker.lookupOne(workerId=runner.worker_id)
        w.currentAssignment = node
    runner.run_test()
    with runner.db.view():
        node = TNode.lookupUnique()
        assert node.executionResultSummary == "Success"
        assert node.testsDefined == 2
        assert node.testsFailing == 1

        results = TResults.lookupOne(node=node).results
        assert len(results) == 2
        assert sum([r.success for r in results]) == 1
