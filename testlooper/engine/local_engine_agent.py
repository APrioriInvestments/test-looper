import concurrent.futures
import docker
import json
import logging
import os
import re
import tempfile
import time
import yaml
import uuid

from collections import defaultdict
from dataclasses import dataclass
from object_database.database_connection import DatabaseConnection
from typing import Dict, List, Set, Optional


from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.test_schema import StageResult, TestRunResult, TestFilter
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.utils import setup_logger
from testlooper.vcs import Git

# TODO
# db and thread exception handling
# thread management (final join)
# more comments
# more logging
# more tests
# more error propagation
# more docs
# less hardcoding

MAX_WORKERS = 12


@dataclass
class Result:
    nodeid: str
    lineno: int
    keywords: List
    outcome: str
    setup: Dict
    call: Dict
    teardown: Dict
    metadata: Optional[Dict] = None


@dataclass
class TestRunOutput:
    created: float
    duration: float
    exitcode: int
    root: str
    environment: Dict
    summary: Dict  # number of outcomes per category, total number of tests
    collectors: List
    tests: List[Result]  # test nodes, with outcome and a set of test stages.
    warnings: Optional[List] = None


class LocalEngineAgent:
    """
    The LocalEngineAgent is responsible for executing new Tasks for testlooper, when
    the repo is stored locally on disk, and everything is run locally.

    Args:
        db: A connection to an in-memory runing ODB instance
        source_control_store: A Git object pointing to a local disk location.
        artifact_store: A connection to an artifact store (TODO not yet implemented).
        clock: A module implementing time().
    """

    def __init__(
        self, db: DatabaseConnection, source_control_store: Git, artifact_store, clock=None
    ):
        if clock is None:
            clock = time

        self.db = db
        self.source_control_store = source_control_store
        self.artifact_store = artifact_store
        self.clock = clock
        self.logger = setup_logger(__name__, level=logging.INFO)
        self.threads = {}
        self.logger.setLevel(logging.INFO)
        self.logger.info("Initialized LocalEngineAgent")
        self.db.subscribeToSchema(engine_schema, repo_schema, test_schema)

    def run_task(self, task_type, executor_func):
        """Run a task of the given type, using the given executor function."""
        with self.db.view():
            tasks = task_type.lookupAll()
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for task in tasks:
                try:
                    with self.db.transaction():
                        timeout_seconds = task.timeout_seconds
                        if task.status[0] is StatusEvent.CREATED:
                            future = executor.submit(executor_func, task)
                            if timeout_seconds is None:
                                future.result()
                            else:
                                future.result(timeout=timeout_seconds)
                except concurrent.futures.TimeoutError:
                    with self.db.transaction():
                        self.logger.error(f"Task {task} timed out")
                        task.timeout(when=self.clock.time())
                except Exception as e:
                    # catch-all for any remaining exceptions
                    self.logger.error(f"Task {task} failed: {e}")
                    self._fail_task(task, str(e))

    def generate_test_plans(self):
        self.run_task(engine_schema.TestPlanGenerationTask, self.generate_test_plan)

    def generate_test_suites(self):
        self.run_task(engine_schema.TestSuiteGenerationTask, self.generate_test_suite)

    def generate_commit_test_definitions(self):
        self.run_task(
            engine_schema.CommitTestDefinitionGenerationTask,
            self.generate_commit_test_definition,
        )

    def generate_commit_test_definition(self, task):
        """
        Triggered when a test plan object is successfully generated for a Commit.
        Creates a CommitTestDefinition and runs set_test_plan.
        TODO does this need a Result?
        """
        with self.db.view():
            status, timestamp = task.status
            commit = task.commit
            test_plan = task.test_plan

        if not self._start_task(task, status, self.clock.time()):
            return

        if test_plan is None:
            self.logger.error(f"Task {task} has no test plan data")
            with self.db.transaction():
                task.failed(self.clock.time())
            return

        with self.db.transaction():
            if not test_schema.CommitTestDefinition.lookupUnique(commit=commit):
                commit_definition = test_schema.CommitTestDefinition(commit=commit)
                self.logger.info(f"Created CommitTestDefinition for commit {commit.hash}")
                commit_definition.set_test_plan(test_plan)
                task.completed(self.clock.time())
            else:
                self.logger.error(
                    f"CommitTestDefinition already exists for commit {commit.hash}"
                )
                task.failed(self.clock.time())

    def generate_test_run_tasks(self):
        """Looks for new or updated CommitDesiredTestings, and works out what TestRunTasks
        to create.

        Applies the DesiredTesting filter to the commit and works out the tests affected.
        (this is also useful in the UI to show users what tests are about to run).

        Then generates TestResults for all touched tests, along with TestRunTasks,
        as appropriate.
        """
        tasks_to_run = []
        with self.db.view():
            # wait for a commit test defintion, both are needed
            # cdts = [cdt for cdt in test_schema.CommitDesiredTesting.lookupAll()]
            for commit_desired_testing in test_schema.CommitDesiredTesting.lookupAll():
                commit = commit_desired_testing.commit
                desired_testing = commit_desired_testing.desired_testing
                commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(
                    commit=commit
                )
                if commit_test_definition is not None:
                    # we only want to run this once all test suite tasks have completed
                    tasks = engine_schema.TestSuiteGenerationTask.lookupAll(commit=commit)
                    if all(
                        task.status[0]
                        in (StatusEvent.COMPLETED, StatusEvent.FAILED, StatusEvent.TIMEDOUT)
                        for task in tasks
                    ):
                        # work out what tests are affected.
                        suites = commit_test_definition.test_suites.values()
                        test_name_to_suite = {}
                        all_tests = set()
                        for suite in suites:
                            for test in suite.tests.values():
                                test_name_to_suite[test.name] = suite
                                all_tests.add(test)

                        # TODO horrible horrible
                        tasks_to_run.append(
                            (commit, desired_testing, test_name_to_suite, all_tests)
                        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for commit, desired_testing, test_name_to_suite, all_tests in tasks_to_run:
                test_filter = desired_testing.filter

                future = executor.submit(
                    self.parse_filter, test_filter, all_tests, test_name_to_suite
                )
                try:
                    # contemplate using concurrent.futures.as_completed then a post-processor.
                    tests_to_run = future.result()
                    if tests_to_run:
                        with self.db.transaction():
                            for test in tests_to_run:
                                test_result = test_schema.TestResults.lookupUnique(
                                    test_and_commit=(test, commit)
                                )
                                if test_result is None:
                                    test_result = test_schema.TestResults(
                                        test=test, commit=commit
                                    )
                                diff = desired_testing.runs_desired - test_result.runs_desired
                                if diff > 0:
                                    test_result.runs_desired = desired_testing.runs_desired
                                    _ = engine_schema.TestRunTask.create(
                                        test_results=test_result,
                                        runs_desired=diff,
                                        commit=commit,
                                        suite=test_name_to_suite[test.name],
                                    )
                                    self.logger.info(
                                        f"Created TestRunTask for test {test.name} "
                                        f"on commit {commit.hash}"
                                    )

                except Exception as e:
                    self.logger.error(f"Error generating test run tasks: {e}")

    def parse_filter(
        self,
        test_filter: TestFilter,
        all_tests: Set[test_schema.Test],
        test_name_to_suite: Dict[str, test_schema.TestSuite],
    ) -> Set[test_schema.Test]:
        """Filter is on labels, paths, suites, and regex on name."""
        filtered_tests = set()

        # this is used in a thread so somewhat bad practice, but all the function does is
        # lookups so can't be avoided
        # (and we don't need our reactor to re-trigger on any of these variables).
        with self.db.view():
            # Filter by labels
            if test_filter.labels == "Any" or test_filter.labels is None:
                filtered_tests = all_tests
            else:
                for test in all_tests:
                    for label in test_filter.labels:
                        if test.label.startswith(label):
                            filtered_tests.add(test)

            # Filter by path prefixes
            path_set = set()
            if test_filter.path_prefixes is not None and test_filter.path_prefixes != "Any":
                for test in filtered_tests:
                    for path_prefix in test_filter.path_prefixes:
                        if test.path.startswith(path_prefix):
                            path_set.add(test)
                filtered_tests &= path_set

            # Filter by suites
            suite_set = set()
            if test_filter.suites is not None and test_filter.suites != "Any":
                for test in filtered_tests:
                    for suite_name in test_filter.suites:
                        if test_name_to_suite[test.name].name == suite_name:
                            suite_set.add(test)
                filtered_tests &= suite_set

            # Filter by regex
            regex_set = set()
            if test_filter.regex is not None:
                for test in filtered_tests:
                    if re.match(test_filter.regex, test.name):
                        regex_set.add(test)

                filtered_tests &= regex_set

            if not filtered_tests:
                self.logger.error(f"Filter {test_filter} matched no tests")

        return filtered_tests

    def run_tests(self):
        """
        There will be a set (perhaps a large set) of TestRunTasks.
        Each one is a commit, a suite, and maybe a testresults.
        Batch them up in order to reduce the number of checkouts/test runs, then run.
        # NB this filter is going to get aggressive, over time.
        #   I hope lookupAll returns a generator.
        """
        with self.db.transaction():
            tasks = engine_schema.TestRunTask.lookupAll()
            test_batches = defaultdict(lambda: defaultdict(list))
            for task in tasks:
                if task.status[0] is StatusEvent.CREATED:
                    task.started(self.clock.time())  # debatable.
                    test_batches[task.commit][task.suite].append(task)

            max_timeouts = {
                commit: max(
                    task.timeout_seconds or 0
                    for suite in suites_dict.values()
                    for task in suite
                )
                for commit, suites_dict in test_batches.items()
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for commit, suites_dict in test_batches.items():
                timeout = max_timeouts[commit]
                future = executor.submit(self.checkout_and_run, commit, suites_dict)
                try:
                    if not timeout:
                        future.result()
                    else:
                        future.result(timeout=timeout)
                except json.JSONDecodeError as e:
                    self.logger.error(f"provided test runner produced invalid json: {e}")
                except Exception as e:
                    self.logger.error(f"Task failed: {e}")
                    # we can fail better here, don't need to error the whole suite.
                    with self.db.transaction():
                        for task_list in suites_dict.values():
                            for task in task_list:
                                task.failed(when=self.clock.time())

    def checkout_and_run(self, commit, suites_dict):
        """Checkout a commit, run all the suites in the suites dict.

        All error handling is done by the caller.
        NB: the TestRunTask is 'completed' even if the actual test fails - if the
        test is properly run and the output successfully parsed, that's a success from the
        Task's perspective.

        Args:
            commit: A commit object.
            suites_dict: A dict from Suite to a list of Tasks.


        Assumptions so far about the output of the test runner.

        1. It's a json file stored at TEST_OUTPUT
        2. It has the structure in TestRunOutput (this is too strict and will be relaxed
            later).


        TODO if we catch a failure, then we should mark the tasks as failed.
        TODO this code is horrible horrible
        """
        # NB with such a large transaction, an unexpected error will throw all in-flight runs
        # away.
        with self.db.transaction():
            self.logger.info(
                f"checking out {commit.hash} and running {len(suites_dict)} suites"
            )
            mount_dir = "/repo"
            test_output_path = "test_output.json"
            test_input_path = "test_input.txt"
            with tempfile.TemporaryDirectory() as tmpdir:
                # check out the necessary commit
                self.source_control_store.create_worktree_and_reset_to_commit(
                    commit.hash, tmpdir
                )

                # generate a list of test runs.
                for suite, task_list in suites_dict.items():
                    try:
                        with tempfile.TemporaryDirectory() as tmpdir2:
                            max_total_runs = max([task.runs_desired for task in task_list])
                            tests_to_run = [{} for _ in range(max_total_runs)]
                            run_all_tests = [False for _ in range(max_total_runs)]
                            for task in task_list:
                                for i in range(task.runs_desired):
                                    if run_all_tests[i]:
                                        continue
                                    if task.test_results is None:
                                        run_all_tests[i] = True
                                    else:
                                        node_id = (
                                            task.test_results.test.path
                                            + "::"
                                            + task.test_results.test.name
                                        )
                                        tests_to_run[i][node_id] = task

                            env = os.environ.copy()
                            env["REPO_ROOT"] = mount_dir
                            env["TEST_OUTPUT"] = os.path.join("/tmp", test_output_path)
                            # test_list is tuples of (test_name, task)
                            for run_all, test_name_and_task_list in zip(
                                run_all_tests, tests_to_run
                            ):
                                # now run the specified tests in the suite as many times
                                # as required.
                                if run_all:
                                    # run the run_tests_command without args
                                    env["TEST_INPUT"] = ""
                                else:
                                    repo_test_input_path = os.path.join(
                                        tmpdir2, test_input_path
                                    )
                                    with open(repo_test_input_path, "w") as flines:
                                        flines.write(
                                            "\n".join(
                                                [
                                                    name
                                                    for name in test_name_and_task_list.keys()
                                                ]
                                            )
                                        )
                                    env["TEST_INPUT"] = os.path.join("/tmp", test_input_path)

                                # the env now has a TEST_INPUT, a TEST_OUTPUT, and a REPO_ROOT,
                                # and we have a bash command that recognises these things.
                                command = suite.run_tests_command
                                image_name = suite.environment.image.name
                                client = docker.from_env()
                                volumes = {
                                    tmpdir: {"bind": mount_dir, "mode": "rw"},
                                    tmpdir2: {"bind": "/tmp", "mode": "rw"},
                                }
                                container = client.containers.run(
                                    image_name,
                                    [command],
                                    volumes=volumes,
                                    environment=env,
                                    working_dir=mount_dir,
                                    remove=False,
                                    detach=True,
                                )
                                container.wait()
                                # logs = container.logs().decode("utf-8")
                                container.remove(force=True)

                                with open(
                                    os.path.join(tmpdir2, test_output_path), "r"
                                ) as flines:
                                    test_results = json.load(flines)

                                parsed_test_results = TestRunOutput(**test_results)
                                assert parsed_test_results.exitcode == 0, "exit code was not 0"
                                number_of_tests_run = parsed_test_results.summary["total"]
                                if run_all:
                                    assert number_of_tests_run == len(suite.tests), (
                                        f"expected {len(suite.tests)} tests to run",
                                        f"got {number_of_tests_run}",
                                    )
                                else:
                                    assert number_of_tests_run == len(
                                        test_name_and_task_list
                                    ), (
                                        f"expected {len(test_name_and_task_list)} tests to"
                                        f" run, got {number_of_tests_run}"
                                    )
                                # match the result to the task and testresults object.
                                for result in parsed_test_results.tests:
                                    result = Result(**result)
                                    stages = {}
                                    total_duration = 0
                                    for stage_name in ["setup", "call", "teardown"]:
                                        stage = getattr(result, stage_name)
                                        stages[stage_name] = StageResult(
                                            duration=stage["duration"],
                                            outcome=stage["outcome"],
                                        )
                                        total_duration += stage["duration"]

                                    test_name = result.nodeid.split("::")[-1]
                                    test_run_result = TestRunResult(
                                        uuid=str(uuid.uuid4()),
                                        outcome=result.outcome,
                                        duration_ms=total_duration,
                                        start_time=parsed_test_results.created,
                                        stages=stages,
                                    )

                                    results_obj = test_schema.TestResults.lookupUnique(
                                        test_and_commit=(suite.tests[test_name], commit)
                                    )
                                    if not results_obj:
                                        results_obj = test_schema.TestResults(
                                            test=suite.tests[test_name],
                                            commit=commit,
                                            results=[],
                                        )

                                    results_obj.add_test_run_result(test_run_result)
                            # ensure all tasks in the task list are marked completed.
                            for task in task_list:
                                task.completed(when=self.clock.time())
                    except Exception as e:
                        # TODO error out the actual TestResults
                        for task in task_list:
                            task.failed(when=self.clock.time())
                        raise e

    def generate_test_plan(self, task):
        """Parse the task config, check out the repo, and run the specified command."""

        with self.db.view():
            status, timestamp = task.status
            commit = task.commit
            commit_hash = commit.hash
            test_config_str = commit.test_config.config

        if not self._start_task(task, status, self.clock.time()):
            return

        try:
            test_config = yaml.safe_load(test_config_str)
        except Exception as e:
            self.logger.exception("Failed to parse test configuration")
            self._test_plan_task_failed(task, f"Failed to parse test configuration: {str(e)}")
            return

        # Data-validation for test config
        required_keys = ["version", "image", "command"]
        for key in required_keys:
            if key not in test_config:
                self._config_missing_data(task, [key])
                return
        if "docker" not in test_config["image"]:
            self._config_missing_data(task, ["image", "docker"])
            return

        if "image" not in test_config["image"]["docker"]:
            self._test_plan_task_failed(
                task, "No docker image specified (dockerfiles are not yet supported)"
            )
            return

        # Run test-plan generation in a Docker container.
        # Requires that docker has access to /tmp/
        # Binds the tmpdir to /repo/ in the container
        mount_dir = "/repo"
        test_plan_file = "test_plan.yaml"
        with tempfile.TemporaryDirectory() as tmpdir:
            # check out the necessary commit
            self.source_control_store.create_worktree_and_reset_to_commit(commit_hash, tmpdir)
            test_plan_output = os.path.join(mount_dir, test_plan_file)
            command = test_config["command"]
            image_name = test_config["image"]["docker"]["image"]
            _ = test_config["image"]["docker"].get("with_docker", False)  # not currently used
            env = os.environ.copy()
            env["TEST_PLAN_OUTPUT"] = test_plan_output
            env["REPO_ROOT"] = tmpdir
            if "variables" in test_config:
                for key, value in test_config["variables"].items():
                    env[key] = value
            # initialise the docker client, bind the tmpdir to let docker access it, run.
            # this requires docker to have access to /tmp/
            client = docker.from_env()
            volumes = {tmpdir: {"bind": mount_dir, "mode": "rw"}}
            container = client.containers.run(
                image_name,
                # the below listbrackets turn out to be crucial for unknown reasons
                [command],
                volumes=volumes,
                environment=env,
                working_dir=mount_dir,
                remove=False,
                detach=True,
            )
            container.wait()
            logs = container.logs()
            if logs:
                self.logger.info("container logs: %s", logs)
            container.remove(force=True)

            with open(os.path.join(tmpdir, test_plan_file), "r") as fd:
                test_plan_str = fd.read()

            # Check that the yaml is parseable.
            try:
                yaml.safe_load(test_plan_str)
            except Exception as e:
                self.logger.exception("Failed to parse generated test-plan")
                self._test_plan_task_failed(
                    task, f"Failed to parse generated test-plan: {str(e)}"
                )
                return

            with self.db.transaction():
                plan = test_schema.TestPlan(plan=test_plan_str, commit=commit)

                task.completed(self.clock.time())
                try:
                    _ = engine_schema.TestPlanGenerationResult(
                        task=task,
                        error="",
                        data=plan,
                        commit=commit,
                    )
                    _ = engine_schema.CommitTestDefinitionGenerationTask.create(
                        commit=commit, test_plan=plan
                    )
                except Exception as e:
                    self.logger.exception("Failed to commit result to ODB.")
                    self._test_plan_task_failed(
                        task, f"Failed to commit result to ODB: {str(e)}"
                    )
                    return

    def generate_test_suite(self, task):
        """Generate some test suites."""
        with self.db.view():
            status, timestamp = task.status
            commit = task.commit
            commit_hash = task.commit.hash
            env = task.environment
            # env_name = env.name
            env_image = env.image
            env_image_name = env_image.name
            env_variables = env.variables
            # dependencies = task.dependencies
            list_tests_command = task.list_tests_command
            run_tests_command = task.run_tests_command

        if not self._start_task(task, status, self.clock.time()):
            return

        output = None
        suite = None
        mount_dir = "/repo"
        with tempfile.TemporaryDirectory() as tmpdir:
            self.source_control_store.create_worktree_and_reset_to_commit(commit_hash, tmpdir)
            env = os.environ.copy()
            env["REPO_ROOT"] = tmpdir
            if env_variables is not None:
                for key, value in env_variables.items():
                    env[key] = value

            client = docker.from_env()
            volumes = {tmpdir: {"bind": mount_dir, "mode": "rw"}}
            container = client.containers.run(
                env_image_name,
                [list_tests_command],
                environment=env,
                working_dir=mount_dir,
                volumes=volumes,
                remove=False,
                detach=True,
            )
            container.wait()
            output = container.logs().decode("utf-8")
            container.remove(force=True)

        if output is not None:
            # parse the output into Tests.
            try:
                test_dict = self.parse_list_tests_yaml(output, perf_test=False)
            except Exception:
                self.logger.error("Failed to parse generated test-suite for task %s", task)
                self._test_suite_task_failed(
                    task, f"Failed to parse generated test-suite from: {output}"
                )
                return
            with self.db.transaction():
                suite = test_schema.TestSuite(
                    name=task.name,
                    environment=task.environment,
                    tests=test_dict,
                    run_tests_command=run_tests_command,
                )  # TODO this needs a TestSuiteParent
                self.logger.info(
                    f"Generated test suite {suite.name} with {len(test_dict)} tests."
                )

        with self.db.transaction():
            try:
                task.completed(self.clock.time())
                _ = engine_schema.TestSuiteGenerationResult(
                    task=task, error="", commit=commit, suite=suite
                )
                # add the test suite to the commit test definition: could be a separate service
                ctd = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
                # have to do the copy dance so that ODB notices the change.
                suites = dict(ctd.test_suites) if ctd.test_suites else {}
                suites[suite.name] = suite
                ctd.test_suites = suites

            except Exception as e:
                self.logger.exception("Failed to commit result to ODB.")
                self._test_suite_task_failed(task, f"Failed to commit result to ODB: {str(e)}")
                return

    def _start_task(self, task, status, start_time) -> bool:
        if status is not StatusEvent.CREATED:
            if isinstance(task, engine_schema.TestPlanGenerationTask):
                self._test_plan_task_failed(task, f"Unexpected Task status {status}")
            elif isinstance(task, engine_schema.TestSuiteGenerationTask):
                self._test_plan_task_failed(task, f"Unexpected Task status {status}")
            return False

        else:
            with self.db.transaction():
                task.started(start_time)
        return True

    def parse_list_tests_yaml(
        self, list_tests_yaml: str, perf_test=False
    ) -> Dict[str, test_schema.Test]:
        """Parse the output of the list_tests command, and generate Tests if required."""
        yaml_dict = yaml.safe_load(list_tests_yaml)
        parsed_dict = {}
        with self.db.transaction():
            for test_name, test_dict in yaml_dict.items():
                test = test_schema.Test.lookupUnique(
                    name_and_labels=(test_name, test_dict.get("labels", []))
                )

                if test is None:
                    test = test_schema.Test(
                        name=test_name,
                        labels=test_dict.get("labels", []),
                        path=test_dict["path"],
                    )  # TODO this needs a Parent
                parsed_dict[test_name] = test
            if perf_test:
                # add 5000 fake tests to each suite to check ODB performance
                for i in range(5000):
                    parsed_dict[f"test_{i}"] = test_schema.Test(
                        name=f"test_{i}", labels=[], path="test.py"
                    )
        return parsed_dict

    def _test_suite_task_failed(self, task, error):
        with self.db.transaction():
            engine_schema.TestSuiteGenerationResult(
                task=task,
                error=error,
                commit=task.commit,
                suite=None,
            )
            task.failed(self.clock.time())

    def _test_plan_task_failed(self, task, error):
        with self.db.transaction():
            engine_schema.TestPlanGenerationResult(
                task=task,
                error=error,
                commit=task.commit,
                data=None,
            )
            task.failed(self.clock.time())

    def _fail_task(self, task, error):
        if isinstance(task, engine_schema.TestPlanGenerationTask):
            self._test_plan_task_failed(task, error)
        elif isinstance(task, engine_schema.TestSuiteGenerationTask):
            self._test_suite_task_failed(task, error)

    def _config_missing_data(self, task, missing_values):
        missing = ".".join(missing_values)
        error = f"Test Configuration for commit {task.commit.hash} missing '{missing}'"
        logging.error(error)
        self._test_plan_task_failed(task, error)
