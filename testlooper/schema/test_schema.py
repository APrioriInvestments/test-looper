import functools
import logging
from datetime import datetime

import object_database.web.cells as cells
import yaml
from object_database import Index, Indexed, SubscribeLazilyByDefault
from typed_python import Alternative, ConstDict, Dict, ListOf, NamedTuple, OneOf, TupleOf

from testlooper.artifact_store import ArtifactStore
from testlooper.utils import TEST_RUN_LOG_FORMAT_STDERR, TEST_RUN_LOG_FORMAT_STDOUT

from ..utils import (
    H1_FONTSIZE,
    H2_FONTSIZE,
    TL_SERVICE_NAME,
    add_menu_bar,
    get_tl_link,
    setup_logger,
    parse_test_filter_within_view,
)
from .schema_declarations import engine_schema, repo_schema, test_schema

logger = setup_logger(__name__, level=logging.INFO)

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
    regex=OneOf(None, str),
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
        self.desired_testing = desired_testing

    def display_cell(self):
        # This should, ideally, show you labels, suites, path_prefixes, regex that is
        # available to you.
        # Then generate a TestFilter, and show you the results of that filter.
        # Then a button that alters desired testing and pings the engine

        layout = cells.Padding(bottom=20) * cells.Text(
            f"Configuring Testing for Commit {self.commit.hash}", fontSize=H1_FONTSIZE
        )

        left_side = cells.Text(
            "\n".join(
                [
                    "Please submit any of:",
                    "a comma-separated list of labels (will prefix match),",
                    "a comma-separated list of path prefixes,",
                    "a comma-separated list of suite names (will exact match),",
                    "a regex for the test name.",
                    "Use Enter to submit, value, button below to show results of filter.",
                ]
            )
        )

        suites = cells.Slot("Any")
        labels = cells.Slot("Any")
        path_prefixes = cells.Slot("Any")
        regex = cells.Slot()
        tests = cells.Slot([])
        tests_shown = cells.Slot(False)
        tests_run = cells.Slot(False)

        def onEsc(text_box, slot):
            text_box.currentText.set(slot.get())

        def onEnter(slot, text):
            slot.set(text)

        for slot, name in [
            (labels, "Labels"),
            (path_prefixes, "Path Prefixes"),
            (suites, "Suites"),
            (regex, "Regex"),
        ]:
            # have to do this in a slightly strange way to avoid referencing the box
            # before assignment.
            box = cells.SingleLineTextBox("")
            box.onEsc = functools.partial(onEsc, text_box=box, slot=slot)
            box.onEnter = functools.partial(onEnter, slot)
            left_side += cells.Text(name + ":") >> box

        def generate_filter():
            kwargs = {}
            for slot_name, slot in [
                ("labels", labels),
                ("path_prefixes", path_prefixes),
                ("suites", suites),
            ]:
                arg = slot.get()
                if arg and arg != "Any":
                    arg = tuple(arg.split(","))
                kwargs[slot_name] = arg
            input_re = regex.get()
            kwargs["regex"] = input_re if input_re else None
            return TestFilter(**kwargs)

        def show_filter_results():
            """Show the results of the configured filter"""
            logger.info("Submitting filter to engine for dry-run")
            generated_filter = generate_filter()
            all_test_results = test_schema.TestResults.lookupAll(commit=self.commit)
            tests_to_run = parse_test_filter_within_view(generated_filter, all_test_results)
            tests.set(list(tests_to_run))
            tests_shown.set(True)
            if tests_run.get():
                tests_run.set(False)

        def run_tests():
            logger.error("RUNNING TESTS")
            for test_result in tests.get():
                engine_schema.TestRunTask.create(
                    test_results=test_result,
                    runs_desired=1,
                    commit=self.commit,
                    suite=test_result.suite,
                )
            tests_run.set(True)

        def show_run_button():
            if tests_shown.get():
                button = cells.Button("Run selected tests", run_tests)
                return button
            else:
                return None

        left_side += cells.Button("Show Filter Results", show_filter_results)
        left_side += cells.Subscribed(show_run_button)

        right_side = cells.Text("Current filter values: ", fontSize=H2_FONTSIZE)
        right_side += cells.Subscribed(lambda: cells.Text(labels.get()))
        right_side += cells.Subscribed(lambda: cells.Text(path_prefixes.get()))
        right_side += cells.Subscribed(lambda: cells.Text(suites.get()))
        right_side += cells.Subscribed(lambda: cells.Text(regex.get()))

        right_side += cells.Subscribed(
            lambda: cells.Text("Tests:\n" + "\n".join([x.test.name for x in tests.get()]))
        )
        layout += cells.ResizablePanel(cells.Card(left_side), cells.Card(right_side))

        layout += cells.Subscribed(
            lambda: cells.Button("Back to Commit", get_tl_link(self.commit))
            if tests_run.get()
            else None
        )

        # A split view with the text boxes on one side, and the slot values on the other.
        # For now that will suffice
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.commit.repo.name: get_tl_link(self.commit.repo),
                self.commit.hash: get_tl_link(self.commit),
            },
        )


@test_schema.define
class CommitTestDefinition:
    """TestSuites and Tests defined by a commit

    One such object exists per commit.
    """

    commit = Indexed(repo_schema.Commit)

    test_plan = OneOf(None, test_schema.TestPlan)  # None when pending generation
    test_suites = OneOf(
        None, ConstDict(str, test_schema.TestSuite)
    )  # None when pending generation

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
        dependent_tasks = []
        if "environments" in test_plan_dict:
            # build the Environment object and corresponding Docker image, if required.
            environments = test_plan_dict["environments"]
            for env_name, env_info in environments.items():
                env, docker_build_task = self.generate_environment(env_name, env_info)
                if docker_build_task:
                    dependent_tasks.append(docker_build_task)
        else:
            raise ValueError('No "environments" key in test_plan')

        if "builds" in test_plan_dict:
            logger.warning("Builds are not yet supported")
        if "suites" in test_plan_dict:
            suites = test_plan_dict["suites"]
            for suite_name, suite in suites.items():
                kind = suite["kind"]
                if kind != "unit":
                    raise NotImplementedError(f"Unsupported suite kind {kind}")
                environment = suite["environment"]
                env = test_schema.Environment.lookupUnique(
                    name_and_hash=(environment, self.commit.hash)
                )

                # FIXME temp: skip suites with linux-native as AWS is unsupported
                if env is None:
                    continue

                # TODO move these build deps somewhere else
                # build_dependencies = suite["dependencies"]
                list_tests = suite["list-tests"]
                run_tests = suite["run-tests"]
                timeout = suite["timeout"]
                engine_schema.TestSuiteGenerationTask.create(
                    commit=self.commit,
                    environment=env,
                    dependencies=dependent_tasks,
                    name=suite_name,
                    timeout_seconds=timeout,
                    list_tests_command=list_tests,
                    run_tests_command=run_tests,
                )

    def generate_environment(self, env_name, env_info):
        try:
            # process the image field
            env_image = None
            docker_build_task = None
            image = env_info["image"]
            if "docker" in image:
                docker_info = image["docker"]
                if "dockerfile" in docker_info:
                    dockerfile = docker_info["dockerfile"]
                    with_docker = (
                        bool(docker_info["with_docker"])
                        if "with_docker" in docker_info
                        else False
                    )
                    docker_build_task = engine_schema.BuildDockerImageTask.create(
                        dockerfile=dockerfile,
                        commit=self.commit,
                        image=env_name,
                    )
                    env_image = Image.DockerImage(name=env_name, with_docker=with_docker)
                elif "image" in docker_info:
                    env_image = Image.DockerImage(name=docker_info["image"])
            elif "aws-ami" in image:
                raise NotImplementedError("AWS AMI not yet supported")
            else:
                raise ValueError(f"Unknown image type {image}")

            variables = env_info["variables"] if "variables" in env_info else {}
            variables = {x: str(y) for x, y in variables.items()}
            min_ram_gb = float(env_info["min_ram_gb"]) if "min_ram_gb" in env_info else 0
            min_cores = int(env_info["min_cores"]) if "min_cores" in env_info else 0
            custom_setup = env_info["custom_setup"] if "custom_setup" in env_info else ""

        except KeyError as e:
            raise ValueError(f"Environment {env_name} is missing required key {e}")

        except NotImplementedError as e:
            logger.error(f"Environment {env_name} is not yet supported: {e}")
            return None, None

        assert (
            test_schema.Environment.lookupUnique(name_and_hash=(env_name, self.commit.hash))
            is None
        ), f"Environment {env_name} already exists for hash {self.commit.hash}"

        env = test_schema.Environment(
            name=env_name,
            commit_hash=self.commit.hash,
            variables=variables,
            image=env_image,
            min_ram_gb=min_ram_gb,
            min_cores=min_cores,
            custom_setup=custom_setup,
        )
        return env, docker_build_task


Image = Alternative(
    "Image",
    AwsAmi=dict(name=str),
    DockerImage=dict(name=str, with_docker=bool),
)


@test_schema.define
class Environment:
    """An environment where tests may run"""

    name = Indexed(str)
    commit_hash = Indexed(str)
    variables = ConstDict(str, str)  # Environment Variables
    image = Image
    min_ram_gb = float
    min_cores = int
    custom_setup = str  # additional bash commands to set up the environment
    name_and_hash = Index("name", "commit_hash")


@test_schema.define
class TestPlan:
    """Contents of YAML file produced by running generate-test-plan on a Commit."""

    plan = Indexed(str)
    commit = Indexed(repo_schema.Commit)

    def display_cell(self) -> cells.Cell:
        """Simply display the yaml text."""

        layout = cells.Padding(bottom=20) * cells.Text("Repo Test Plan", fontSize=H1_FONTSIZE)
        layout += cells.Scrollable(cells.Code(self.plan))
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.commit.repo.name: get_tl_link(self.commit.repo),
                self.commit.hash: get_tl_link(self.commit),
            },
        )


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
    run_tests_command = str
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

    def display_cell(self):
        layout = cells.Padding(bottom=20) * cells.Text(
            f"Test: {self.name}", fontSize=H1_FONTSIZE
        )
        layout += cells.Text("Labels: " + ", ".join(self.labels))
        layout += cells.Text("Path: " + self.path)

        def renderer_fun(row, col):
            # row is a TestResult. For all info, for now, use the most recent result.
            if col == "Status":
                if row.runs_pending:
                    text = "PENDING"
                else:
                    if row.runs_errored:
                        text = "ERROR"
                    elif row.runs_failed:
                        text = "FAILED"
                    else:
                        text = "PASSED"
                return cells.Clickable(text, get_tl_link(row))
            elif col == "Duration":
                return (
                    str(round(row.results[-1].duration_ms, 2)) + " ms" if row.results else ""
                )
            elif col == "Commit":
                return row.commit.hash

        table = cells.Table(
            colFun=lambda: ["Commit", "Status", "Duration"],
            rowFun=functools.partial(test_schema.TestResults.lookupAll, test=self),
            rendererFun=renderer_fun,
            headerFun=lambda x: x,
        )

        layout += table

        repo = test_schema.TestResults.lookupAny(test=self).commit.repo

        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                repo.name: get_tl_link(repo),
            },
        )

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
    suite = test_schema.TestSuite

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

    @property
    def artifact_store(self) -> ArtifactStore:
        """Return the artifact store by looking up the config."""
        config = engine_schema.MessageBusConfig.lookupUnique()
        return ArtifactStore.from_config(config.artifact_store_config)

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
        self.results += [result]  # append doesn't work here for ODB reasons
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
            self.runs_errored += 1
        elif outcome == "skipped":
            self.runs_skipped += 1
        else:
            # TODO: log an error
            pass

    def clear_results(self):
        """Delete all runs and zero the trackers."""
        self.results = []
        self.runs_desired = 0
        self.runs_completed = 0
        self.runs_passed = 0
        self.runs_xpassed = 0
        self.runs_failed = 0
        self.runs_xfailed = 0
        self.runs_errored = 0
        self.runs_skipped = 0

    def display_cell(self):
        layout = cells.Padding(bottom=20) * cells.Text(
            f"Results for {self.test.name} on commit {self.commit.hash}", fontSize=H1_FONTSIZE
        )

        layout += cells.Button("See all commits", get_tl_link(self.test))

        layout += cells.Text("Summary:", fontSize=H2_FONTSIZE)
        for attr_name, attr_val in [
            ("Runs Desired", self.runs_desired),
            ("Runs Completed", self.runs_completed),
            ("Runs Pending", self.runs_pending),
            ("Runs Passed", self.runs_passed),
            ("Runs XPassed", self.runs_xpassed),
            ("Runs Failed", self.runs_failed),
            ("Runs XFailed", self.runs_xfailed),
            ("Runs Errored", self.runs_errored),
            ("Runs Skipped", self.runs_skipped),
        ]:
            layout += cells.Text(attr_name + ": " + str(attr_val))

        layout += cells.Text("Individual Results:", fontSize=H2_FONTSIZE)
        for result in self.results:
            layout += cells.Text(f"UUID: {result.uuid}")
            layout += cells.Text(f"Outcome: {result.outcome}")
            layout += cells.Text(f"Duration: {result.duration_ms} ms")
            formatted_time = datetime.utcfromtimestamp(result.start_time).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            layout += cells.Text(f"Start Time: {formatted_time}")
            layout += cells.Text("")

            # log. Look up the config. Pull the results corresponding to that config.

        # FIXME this assumes only one run. Use the UUID instead.
        stdout = self.artifact_store.load(
            TEST_RUN_LOG_FORMAT_STDOUT.format(self.suite.name, self.commit.hash)
        ).decode("utf-8")
        stderr = self.artifact_store.load(
            TEST_RUN_LOG_FORMAT_STDERR.format(self.suite.name, self.commit.hash)
        ).decode("utf-8")

        layout += cells.Text("Run STDOUT", fontSize=H2_FONTSIZE)
        layout += cells.Text(stdout)

        layout += cells.Text("Run STDERR", fontSize=H2_FONTSIZE)
        layout += cells.Text(stderr)

        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.commit.repo.name: get_tl_link(self.commit.repo),
                self.commit.hash: get_tl_link(self.commit),
            },
        )


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
