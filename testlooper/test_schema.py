from typed_python import OneOf, TupleOf, NamedTuple, ListOf, ConstDict, Alternative, Dict
from object_database import Indexed, Index, SubscribeLazilyByDefault

from .schema_declarations import repo_schema, test_schema


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


DesiredTesting = NamedTuple(
    runs_desired=int,
    fail_runs_desired=int,  # how many runs for any tests that fail
    flake_runs_desired=int,  # how many runs for tests that are known to flake
    new_runs_desired=int,  # how may runs for new tests
    filter=TestFilter,
)


@test_schema.define
class BranchDesiredTesting:
    """Describes our DesiredTesting config for a branch.

    We can have at most one BranchDesiredTesting per repo_schema.Branch instance

    Each time new commits appear on a branch that has a BranchDesiredTesting
    associated with it, a corresponding CommitDesiredTesting is created for
    top commit of that branch.
    """

    branch = Indexed(repo_schema.Branch)
    desired_testing = DesiredTesting

    def apply_to(self, commit):
        assert isinstance(commit, repo_schema.Commit), commit

        commit_dt = test_schema.CommitDesiredTesting.lookupUnique(commit=commit)
        if commit_dt is None:
            test_schema.CommitDesiredTesting(
                commit=commit, desired_testing=self.desired_testing
            )

        else:
            commit_dt.update_desired_testing(self.desired_testing)


@test_schema.define
class CommitDesiredTesting:
    """Describes our desired DesiredTesting for a commit

    We can have at most one CommitDesiredTesting per repo_schema.Commit instance.

    These objects are created by applying a BranchDesiredTesting to a commit.
    """

    commit = Indexed(repo_schema.Commit)
    desired_testing = DesiredTesting

    # Index plan to easily grab those whose plan needs to be generated
    test_plan = Indexed(OneOf(None, test_schema.TestPlan))
    test_suites = Dict(str, test_schema.TestSuite)

    def update_desired_testing(self, desired_testing):
        # TODO: do we need to trigger engine events such as TestSuiteGenerationTask?
        self.desired_testing = desired_testing

    def set_test_plan(self, test_plan):
        assert isinstance(test_plan, test_schema.TestPlan), test_plan

        if self.test_plan is not None:
            raise RuntimeError(
                f"Cannot set_test_pan on commit {self.commit.hash} because it already has one"
            )

        self.test_plan = test_plan


Image = Alternative(
    "Image",
    AMI=dict(name=str),
    DockerImage=dict(name=str),
    Dockerfile=dict(path=str),
)


@test_schema.define
class Environment:
    """An environment where tests may run"""

    name = str
    variables = ConstDict(str, str)  # Environment Variables
    image = Image
    min_ram_gb = float
    min_cores = int
    custom_setup = str  # additional bash commands to set up the environment


@test_schema.define
class TestPlan:
    """Contents of YAML file produced by running generate-test-plan on a Commit."""

    plan = Indexed(str)


@test_schema.define
class TestSuite:
    """Definition of a named collection of Tests

    Generated when list-tests for this suite is executed because we want to
    run some of its tests.

    The 'parent' allows us to track test-suites over time as tests get added,
    removed, renamed, etc
    """

    name = Indexed(str)
    environment = test_schema.Environment
    tests = TupleOf(test_schema.Test)  # unique; sorted treated as a frozenset

    parent = OneOf(None, test_schema.TestSuite)  # Most recent ancestor
    _hash = OneOf(None, int)

    @property
    def is_new(self):
        return True if self.parent is None else False

    def __hash__(self):
        if self._hash is None:
            self._hash = hash(tuple(hash(test.name) for test in self.tests))
        return self._hash

    def new_tests(self):
        """Returns a list of tests that are new in this test-suite"""
        return [test for test in self.tests if test.is_new]

    def deleted_tests(self):
        """Return a list of test from the parent test suite that we don't have."""
        if self.parent is None:
            return []

        parent_tests = {test.name: test for test in self.parent.tests}
        for test in self.tests:
            if test.parent is not None:
                del parent_tests[test.parent.name]

        return list(parent_tests.values())

    def renamed_tests(self):
        if self.parent is None:
            return []

        return [test for test in self.tests if test.parent and test.parent.name != test.name]


@test_schema.define
class Test:
    """Definition of a Test

    May belong to more than one TestSuite object (for different commits)
    Its name is unique within a TestSuite and also within a commit, but not
    necessarily across commits because the labels might be different.
    """

    name = Indexed(str)
    labels = TupleOf(str)
    name_and_labels = Index("name", "labels")  # unique
    path = str

    parent = OneOf(None, test_schema.Test)  # Most recent ancestor

    @property
    def is_new(self):
        return True if self.parent is None else False


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
    duration_ms=float,  # time taken in ms
    start_time=int,  # epoch time
    stages=ConstDict(str, StageResult),  # stages are usually setup | call | teardown
)


@test_schema.define
@SubscribeLazilyByDefault
class TestResults:
    """Results of running a test on a commit

    An instance is created upon determining we need this test to run on a commit
    """

    test = Indexed(test_schema.Test)
    commit = Indexed(repo_schema.Commit)
    test_and_commit = Index("test", "commit")  # unique

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
