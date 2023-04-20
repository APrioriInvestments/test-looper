from typed_python import OneOf, Alternative, TupleOf, Dict, NamedTuple, ListOf, ConstDict
from object_database import Schema, Indexed, Index, SubscribeLazilyByDefault
from .repo_schema import repo_schema

# schema for test-looper test objects
test_schema = Schema("test_looper_test")


TestFilter = NamedTuple(
    # Result is tests that satisfy:
    # Intersection(
    #     set(test if test.label has a prefix in filter.labels),
    #     set(test if test.path  has a prefix in filter.paths),
    #     set(test if test.suite in filter.suites),
    #     set(test if regex matches test.name),
    # )
    labels=OneOf("Any", None, TupleOf(str)),
    path_prefixes=OneOf("Any", TupleOf(str)),
    suites=OneOf("Any", TupleOf(str)),
    regex=str,
)


TestConfiguration = NamedTuple(
    runs_desired=int,
    fail_runs_desired=int,  # how many runs for any tests that fail
    flake_runs_desired=int,  # how many runs for tests that are known to flake
    new_runs_desired=int,  # how may runs for new tests
    filter=TestFilter,
)


@test_schema.define
class BranchTestConfiguration:
    branch = Indexed(repo_schema.Branch)
    config = TestConfiguration


@test_schema.define
class CommitTestConfiguration:
    commit = Indexed(repo_schema.Commit)
    config = TestConfiguration

    # Index plan to easily grab those whose plan needs to be generated
    plan = Indexed(OneOf(None, test_schema.TestPlan))


@test_schema.define
class TestPlan:
    plan = str  # YAML file contents or path


@test_schema.define
class TestSuite:
    """Definition of a named collection of Tests

    Generated when list-tests for this suite is executed because we want to
    run some of its tests.

    The 'parent' allows us to track suites over time as tests get added, removed, renamed, etc
    """

    name = Indexed(str)
    tests = TupleOf(test_schema.Test)  # unique; sorted treated as a frozenset

    parent = OneOf(None, test_schema.TestSuite)  # Most recent ancestor
    _hash = int

    @property
    def hash(self):
        if not self._hash:
            self._hash = hash(tuple(hash(test.name) for test in self.tests))
        return self._hash

    def new_tests(self):
        return [test for test in self.tests if test.parent is None]


@test_schema.define
class Test:
    """Definition of a Test

    May belong to more than one TestSuite object (for different commits)
    Its name is unique within a TestSuite and also within a commit
    """

    name = Indexed(str)  # unique
    path = str
    labels = TupleOf(str)

    parent = OneOf(None, test_schema.Test)  # Most recent ancestor


# outcomes taken from pytest-json-report; append to add more
Outcome = OneOf(
    "passed",  # all is hunky dory
    "failed",  # an assert was false
    "error",  # an exception happened
    "skipped",  # we didn't run the test
    "xfailed",  # test was marked as xfail and it failed
    "xpassed",  # test was marked as xfail and it passed
)


StageResult = NamedTuple(duration=float, outcome=Outcome)


TestRunResult = NamedTuple(
    uuid=str,  # guid we can use to pull relevant logs from the artifact store
    outcome=Outcome,
    duration=float,
    stages=ConstDict(str, StageResult),  # stages are usually setup | call | teardown
)


@test_schema.define
class TestResults:
    """Results of running a test on a commit

    An instance is created upon determining we need this test to run on a commit
    """

    test = Index(test_schema.Test)
    commit = Index(repo_schema.Commit)
    test_and_commit = Index("test", "commit")

    runs_desired = int

    results = ListOf(TestRunResult)

    # run_* fields below are computed as we add test results to this object
    runs_completed = int

    runs_passed = int
    runs_xpassed = int
    runs_failed = int
    runs_xfailed = int
    runs_errored = int
    runs_skipped = int

    @property
    def runs_pending(self):
        return max(self.runs_desired - self.runs_completed, 0)

    def fail_rate(self, include_xfailed=False):
        fails = self.runs_failed + self.runs_errored

        if include_xfailed:
            fails += self.runs_xfailed

        # avoid a potential division by zero if all the runs were skipped
        if fails > 0:
            return fails / (self.runs_completed - self.runs_skipped)
        else:
            return 0.0

    def add_test_run_results(self, result):
        self.results.append(result)
        self.runs_completed += 1

        outcome = result.outcome
        if outcome == "passed":
            self.runs_passed += 1
        elif outcome == "xpassed":
            self.runs_xpassed += 1
        elif outcome == "failed":
            self.runs_failed += 1
        elif outcome == "xfailed":
            self.runs_xfailed += 1
        elif outcome == "error":
            self.rus_errored += 1
        elif outcome == "skipped":
            self.runs_skipped += 1
        else:
            # TODO: log an error
            pass
