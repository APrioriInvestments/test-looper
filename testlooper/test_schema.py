import yaml
from object_database import Index, Indexed, SubscribeLazilyByDefault
from typed_python import Alternative, ConstDict, Dict, ListOf, NamedTuple, OneOf, TupleOf

from .schema_declarations import repo_schema, test_schema, engine_schema
from .engine_schema import Status

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

    def update_desired_testing(self, desired_testing):
        # TODO: trigger any engine_schema testing actions to perform the desired testing.
        self.desired_testing = desired_testing


@test_schema.define
class CommitTestDefinition:
    """TestSuites and Tests defined by a commit

    One such object exists per commit.
    """

    commit = Indexed(repo_schema.Commit)

    test_plan = OneOf(None, test_schema.TestPlan)  # None when pending generation
    test_suites = Dict(str, OneOf(None, test_schema.TestSuite))  # None when pending generation

    def set_test_plan(self, test_plan):
        """parse the YAML file produced by generated-test-plan
        (see docs/specs/Repo_Configuration_Spec.md)
        """
        assert isinstance(test_plan, test_schema.TestPlan), test_plan

        if self.test_plan is not None:
            raise RuntimeError(
                f"Cannot set_test_pan on commit {self.commit.hash} because it already has one"
            )

        test_plan_dict = yaml.safe_load(test_plan.plan)
        self.parse_test_plan(test_plan_dict)
        self.test_plan = test_plan

    def parse_test_plan(self, test_plan_dict: Dict(str, str)):
        """Act on the test plan. Read the environments, builds, and suites,
        and generate Tasks accordingly.
        """

        version = test_plan_dict["version"]
        assert version == 1, f"Unsupported test_plan version {version}"
        if "environments" in test_plan_dict:
            pass  # TODO
        if "builds" in test_plan_dict:
            pass  # TODO
        if "suites" in test_plan_dict:
            # suites: suite_name: kind
            suites = test_plan_dict["suites"]
            for suite_name, suite in suites.items():
                kind = suite["kind"]
                if kind != "unit":
                    raise NotImplementedError(f"Unsupported suite kind {kind}")
                environment = suite["environment"]
                # FIXME: this environment should match a previously defined env, but
                # this still needs building so we generate a fresh one.

                env = test_schema.Environment.lookupUnique(name=environment)
                if env is None:
                    env = test_schema.Environment(
                        name=environment,
                        variables={},
                        image=Image.DockerImage(
                            name="ubuntu:latest", with_docker=True, from_dockerfile=None
                        ),
                        min_ram_gb=0,
                        min_cores=0,
                        custom_setup="",
                    )
                dependencies = suite["dependencies"]
                list_tests = suite["list-tests"]
                run_tests = suite["run-tests"]
                timeout = suite["timeout"]
                engine_schema.TestSuiteGenerationTask(
                    commit=self.commit,
                    environment=env,
                    dependencies=dependencies,
                    name=suite_name,
                    status=Status(),
                    timeout=timeout,
                    list_tests_command=list_tests,
                    run_tests_command=run_tests,
                )


Image = Alternative(
    "Image",
    AwsAmi=dict(name=str),
    DockerImage=dict(name=str, with_docker=bool, from_dockerfile=OneOf(None, str)),
)


@test_schema.define
class Environment:
    """An environment where tests may run"""

    name = Indexed(str)
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
    tests = ConstDict(str, test_schema.Test)

    _hash = OneOf(None, int)

    @property
    def is_new(self):
        return True if self.parent is None else False

    def __hash__(self):
        if self._hash is None:
            self._hash = hash(tuple(hash(test) for test in self.tests.values()))
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

    @staticmethod
    def for_commit(name, commit):
        """Find the TestSuite that corresponds to a commit."""
        testing_config = test_schema.CommitDesiredTesting.lookupUnique(commit=commit)
        if testing_config is None:
            return None

        return testing_config.test_suites.get(name, None)


@test_schema.define
class TestSuiteParent:
    parent = Indexed(TestSuite)
    child = Indexed(TestSuite)

    parent_and_child = Index("parent", "child")

    commit_parent = repo_schema.CommitParent


class Unknown:
    pass


@test_schema.define
class Test:
    """Definition of a Test

    May belong to more than one TestSuite object (for different commits)
    Its name is unique within a TestSuite and also within a commit, but not
    necessarily across commits because the labels might be different.
    """

    name = Indexed(str)
    labels = TupleOf(str)  # sorted or frozenset
    name_and_labels = Index("name", "labels")  # unique
    path = str

    _hash = OneOf(None, int)

    def __hash__(self):
        if self._hash is None:
            self._hash = hash(tuple(self.name, tuple(hash(label) for label in self.labels)))
        return self._hash

    def get_parents(self):
        return test_schema.TestParent.lookupAll(child=self)

    @property
    def is_new(self) -> bool:
        return len(self.get_parents()) == 0

    @property
    def created_since(self, commit):
        existed = self.exists_in(commit)
        if existed is Unknown:
            return Unknown
        else:
            return not existed

    @property
    def exists_in(self, commit):
        """True if test exists in commit, False if it doesn't, and Unknown if we don't know."""
        testing_config = test_schema.CommitDesiredTesting.lookupUnique(commit=commit)
        if testing_config is None:
            return Unknown

        missing = False
        for name, suite in testing_config.test_suites.items():
            if suite is None:
                missing = True

            else:
                for name, test in suite.tests.items():
                    if self == test:
                        return True

        return Unknown if missing else False


@test_schema.define
class TestParent:
    parent = Indexed(Test)
    child = Indexed(Test)

    parent_and_child = Index("parent", "child")

    commit_parent = repo_schema.CommitParent


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
    start_time=float,  # epoch time
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

    def add_test_run_result(self, result):
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


def find_most_recent_test_results(test, commit, count=50, depth=1000):
    """Return a list of TestRunResult objects for a test starting from a given commit

    This will be used by our logic that tries to guess how long a test will take.

    We need to walk back the commit history starting from the given commit doing a
    breadth first search looking for TestResults objects and collecting their TestRunResult
    objects.

    There are many ways of doing this. For example we could only look at TestResults that
    match Test exactly, and then priorize by commit proximity, including or excluding commits
    on other branches. Or we could take into account TestResults for a given test based on how
    recently they were ran.
    """
    raise NotImplementedError()
