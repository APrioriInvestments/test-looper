"""Test runner service"""
import threading
import time
import uuid

from object_database.database_connection import DatabaseConnection

from test_looper.command import get_command_runner, TestRunnerResult
from test_looper.test_schema import TestNode, Worker, TestResults, TestResult, TestNodeDefinition
from test_looper.utils.db import transaction, ServiceMixin


class DispatchService(ServiceMixin):
    """assigns tests to workers"""

    def start(self):
        self.start_threadloop(self.assign_nodes)

    @transaction
    def assign_nodes(self):
        """Find TestNode's the needs more work and assign them to workers"""
        nodes = [n for n in TestNode.lookupAll(needsMoreWork=True) if not n.isAssigned]
        workers = Worker.lookupAll(currentAssignment=None)
        if len(nodes) > 0 and len(workers) > 0:
            self.logger.debug(f"Assigning {len(nodes)} TestNodes to {len(workers)} available workers")
        for i in range(min(len(nodes), len(workers))):
            workers[i].currentAssignment = nodes[i]
            nodes[i].isAssigned = True


class RunnerService(ServiceMixin):
    """Runs tests"""

    def __init__(self, db: DatabaseConnection, worker_id: str):
        super(RunnerService, self).__init__(db)
        self.worker_id = worker_id
        with self.db.transaction():
            worker = Worker.lookupAll(workerId=self.worker_id)
            if len(worker) > 1:
                raise ValueError("Duplicate worker")
            if len(worker) == 0:
                Worker(workerId=self.worker_id,
                       startTimestamp=time.time_ns(),
                       lastHeartbeatTimestamp=time.time_ns())

    def start(self):
        self.start_threadloop(self.heartbeat)
        self.start_threadloop(self.run_test)

    @transaction
    def heartbeat(self):
        worker = Worker.lookupOne(workerId=self.worker_id)
        worker.lastHeartbeatTimestamp = time.time_ns()
        return worker.lastHeartbeatTimestamp

    @transaction
    def run_test(self):
        worker = Worker.lookupOne(workerId=self.worker_id)
        test_node = worker.currentAssignment
        if test_node is not None:
            try:
                self._execute_tests(test_node)
                test_node.executionResultSummary = "Success"
            except TimeoutError:
                test_node.executionResultSummary = "Timeout"
            except Exception:
                test_node.executionResultSummary = "Fail"
            worker.lastTestCompletedTimestamp = time.time_ns()
            worker.currentAssignment = None
            test_node.needsMoreWork = False
            test_node.isAssigned = False

    def _execute_tests(self, test_node: TestNode):
        test_def = test_node.definition
        if isinstance(test_def, TestNodeDefinition.Test):
            test_node.commit.checkout()
            repo_path = test_node.commit.repo.config.path
            self._run_test_commands(repo_path, test_node)
        elif isinstance(test_def, TestNodeDefinition.Build):
            raise NotImplementedError()
        elif isinstance(test_def, TestNodeDefinition.Docker):
            raise NotImplementedError()

    @staticmethod
    def _run_test_commands(repo_path: str, test_node: TestNode):
        test_def = test_node.definition
        parts = test_def.runTests.bashCommand.split(' ')
        runner = get_command_runner(repo_path, parts[0], parts[1:])
        # TODO save json report to artifact url
        # TODO pass in the timeout
        cmd_output = runner.run_tests()
        trr: TestRunnerResult = cmd_output['results']
        test_node.testsDefined = trr.summary.num_tests
        test_node.testsFailing = trr.summary.num_failed
        # TODO parse previous report from artifact url newlyFailing, newlyFixed, executedAtLeastOnce
        results = []
        for case_result in trr.results:
            tr = TestResult(testId=str(uuid.uuid4()),
                            testName=case_result.name,
                            success=case_result.status == "passed",
                            executionTime=int(round(case_result.duration * 1e9)))
            results.append(tr)
        TestResults(node=test_node, results=results)
