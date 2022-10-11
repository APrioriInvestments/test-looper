"""Test runner service"""
import os.path
import threading
import time
import uuid

from object_database import ServiceBase, Reactor
from object_database.database_connection import DatabaseConnection

from test_looper import test_looper_schema
from test_looper.command import get_command_runner, TestRunnerResult
from test_looper.repo_schema import Repository
from test_looper.test_schema import TestNode, Worker, TestResults, TestResult, TestNodeDefinition
from test_looper.tl_git import GIT
from test_looper.utils.db import transaction


class RunnerService(ServiceBase):
    """
    A RunnerService will run on a test-looper worker. It will look in odb for
    assigned TestNode's and execute the tests that are assigned to it. Once
    completed it will put TestResults back in ODB then go back to looking for
    assignments.

    Once every 10s, this runner should send a heartbeat (to ODB), so that bad
    workers can be killed by the overall system
    """

    def __init__(self,
                 db: DatabaseConnection,
                 serviceObject,
                 serviceRuntimeConfig,
                 repo_url: str = "/tmp/test_looper/repos",
                 worker_id: str = "worker-0"):
        super(RunnerService, self).__init__(db, serviceObject, serviceRuntimeConfig)
        self.repo_url = repo_url
        self.worker_id = worker_id

    def initialize(self):
        self.db.subscribeToSchema(test_looper_schema)
        self._init_worker()
        runner_reactor = Reactor(self.db, self.run_test)
        self.registerReactor(runner_reactor)
        self.startReactors()

    def _init_worker(self):
        with self.db.transaction():
            worker = Worker.lookupAll(workerId=self.worker_id)
            if len(worker) > 1:
                raise ValueError("Duplicate worker")
            if len(worker) == 0:
                Worker(workerId=self.worker_id,
                       startTimestamp=time.time_ns(),
                       lastHeartbeatTimestamp=time.time_ns())

    def doWork(self, shouldStop: threading.Event):
        print("In doWork")
        with self.reactorsRunning():
            print("Heartbeating")
            self.heartbeat()
            shouldStop.wait(10)

    @transaction
    def heartbeat(self):
        worker = Worker.lookupOne(workerId=self.worker_id)
        worker.lastHeartbeatTimestamp = time.time_ns()
        return worker.lastHeartbeatTimestamp

    @transaction
    def run_test(self):
        print("Running tests")
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
            is_found, clone_path = self.get_clone(test_node.commit.repo)
            if not is_found:
                raise FileNotFoundError(f"{clone_path} not found; "
                                        f"can't run tests")
            self._run_test_commands(clone_path, test_node)
        elif isinstance(test_def, TestNodeDefinition.Build):
            raise NotImplementedError()
        elif isinstance(test_def, TestNodeDefinition.Docker):
            raise NotImplementedError()

    @staticmethod
    def _run_test_commands(repo_path: str, test_node: TestNode):
        GIT().checkout(repo_path, test_node.commit.sha)
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

    def get_clone(self, repo: Repository):
        clone_path = os.path.join(self.repo_url, repo.name)
        is_found = os.path.exists(clone_path)
        return is_found, clone_path
