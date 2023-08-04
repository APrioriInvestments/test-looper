import concurrent.futures
import docker
import json
import logging
import os
import subprocess
import tempfile
import time
import yaml
import uuid

from collections import defaultdict
from dataclasses import dataclass
from object_database.database_connection import DatabaseConnection
from typing import Dict, List, Optional


from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.test_schema import StageResult, TestRunResult
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.utils import setup_logger, parse_test_filter
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
        self.logger = setup_logger(__name__, level=logging.ERROR)
        self.threads = {}
        self.logger.info("Initialized LocalEngineAgent")
        self.db.subscribeToSchema(engine_schema, repo_schema, test_schema)

    def run_task(self, task_type, executor_func):
        """Run a task of the given type, using the given executor function."""
        with self.db.view():
            tasks = task_type.lookupAll()
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for task in tasks:
                try:
                    # this is completely wrong, as the thread runs outside the
                    # transaction
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

    def generate_test_configs(self):
        self.run_task(engine_schema.GenerateTestConfigTask, self.generate_test_config)

    def build_docker_images(self):
        self.run_task(engine_schema.BuildDockerImageTask, self.build_docker_image)

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
            test_plan_commit = test_plan.commit

        if not self._start_task(task, status, self.clock.time()):
            return

        if not test_plan_commit == commit:
            self.logger.error("Test plan commit must match task commit")
            with self.db.transaction():
                task.failed(self.clock.time())
            return

        if test_plan is None:
            self.logger.error(f"Task {task} has no test plan data")
            with self.db.transaction():
                task.failed(self.clock.time())
            return

        try:
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
        except Exception:
            with self.db.transaction():
                task.failed(self.clock.time())

    def generate_test_run_tasks(self):
        """Looks for new or updated CommitDesiredTestings, and works out what TestRunTasks
        to create.

        Applies the DesiredTesting filter to the commit and works out the tests affected.
        (this is also useful in the UI to show users what tests are about to run).

        Then generates TestResults for all touched tests, along with TestRunTasks,
        as appropriate.

        TODO horrible horrible
        """
        tasks_to_run = []
        with self.db.transaction():
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
                        # TODO only run this 'make all test results for the commit' once.
                        suites = commit_test_definition.test_suites.values()
                        all_test_results = set()
                        for suite in suites:
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

                        # TODO horrible horrible
                        tasks_to_run.append((commit, desired_testing, all_test_results))

        # so we make a list of commit + desired_testing + test results
        # then we use those test results and trim them down using our filter
        # then we compare the runs_desired to the number of runs already done.
        # then we make the Task.
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for commit, desired_testing, all_test_results in tasks_to_run:
                test_filter = desired_testing.filter

                future = executor.submit(
                    parse_test_filter, self.db, test_filter, all_test_results
                )
                try:
                    # contemplate using concurrent.futures.as_completed then a post-processor.
                    test_results_to_run = future.result()
                    if not test_results_to_run:
                        self.logger.error(f"Filter {test_filter} matched no tests")
                    else:
                        with self.db.transaction():
                            for test_result in test_results_to_run:
                                diff = desired_testing.runs_desired - test_result.runs_desired
                                if diff > 0:
                                    test_result.runs_desired = desired_testing.runs_desired
                                    _ = engine_schema.TestRunTask.create(
                                        test_results=test_result,
                                        runs_desired=diff,
                                        commit=commit,
                                        suite=test_result.suite,
                                    )
                                    self.logger.info(
                                        f"Created TestRunTask for test "
                                        f"{test_result.test.name} on commit {commit.hash}"
                                    )

                except Exception as e:
                    self.logger.error(f"Error generating test run tasks: {e}")

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
                        try:
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
                                assert parsed_test_results.exitcode in (
                                    0,
                                    1,
                                ), f"unexpected exit code {parsed_test_results.exitcode}"
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
                                            suite=suite,
                                        )

                                    results_obj.add_test_run_result(test_run_result)
                        except Exception as e:
                            self.logger.error(
                                f"Error running tests for commit {commit.hash}: {e}"
                            )
                            # get the affected TestResults.

                            # FIXME this likely requires a new error, it's not
                            # really a pytest error.
                            failure = TestRunResult(
                                uuid=str(uuid.uuid4()),
                                outcome="error",
                                duration_ms=0,
                                start_time=self.clock.time(),
                                stages={},
                            )
                            if run_all:
                                # error out the whole suite
                                for test in suite.tests.values():
                                    results_obj = test_schema.TestResults.lookupUnique(
                                        test_and_commit=(test, commit)
                                    )
                                    if not results_obj:
                                        results_obj = test_schema.TestResults(
                                            test=test, commit=commit, results=[], suite=suite
                                        )

                                    results_obj.add_test_run_result(failure)
                            else:
                                for test_node in test_name_and_task_list.keys():
                                    test_name = test_node.split("::")[-1]
                                    # error out the individual tests.
                                    results_obj = test_schema.TestResults.lookupUnique(
                                        test_and_commit=(suite.tests[test_name], commit)
                                    )
                                    if not results_obj:
                                        results_obj = test_schema.TestResults(
                                            test=suite.tests[test_name],
                                            commit=commit,
                                            results=[],
                                            suite=suite,
                                        )
                                    results_obj.add_test_run_result(failure)

                            for task in task_list:
                                task.failed(when=self.clock.time())
                        # ensure all tasks in the task list are marked completed.
                        for task in task_list:
                            try:
                                task.completed(when=self.clock.time())
                            except RuntimeError:
                                continue

    def generate_test_plan(self, task):
        """Check out the repo, and run the specified command from the config.

        TODO block on the docker build, if ongoing.
        """

        with self.db.view():
            status, timestamp = task.status
        if not self._start_task(task, status, self.clock.time()):
            return

        with self.db.view():
            commit = task.commit
            commit_hash = commit.hash
            command = commit.test_config.command
            env_vars = commit.test_config.variables
            image_name = commit.test_config.image_name
            test_plan = test_schema.TestPlan.lookupUnique(commit=commit)
            if test_plan is not None:
                raise ValueError(f"Test plan already exists for commit {commit_hash}")

        # Run test-plan generation in a Docker container.
        # Requires that docker has access to /tmp/
        # Binds the tmpdir to /repo/ in the container
        mount_dir = "/repo"
        test_plan_file = "test_plan.yaml"
        with tempfile.TemporaryDirectory() as tmpdir:
            # check out the necessary commit
            self.source_control_store.create_worktree_and_reset_to_commit(commit_hash, tmpdir)
            test_plan_output = os.path.join(mount_dir, test_plan_file)
            # get the image name from the config, which is either the image provided, or the
            # image given from the docker build
            env = os.environ.copy()
            env["TEST_PLAN_OUTPUT"] = test_plan_output
            env["REPO_ROOT"] = tmpdir
            if env_vars:
                for key, value in env_vars.items():
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
        """Generate some test suites. Triggered by parse_test_plan on CommitTestDefinition."""
        with self.db.view():
            status, timestamp = task.status

        if not self._start_task(task, status, self.clock.time()):
            return

        with self.db.view():
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
            ctd = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
            if ctd.test_suites and task.name in ctd.test_suites:
                raise ValueError(f"Test suite already exists for commit {commit_hash}")

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

        try:
            with self.db.transaction():
                task.completed(self.clock.time())
                _ = engine_schema.TestSuiteGenerationResult(
                    task=task, error="", commit=commit, suite=suite
                )
                # add the test suite to the commit test definition: could be a separate service
                # have to do the copy dance so that ODB notices the change.
                suites = dict(ctd.test_suites) if ctd.test_suites else {}
                suites[suite.name] = suite
                ctd.test_suites = suites

        except Exception as e:
            self.logger.exception("Failed to commit result to ODB.")
            self._test_suite_task_failed(task, f"Failed to commit result to ODB: {str(e)}")
            return

    def generate_test_config(self, task):
        """When a Commit comes in, we read the commit's config file, and make a new
        TestConfig object and parse if we need to. Generate
        BuildDockerImageTasks if needed."""
        with self.db.transaction():
            task.started(self.clock.time())
            commit = task.commit
            path = task.config_path
            commit_hash = commit.hash
            commit_config = commit.test_config

        # read the config file.
        try:
            if commit_config is not None:
                raise ValueError(
                    f"Commit {commit_hash} already has a config file: {commit_config}"
                )

            config_file_contents = self.source_control_store.get_file_contents(
                commit_hash, path
            )

            assert config_file_contents is not None

            with self.db.view():
                config = repo_schema.TestConfig.lookupUnique(config_str=config_file_contents)

            if config is None:
                with self.db.transaction():
                    config = repo_schema.TestConfig(
                        config_str=config_file_contents, repo=commit.repo
                    )
                    config.parse_config()
                    if docker_config := config.image.get("docker"):
                        if docker_config.get("dockerfile"):
                            _ = engine_schema.BuildDockerImageTask.create(
                                commit=commit,
                                environment_name="TODO",
                                dockerfile=docker_config["dockerfile"],
                                image=config.name,
                            )
                            config.image_name = (
                                config.name
                            )  # for now, if building new docker images, use the repo name
                        else:
                            config.image_name = docker_config["image"]
                    else:
                        raise ValueError("No docker image specified in config.")
        except Exception as e:
            self.logger.error(f"Failed to parse config file: {e}")
            with self.db.transaction():
                task.failed(self.clock.time())
            return

        with self.db.transaction():
            commit.test_config = config
            engine_schema.TestPlanGenerationTask.create(commit=commit)
            task.completed(self.clock.time())

    def build_docker_image(self, task):
        """Check if we've built an image like this already. If not, build it.

        First things first - build it every time.
        """
        with self.db.transaction():
            task.started(self.clock.time())

        with self.db.view():
            commit = task.commit
            commit_hash = commit.hash
            dockerfile = task.dockerfile
            image_name = task.image
            # what's the build context?
        with tempfile.TemporaryDirectory() as tmpdir:
            self.source_control_store.create_worktree_and_reset_to_commit(commit_hash, tmpdir)
            output = subprocess.run(
                ["docker", "build", "-t", image_name, "-f", dockerfile, tmpdir],
                capture_output=True,
            )  # TODO check=True
            if output.returncode != 0:
                print(output.stderr)
                print(output.stdout)
                raise RuntimeError(f"Failed to build docker image for task {task}")

        with self.db.transaction():
            task.completed(self.clock.time())

        # CHECKOUT THE COMMIT. RUN THE BUILD

        pass

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

    def _build_docker_image_task_failed(self, task, error):
        with self.db.transaction():
            engine_schema.BuildDockerImageResult(
                task=task,
                error=error,
                commit=task.commit,
                image="",
                environment_name="",
            )
            task.failed(self.clock.time())

    def _fail_task(self, task, error):
        if isinstance(task, engine_schema.TestPlanGenerationTask):
            self._test_plan_task_failed(task, error)
        elif isinstance(task, engine_schema.TestSuiteGenerationTask):
            self._test_suite_task_failed(task, error)
        elif isinstance(task, engine_schema.BuildDockerImageTask):
            self._build_docker_image_task_failed(task, error)

    def _config_missing_data(self, task, missing_values):
        missing = ".".join(missing_values)
        error = f"Test Configuration for commit {task.commit.hash} missing '{missing}'"
        logging.error(error)
        self._test_plan_task_failed(task, error)
