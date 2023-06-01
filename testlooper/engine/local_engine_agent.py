import logging
import os
import tempfile
import threading
import time
import yaml

from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.schema import engine_schema, repo_schema


class LocalEngineAgent:
    def __init__(self, db, source_control_store, artifact_store, clock=None):
        if clock is None:
            clock = time

        self.db = db
        self.source_control_store = source_control_store
        self.artifact_store = artifact_store
        self.clock = clock
        self.logger = logging.getLogger(__name__)
        self.threads = {}

    def generate_test_plans(self):
        self.db.subscribeToSchema(engine_schema, repo_schema)
        with self.db.view():
            tasks = engine_schema.TestPlanGenerationTask.lookupAll()

        for task in tasks:
            with self.db.transaction():
                if task.status[0] is StatusEvent.CREATED:
                    task.started(self.clock.time())

                    thread = threading.Thread(target=self.generate_test_plan, args=(task))
                    thread.start()
                    self.threads[task] = thread

    def generate_test_plan(self, task):
        # - parse the test_config
        # - checks out the repo at the given commit (probably use git-worktree)
        # - runs the generation task in a docker container.

        now = self.clock.time()

        with self.db.view():
            status, timestamp = task.status
            commit = task.commit
            commit_hash = commit.hash
            repo = commit.repo
            repo_config = repo.config
            test_config_str = commit.test_config

        if status is not StatusEvent.CREATED:
            self._task_failed(task, f"Unexpected Task status {status}")
            return

        else:
            with self.db.transaction():
                task.started(now)

        # Parse Yaml test-config
        try:
            test_config = yaml.safe_load(test_config_str)
        except Exception as e:
            self.logger.exception("Failed to parse test configuration")
            self._task_failed(task, f"Failed to parse test configuration: {str(e)}")
            return

        # Data-validation for test-config
        required_keys = ["version", "image", "generate-test-plan"]
        for key in required_keys:
            if key not in test_config:
                self._config_missing_data(task, [key])
                return

        if "docker" not in test_config["image"]:
            self._config_missing_data(task, ["image", "docker"])
            return

        # commit_path = self.source_control_store.get_worktree(repo_config, commit_hash)

        # Run test-plan generation
        with tempfile.TemporaryDirectory() as tmpdir:
            test_plan_output = os.path.join(tmpdir, "test-plan.yaml")

            # Now run the test plan generation in docker
            # - mount commit_path and set REPO_ROOT to point to it
            # - mount tmpdir and set TEST_PLAN_OUTPUT to test_plan_output
            # - set ENV_VARS from test_config["variables"] if any are present
            # - mount the docker daemon socket if needed

            # TODO
            pass

            with open(test_plan_output, "r") as fd:
                test_plan_str = fd.read()

            # Parse Yaml test-plan
            try:
                yaml.safe_load(test_plan_str)
            except Exception as e:
                self.logger.exception("Failed to parse generated test-plan")
                self._task_failed(task, f"Failed to parse generated test-plan: {str(e)}")
                return

            self.artifact_store.set_test_plan(repo_config, commit_hash, test_plan_str)

            with self.db.transaction():
                task.completed(self.clock.time())
                engine_schema.TestPlanGenerationResult(
                    task=task,
                    error="",
                    commit=task.commit,
                    data=test_plan_str,
                )

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

        self._task_failed(task, error, self.clock.time())
