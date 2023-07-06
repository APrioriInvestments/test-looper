import time
from enum import Enum

from object_database import Indexed, service_schema
from typed_python import Dict, NamedTuple, OneOf, TupleOf

from .schema_declarations import engine_schema, repo_schema, test_schema


class StatusEvent(Enum):
    CREATED = 1
    STARTED = 2
    FAILED = 3
    TIMEDOUT = 4
    COMPLETED = 5


StatusChange = NamedTuple(status=StatusEvent, timestamp=float)


class Status:
    def __init__(self):
        self._history = []  # list of (StatusEvent, Timestamp)
        self._add_status(StatusEvent.CREATED, when=time.time())

    @property
    def history(self):
        """Returns a list of (StatusEvent, Timestamp) tuples."""
        return self._history

    @property
    def latest(self):
        """Returns the most recent (StatusEvent, Timestamp) tuple."""
        return self._history[-1]

    def _add_status(self, status: StatusEvent, when: float):
        self._history.append((status, when))

    def start(self):
        if self.latest[0] != StatusEvent.CREATED:
            raise RuntimeError("Can't start a task that's already started.")
        self._add_status(StatusEvent.STARTED, time.time())

    def fail(self):
        if self.latest[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't fail a task that's not started.")
        self._add_status(StatusEvent.FAILED, time.time())

    def timeout(self):
        if self.latest[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't timeout a task that's not started.")
        self._add_status(StatusEvent.TIMEDOUT, time.time())

    def completed(self):
        if self.latest[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't complete a task that's not started.")
        self._add_status(StatusEvent.COMPLETED, time.time())


@engine_schema.define
class TaskBase:
    timeout_seconds = OneOf(float, None)
    _status_history = TupleOf(StatusChange)

    @classmethod
    def create(cls, *args, when=None, **kwargs):
        if when is None:
            when = time.time()
        if "timeout_seconds" not in kwargs:
            # otherwise timeout_seconds is set to 0.
            timeout_seconds = None
            c = cls(*args, timeout_seconds=timeout_seconds, **kwargs)
        else:
            c = cls(*args, **kwargs)
        c._add_status(StatusEvent.CREATED, when)

        return c

    def _add_status(self, status: StatusEvent, when: float):
        tu = StatusChange(status=status, timestamp=when)
        updated = self._status_history + [tu]
        self._status_history = updated

    @property
    def status_history(self):
        """Returns a list of (StatusEvent, Timestamp) tuples."""
        return self._status_history

    @property
    def status(self):
        """Returns the most recent (StatusEvent, Timestamp) tuple."""
        return self._status_history[-1]

    def started(self, when: float):
        if self.status[0] != StatusEvent.CREATED:
            raise RuntimeError("Can't start a task that's already started.")
        self._add_status(StatusEvent.STARTED, when)

    def failed(self, when: float):
        if self.status[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't fail a task that's not started.")
        self._add_status(StatusEvent.FAILED, when)

    def timeout(self, when: float):
        if self.status[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't timeout a task that's not started.")
        self._add_status(StatusEvent.TIMEDOUT, when)

    def completed(self, when: float):
        if self.status[0] != StatusEvent.STARTED:
            raise RuntimeError("Can't complete a task that's not started.")
        self._add_status(StatusEvent.COMPLETED, when)


@engine_schema.define
class TestPlanGenerationTask(TaskBase):
    """Keep track of a task to generate a test plan."""

    commit = repo_schema.Commit


@engine_schema.define
class ResultBase:
    task = engine_schema.TaskBase
    error = str


@engine_schema.define
class TestPlanGenerationResult(ResultBase):
    """Keep track of a task to generate a test plan."""

    # TODO (Will): resolve the overlap between this and CommitTestDefinition
    commit = Indexed(repo_schema.Commit)
    data = OneOf(
        None, test_schema.TestPlan
    )  # YAML file of TestPlan (None if result is a failure)
    task = Indexed(engine_schema.TestPlanGenerationTask)


@engine_schema.define
class BuildDockerImageTask:
    commit = repo_schema.Commit
    environment_name = str
    dockerfile = str  # path to Dockerfile or its directory
    image = str  # image name and/or tag
    status = Status


@engine_schema.define
class BuildDockerImageResult:
    commit = repo_schema.Commit
    environment_name = str
    image = str


@engine_schema.define
class TestSuiteGenerationTask(TaskBase):
    commit = Indexed(repo_schema.Commit)  # TODO this index is likely temporary
    environment = test_schema.Environment
    # map of build name to build path, optional
    dependencies = OneOf(Dict(str, str), None)
    name = str
    list_tests_command = str
    run_tests_command = str


@engine_schema.define
class TestSuiteGenerationResult(ResultBase):
    commit = Indexed(repo_schema.Commit)
    suite = OneOf(None, test_schema.TestSuite)
    task = Indexed(engine_schema.TestSuiteGenerationTask)


@engine_schema.define
class TestRunTask(TaskBase):
    """either run a specific test on a specific commit, or all tests
    for a suite on a specific commit."""

    # this probably needs a Result to distinguish task failures from test failures.
    test_results = OneOf(None, test_schema.TestResults)
    runs_desired = int
    # environment = Indexed(test_schema.Environment)
    commit = Indexed(repo_schema.Commit)
    suite = Indexed(test_schema.TestSuite)


@engine_schema.define
class CommitTestDefinitionGenerationTask(TaskBase):
    commit = Indexed(repo_schema.Commit)
    test_plan = test_schema.TestPlan


@engine_schema.define
class LocalEngineConfig:
    path_to_git_repo = str


@engine_schema.define
class GitWatcherConfig:
    service = Indexed(service_schema.Service)
    port = int
    hostname = str
    log_level = int
