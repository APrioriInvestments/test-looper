import time
from typed_python import TupleOf, NamedTuple, Dict, OneOf
from object_database import Indexed
from .schema_declarations import test_schema, engine_schema, repo_schema


from enum import Enum


StatusEvent = Enum("StatusEvent", ["CREATED", "STARTED", "FAILED", "TIMEDOUT", "COMPLETED"])


class Status:
    def __init__(self):
        self._history = []  # list of (StatusEvent, Timestamp)
        self._add_status(StatusEvent.CREATED)

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
        self._add_status(StatusEvent.STARTED)

    def fail(self):
        self._add_status(StatusEvent.FAILED)

    def timeout(self):
        self._add_status(StatusEvent.TIMEDOUT)

    def completed(self):
        self._add_status(StatusEvent.COMPLETED)


class TaskBase:
    _status_history = TupleOf(NamedTuple(status=StatusEvent, timestamp=float))

    def __init__(self, when=None):
        if when is None:
            when = time.time()

        self._add_status(StatusEvent.CREATED, when)

    def _add_status(self, status: StatusEvent, when: float):
        updated = self._status_history + [NamedTuple(status=status, timestamp=when)]

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
        self._add_status(StatusEvent.STARTED, when)

    def failed(self, when: float):
        self._add_status(StatusEvent.FAILED)

    def timeout(self, when: float):
        self._add_status(StatusEvent.TIMEDOUT)

    def completed(self, when: float):
        self._add_status(StatusEvent.COMPLETED)


@engine_schema.define
class TestPlanGenerationTask(TaskBase):
    """Keep track of a task to generate a test plan."""

    commit = repo_schema.Commit


class ResultBase:
    task = engine_schema.TaskBase
    error = str


@engine_schema.define
class TestPlanGenerationResult(ResultBase):
    """Keep track of a task to generate a test plan."""

    # TODO (Will): resolve the overlap between this and CommitTestDefinition
    commit = repo_schema.Commit
    data = test_schema.TestPlan  # YAML file of TestPlan


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
class TestSuiteGenerationTask:
    commit = Indexed(repo_schema.Commit)  # TODO this index is likely temporary
    environment = test_schema.Environment
    # map of build name to build path, optional
    dependencies = OneOf(Dict(str, str), None)
    name = str
    status = Status
    timeout = OneOf(int, None)  # seconds, optional
    list_tests_command = str
    run_tests_command = str


@engine_schema.define
class TestSuiteGenerationResult:
    commit = Indexed(repo_schema.Commit)
    environment = test_schema.Environment
    name = str
    tests = str  # output of list-tests
    status = Status


@engine_schema.define
class TestRunTask:
    test_results = test_schema.TestResults
    runs_desired = int
    environment = Indexed(test_schema.Environment)
    commit = Indexed(repo_schema.Commit)
    status = Status
