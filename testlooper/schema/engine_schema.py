import time
from enum import Enum

from abc import ABC, abstractmethod
from object_database import Index, Indexed, service_schema
from typed_python import Alternative, NamedTuple, OneOf, TupleOf, ListOf
from .schema_declarations import engine_schema, repo_schema, test_schema


def dereference(self) -> "TaskBase":
    """Finds the Task in the database and returns it. The complement to TaskBase.reference"""
    if self.matches.TestPlanGeneration:
        return engine_schema.TestPlanGenerationTask.lookupUnique(commit=self.commit)
    elif self.matches.BuildDockerImage:
        return engine_schema.BuildDockerImageTask.lookupUnique(
            commit_and_image=(self.commit, self.image)
        )
    elif self.matches.TestSuiteGeneration:
        return engine_schema.TestSuiteGenerationTask.lookupUnique(
            commit_and_name=(self.commit, self.name)
        )
    elif self.matches.TestSuiteRun:
        return engine_schema.TestSuiteRunTask.lookupUnique(uuid=self.uuid)
    elif self.matches.CommitTestDefinitionGeneration:
        return engine_schema.CommitTestDefinitionGenerationTask.lookupUnique(
            commit=self.commit
        )
    elif self.matches.GenerateTestConfig:
        return engine_schema.GenerateTestConfigTask.lookupUnique(commit=self.commit)
    else:
        raise TypeError(f"Unknown task type {self}")


# Used to pass information about tasks between the dispatcher and the workers.
TaskReference = Alternative(
    "TaskReference",
    TestPlanGeneration=dict(commit=repo_schema.Commit),
    BuildDockerImage=dict(commit=repo_schema.Commit, image=str),
    TestSuiteGeneration=dict(commit=repo_schema.Commit, name=str),
    TestSuiteRun=dict(
        uuid=str,
    ),
    CommitTestDefinitionGeneration=dict(commit=repo_schema.Commit),
    GenerateTestConfig=dict(commit=repo_schema.Commit),
    dereference=dereference,
)


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


class TaskBase(ABC):
    timeout_seconds = OneOf(None, float)
    _status_history = TupleOf(StatusChange)
    dependencies = ListOf(object)  # these should be TaskBases

    @abstractmethod
    def reference(self) -> TaskReference:
        """Must return a TaskReference with enough information to run lookupUnique on the
        Task. This is the complement to TaskReference.lookup()"""
        pass

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

    commit = Indexed(repo_schema.Commit)

    def reference(self):
        return TaskReference.TestPlanGeneration(commit=self.commit)


class ResultBase(ABC):
    task = TaskBase
    error = str


@engine_schema.define
class TestPlanGenerationResult(ResultBase):
    """Keep track of a task to generate a test plan."""

    commit = Indexed(repo_schema.Commit)
    data = OneOf(
        None, test_schema.TestPlan
    )  # YAML file of TestPlan (None if result is a failure)
    task = Indexed(engine_schema.TestPlanGenerationTask)


@engine_schema.define
class BuildDockerImageTask(TaskBase):
    commit = Indexed(repo_schema.Commit)
    # environment_name = str
    dockerfile = str  # path to Dockerfile or its directory
    image = (
        str  # image name and/or tag. Normally <repo_name>.config or <repo_name>.listtests etc
    )
    commit_and_image = Index("commit", "image")

    def reference(self):
        return TaskReference.BuildDockerImage(commit=self.commit, image=self.image)


@engine_schema.define
class BuildDockerImageResult(ResultBase):
    commit = repo_schema.Commit
    environment_name = str
    image = str
    task = Indexed(engine_schema.BuildDockerImageTask)


@engine_schema.define
class TestSuiteGenerationTask(TaskBase):
    commit = Indexed(repo_schema.Commit)
    environment = test_schema.Environment
    name = str
    commit_and_name = Index("commit", "name")
    list_tests_command = str
    run_tests_command = str

    def reference(self):
        return TaskReference.TestSuiteGeneration(commit=self.commit, name=self.name)


@engine_schema.define
class TestSuiteGenerationResult(ResultBase):
    commit = Indexed(repo_schema.Commit)
    suite = OneOf(None, test_schema.TestSuite)
    task = Indexed(engine_schema.TestSuiteGenerationTask)


@engine_schema.define
class TestRunTask(TaskBase):
    """DEPRECATED - either run a specific test on a specific commit, or all tests
    for a suite on a specific commit."""

    # this probably needs a Result to distinguish task failures from test failures.
    test_results = OneOf(None, test_schema.TestResults)
    runs_desired = int
    # environment = Indexed(test_schema.Environment)
    commit = Indexed(repo_schema.Commit)
    suite = Indexed(test_schema.TestSuite)
    commit_suite_and_run = Index("commit", "suite", "test_results")

    def reference(self):
        return TaskReference.TestRun(commit=self.commit, suite=self.suite)


@engine_schema.define
class TestSuiteRunTask(TaskBase):
    """A single run of some, or all, tests in a suite."""

    # environment = Indexed(test_schema.Environment)
    uuid = Indexed(str)
    commit = Indexed(repo_schema.Commit)
    suite = Indexed(test_schema.TestSuite)
    test_node_ids = OneOf(None, ListOf(str))

    def reference(self):
        return TaskReference.TestSuiteRun(uuid=self.uuid)


@engine_schema.define
class CommitTestDefinitionGenerationTask(TaskBase):
    commit = Indexed(repo_schema.Commit)
    test_plan = test_schema.TestPlan

    def reference(self):
        return TaskReference.CommitTestDefinitionGeneration(commit=self.commit)


@engine_schema.define
class GenerateTestConfigTask(TaskBase):
    # test_config = repo_schema.TestConfig
    commit = Indexed(repo_schema.Commit)
    config_path = str  # relative to the repo root

    def reference(self):
        return TaskReference.GenerateTestConfig(commit=self.commit)


ArtifactStoreConfig = Alternative(
    "ArtifactStoreConfig",
    LocalDisk=dict(
        root_path=str,
        build_artifact_prefix=str,
        test_artifact_prefix=str,
    ),
    S3=dict(bucket=str, region=str, build_artifact_prefix=str, test_artifact_prefix=str),
)


@engine_schema.define
class TLConfig:
    """Stores everything needed to run testlooper.
    There should be exactly one of these objects."""

    message_bus_port = int
    message_bus_hostname = str
    git_watcher_port = int
    git_watcher_hostname = str
    log_level = int
    path_to_git_repo = str
    path_to_config = str
    artifact_store_config = ArtifactStoreConfig


@engine_schema.define
class WorkerStatus:
    """Tracks the state of a Worker service instance."""

    instance = Indexed(service_schema.ServiceInstance)
    worker_id = int
    is_busy = bool
    task_start_time = str
    task = str
