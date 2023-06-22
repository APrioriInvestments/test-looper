import concurrent.futures
import docker
import logging
import os
import tempfile
import time
import yaml

from object_database.database_connection import DatabaseConnection

from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.vcs import Git
from testlooper.utils import setup_logger

from typing import Dict

# TODO
# db and thread exception handling
# thread management (final join)
# more comments
# more logging
# more tests
# more error propagation
# more docs
# less hardcoding


class LocalEngineAgent:
    """
    The LocalEngineAgent is responsible for executing new Tasks for testlooper, when
    the repo is stored locally on disk, and everything is run locally.

    Args:
        db: A connection to an in-memory runing ODB instance
        source_control_store: A Git object pointing to a local disk location.
        artifact_store: A connection to an artifact store (not yet implemented).
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
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for task in tasks:
                with self.db.transaction():
                    if task.status[0] is StatusEvent.CREATED:
                        task.started(self.clock.time())
                        future = executor.submit(executor_func, task)
                        try:
                            if task.timeout_seconds is None:
                                future.result()
                            else:
                                future.result(timeout=task.timeout_seconds)
                        except concurrent.futures.TimeoutError:
                            self.logger.error(f"Task {task} timed out")
                            task.timeout(when=self.clock.time())

    def generate_test_plans(self):
        self.run_task(engine_schema.TestPlanGenerationTask, self.generate_test_plan)

    def generate_test_suites(self):
        self.run_task(engine_schema.TestSuiteGenerationTask, self.generate_test_suite)

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
        test_plan_file = "test_plan2.yaml"
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
            volumes = {tmpdir: {"bind": "/repo", "mode": "rw"}}
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
            volumes = {tmpdir: {"bind": "/repo", "mode": "rw"}}
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

    def _config_missing_data(self, task, missing_values):
        missing = ".".join(missing_values)
        error = f"Test Configuration for commit {task.commit.hash} missing '{missing}'"
        logging.error(error)
        self._test_plan_task_failed(task, error)
