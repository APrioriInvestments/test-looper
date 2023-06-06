import logging
import os
import tempfile
import threading
import subprocess
import time
import yaml

from object_database.database_connection import DatabaseConnection

from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
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
        self.logger = logging.getLogger(__name__)
        self.threads = {}
        self.logger.setLevel(logging.INFO)
        self.logger.info("Initialized LocalEngineAgent")

    def generate_test_plans(self):
        self.db.subscribeToSchema(engine_schema, repo_schema, test_schema)
        with self.db.view():
            tasks = engine_schema.TestPlanGenerationTask.lookupAll()
        for task in tasks:
            with self.db.transaction():
                if task.status[0] is StatusEvent.CREATED:
                    task.started(self.clock.time())
                    thread = threading.Thread(target=self.generate_test_plan, args=(task,))
                    thread.start()
                    thread.join()
                    self.threads[task] = thread

                elif task.status[-1] in (
                    StatusEvent.FAILED,
                    StatusEvent.TIMEDOUT,
                    StatusEvent.COMPLETED,
                ):
                    self.threads[task].join()
                    self.threads.pop(task)

    def generate_test_plan(self, task):
        """Parse the task config, check out the repo, and run the specified command."""
        now = self.clock.time()

        with self.db.view():
            status, timestamp = task.status
            commit = task.commit
            commit_hash = commit.hash
            test_config_str = commit.test_config.config

        # note the below is racey as the status is only changed at the end.
        if status is not StatusEvent.CREATED:
            self._task_failed(task, f"Unexpected Task status {status}")
            return

        else:
            with self.db.transaction():
                task.started(now)

        try:
            test_config = yaml.safe_load(test_config_str)
        except Exception as e:
            self.logger.exception("Failed to parse test configuration")
            self._task_failed(task, f"Failed to parse test configuration: {str(e)}")
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

        # Run test-plan generation
        # TODO dockerize
        with tempfile.TemporaryDirectory() as tmpdir:
            # check out the necessary commit
            self.source_control_store.create_worktree_and_reset_to_commit(commit_hash, tmpdir)
            test_plan_output = os.path.join(tmpdir, "test-plan.yaml")
            command = test_config["command"]
            env = os.environ.copy()
            env["TEST_PLAN_OUTPUT"] = test_plan_output
            env["REPO_ROOT"] = tmpdir
            if "variables" in test_config:
                for key, value in test_config["variables"].items():
                    env[key] = value
            subprocess.run(command, shell=True, cwd=tmpdir, env=env)

            with open(test_plan_output, "r") as fd:
                test_plan_str = fd.read()

            # Check that the yaml is parseable.
            try:
                yaml.safe_load(test_plan_str)
            except Exception as e:
                self.logger.exception("Failed to parse generated test-plan")
                self._task_failed(task, f"Failed to parse generated test-plan: {str(e)}")
                return

            with self.db.transaction():
                plan = test_schema.TestPlan(plan=test_plan_str, commit=commit)

                # racey - see above
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
                    self._task_failed(task, f"Failed to commit result to ODB: {str(e)}")

    def _task_failed(self, task, error):
        with self.db.transaction():
            engine_schema.TestPlanGenerationResult(
                task=task,
                error=error,
                commit=task.commit,
                data="",
            )
            task.failed(self.clock.time())

    def _config_missing_data(self, task, missing_values):
        missing = ".".join(missing_values)
        error = f"Test Configuration for commit {task.commit.hash} missing '{missing}'"
        logging.error(error)
        self._task_failed(task, error)
