import logging
from threading import RLock
import time
import uuid

import object_database.web.cells as cells


from collections import deque, defaultdict
from object_database import Reactor, ServiceBase
from object_database.message_bus import MessageBus, ConnectionId
from typed_python import SerializationContext
from typing import Set, List, Dict

from testlooper.messages import Request, Response, DISPATCHED_TASKS
from testlooper.schema.engine_schema import StatusEvent, ArtifactStoreConfig
from testlooper.utils import (
    parse_test_filter,
    setup_logger,
    parse_test_filter,
    get_node_id,
)
from testlooper.schema.schema import engine_schema, test_schema, repo_schema


class DispatcherService(ServiceBase):
    """Stand up, and starts a message bus.

    Methods:
    - boot
    - configure the bus
    - monitor the db via various reactors.
    - the reactors will spot new work, and send a message with sufficient info for the worker
      to do the work.

    Decision:
    - do we want the worker to message when its started and finished? Currently it get messages
      when done, dispatcher handles when free.
    """

    def initialize(self):
        self.db.subscribeToSchema(engine_schema, test_schema, repo_schema)
        with self.db.view():
            config = engine_schema.TLConfig.lookupUnique()
            if config is None:
                raise RuntimeError("No message bus config found - did you run configure()?")
            self.hostname = config.message_bus_hostname
            self.port = config.message_bus_port
            self._logger = setup_logger(__name__, level=config.log_level)
        self.bus_is_active = False
        self._workers: Set[ConnectionId] = set()  # , bool] = {}
        self._free_workers: Set[ConnectionId] = set()
        self.registerReactor(Reactor(self.db, self.enqueue_tasks, maxSleepTime=1))
        self.registerReactor(
            Reactor(self.db, self.generate_test_suite_runs)
        )  # TODO this won't scale
        self.task_queue = deque()
        self._lock = RLock()
        # self._start_bus()

    def enqueue_tasks(self):
        """This Reactor looks for tasks, and puts them in a queue if they aren't already being
        worked on.

        The main doWork thread of this service will constantly attempt to shrink the queue by
        assigning tasks to workers.

        TODO - better guards on double-processing. Probably the worker sends a 'no ty' message
        and the task gets added back.

        Currently there is a race condition and tasks get multiply added.
        """
        for task_type in DISPATCHED_TASKS:
            # view opening/closing is key here to avoid double-queueing
            with self.db.view():
                tasks = task_type.lookupAll()

            for task in tasks:
                self._lock.acquire()
                if task not in self.task_queue:
                    with self.db.view():
                        if task.status[0] is StatusEvent.CREATED:
                            # this assumes implicitly that the dependency is in
                            # DISPATCHED_TASKS, so the Reactor will wake up and check again
                            # when the dependency is done.
                            for dep in task.dependencies:
                                if dep.status[0] is not StatusEvent.COMPLETED:
                                    break
                            else:
                                # only executes if all dependencies are completed
                                self.task_queue.append(task)
                self._lock.release()

    def generate_test_suite_runs(self):
        """Look for new or updated CommitDesiredTesting objects, and generate TestSuiteRunTasks
        as required.
        """

        with self.db.view():
            commit_desired_testings = test_schema.CommitDesiredTesting.lookupAll()

        for commit_desired_testing in commit_desired_testings:
            with self.db.view():
                commit = commit_desired_testing.commit
                runs_requested = commit_desired_testing.desired_testing.runs_desired
                commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(
                    commit=commit
                )
            if commit_test_definition is not None:
                # ensure this only runs after all test suites have been generated for this
                # commit
                if self._all_test_suites_generated(commit):
                    # parse the desired_testing, compare to the suites we have already have
                    affected_tests = self._process_desired_testing(commit_desired_testing)

                    # now we have a set of TestResults. Compare the runs_desired of our
                    # desired_testing to the runs_desired of the result.
                    suite_to_runs_map = self._get_number_of_new_runs(
                        runs_requested, affected_tests
                    )

                    # for each suite, generate a TestSuiteRunTask
                    with self.db.transaction():
                        for suite, list_of_test_results in suite_to_runs_map.items():
                            for test_results in list_of_test_results:
                                node_ids = []
                                for result in test_results:
                                    result.runs_desired += 1
                                    node_ids.append(get_node_id(result.test))
                                assert len(node_ids) == len(test_results)
                                _ = engine_schema.TestSuiteRunTask.create(
                                    commit=commit,
                                    suite=suite,
                                    test_node_ids=node_ids,
                                    uuid=str(uuid.uuid4()),
                                )

                                self._logger.error(
                                    f"Made a TestSuiteRunTask for suite {suite.name},",
                                    f"commit {commit.hash}, with {len(test_results)} tests.",
                                )

    def _all_test_suites_generated(self, commit) -> bool:
        """Return True if every TestSuiteGenerationTask for this commit has finished
        (regardless of status)."""
        with self.db.view():
            tasks = engine_schema.TestSuiteGenerationTask.lookupAll(commit=commit)
            return all(
                task.status[0]
                in (StatusEvent.COMPLETED, StatusEvent.FAILED, StatusEvent.TIMEDOUT)
                for task in tasks
            )

    def _process_desired_testing(self, commit_desired_testing) -> Set[test_schema.TestResults]:
        """This will compare the desired_testing to the TestResults we have for each suite,
        and output a list of test results matching our filter."""
        with self.db.view():
            commit = commit_desired_testing.commit
            test_filter = commit_desired_testing.desired_testing.filter
            # get the results of trimming that through the filter.
        all_test_results = self._generate_all_test_results(commit)
        filtered_tests = parse_test_filter(self.db, test_filter, all_test_results)

        if not filtered_tests:
            self._logger.error(f"Test filter {test_filter} matched no tests.")

        return filtered_tests

    def _generate_all_test_results(self, commit):
        all_test_results = set()
        with self.db.transaction():
            ctd = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
            for suite in ctd.test_suites.values():
                for test in suite.tests.values():
                    if (
                        tr := test_schema.TestResults.lookupUnique(
                            test_and_commit=(test, commit)
                        )
                    ) is None:
                        tr = test_schema.TestResults(
                            test=test,
                            commit=commit,
                            suite=suite,
                            runs_desired=0,
                            results=[],
                        )
                    all_test_results.add(tr)
        return all_test_results

    def _get_number_of_new_runs(
        self, runs_requested, affected_tests: Set[test_schema.TestResults]
    ) -> Dict[test_schema.TestSuite, List[List[test_schema.TestResults]]]:
        """Given a set of TestResults matched by our filter, loop over each one. For each,
        get the suite it belongs to and the total number of new runs we need.

        End result will be suite -> list of lists of test names, where each sublist
        corresponding to something we can run as a single command.
        """

        suite_to_runs_map = defaultdict(list)
        with self.db.view():
            for test_result in affected_tests:
                suite = test_result.suite
                new_runs = runs_requested - test_result.runs_desired
                if new_runs > 0:
                    for i in range(new_runs):
                        try:
                            suite_to_runs_map[suite][i].append(test_result)
                        except IndexError:
                            suite_to_runs_map[suite].append([test_result])

        return suite_to_runs_map

    def _start_bus(self):
        self.bus = MessageBus(
            busIdentity="TLMessageBusDispatcher",
            endpoint=(self.hostname, self.port),
            inMessageType=Response,
            outMessageType=Request,
            onEvent=self._on_event,
            authToken="tl_auth_token",
            serializationContext=SerializationContext(),
            certPath=None,
            wantsSSL=True,
            sslContext=None,
            extraMessageSizeCheck=True,
        )
        self.bus.start()
        self._logger.info("Bus started")

    def doWork(self, shouldStop):
        """This is the main loop of the service.

        It ensures the bus is started, then constantly tries to knock down tasks in the queue,
        by processing them into a form such that the Worker can run them most effectively.

        To start with, don't batch stuff up. Just make the reference to the task, and send it
        to the worker. Currently has a race condition between task dispatch and task start
        that must be guarded against (as best possible).
        """
        with self.reactorsRunning():
            while not shouldStop.is_set():
                if not self.bus_is_active:
                    self._start_bus()
                    self.bus_is_active = True
                if self._free_workers and self.task_queue:
                    # print('tasks in queue:', '\n'.join(map(str, self.task_queue)))
                    self._lock.acquire()
                    worker = self._free_workers.pop()
                    task = self.task_queue.popleft()
                    with self.db.view():
                        status = task.status[0]
                        payload = task.reference()
                    if status is not StatusEvent.CREATED:
                        self._logger.info(f"Task {task} was already started, skipping...")
                    else:
                        self._logger.info(f"Assigning task {task} to worker {worker}")
                        self.bus.sendMessage(worker, Request.v1(payload=payload))
                    self._lock.release()
                else:
                    self._logger.debug("No free workers or no tasks to assign, waiting...")
                    time.sleep(0.1)

    def _on_event(self, event):
        """Triggered whenever a message is received."""
        if event.matches.NewIncomingConnection:
            self._add_worker_to_pool(event.connectionId)
            self._logger.warning(f"Set up connection {event.connectionId} from {event.source}")
        elif event.matches.IncomingConnectionClosed:
            self._remove_worker_from_pool(event.connectionId)
            self._logger.warning(f"Incoming connection {event.connectionId} closed.")

        elif event.matches.IncomingMessage:
            self._handle_message(event.connectionId, event.message)
        else:
            self._logger.error(f"Unexpected message of type {type(event)}")

    def _add_worker_to_pool(self, connection_id: ConnectionId):
        """Add the worker to the pool, checking it's not already there."""
        if connection_id in self._workers:
            self._logger.error(f"Worker {connection_id} already in pool.")
            return

        self._workers.add(connection_id)
        self._free_workers.add(connection_id)

    def _remove_worker_from_pool(self, connection_id: ConnectionId):
        """Remove the worker from the pool, checking it's there."""
        if connection_id not in self._workers:
            self._logger.error("Worker {connection_id} not in pool.")
        self._workers.remove(connection_id)
        if connection_id in self._free_workers:
            self._free_workers.remove(connection_id)

    def _handle_message(self, connection_id, message):
        """Process the WorkerRequest. This should be of the form:
        - i've finished my work, give me work
        - i'm still alive, give me work
        thus we only except the message to be of a single type, and take a single action.
        TODO - handle other kinds of message
        """
        if not message.matches.v1:
            self._logger.error(f"Unexpected message version: {type(message)}")
            return

        if message.message:
            if message.task_succeeded:
                self._logger.debug(f"Worker {connection_id} has processed task successfully")
            else:
                self._logger.warning(f"Worker {connection_id} has failed to process task")
            self._free_workers.add(connection_id)

        # self._logger.warning(f"Got a message {message} from {connection_id}")

    @staticmethod
    def configure(
        db,
        service_object,
        hostname: str,
        port: str,
        path_to_git_repo: str,
        artifact_store_config: ArtifactStoreConfig,
        log_level_name=None,
    ):
        """Tell the dispatcher (and worker) what port and hostname to talk to each other on."""
        db.subscribeToSchema(engine_schema)
        with db.transaction():
            c = engine_schema.TLConfig.lookupUnique()
            if not c:
                c = engine_schema.TLConfig
            c.message_bus_hostname = hostname
            c.message_bus_port = port
            c.path_to_git_repo = path_to_git_repo
            if log_level_name:
                c.log_level = logging.getLevelName(log_level_name)
            c.artifact_store_config = artifact_store_config

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        return cells.Text("Dispatcher Service")
