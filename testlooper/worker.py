"""
worker.py

On spawn, tries repeatedly to connect to the dispatcher MessageBus, then waits
for work in the form of Tasks. When a Task is received, it does the work, messages back
with the status of the attempt, then asks for more.
"""

import docker
import json
import os
import subprocess
import tempfile
import time
import uuid
import yaml


import object_database.web.cells as cells
from dataclasses import dataclass
from object_database import ServiceBase, service_schema
from object_database.message_bus import MessageBus, MessageBusEvent
from object_database import RevisionConflictException
from typed_python import SerializationContext
from typing import Dict, Optional, List

from testlooper.artifact_store import ArtifactStore
from testlooper.dispatcher import Request, Response
from testlooper.schema.engine_schema import StatusEvent, TaskReference
from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.schema.test_schema import StageResult, TestRunResult
from testlooper.utils import (
    setup_logger,
    TEST_RUN_LOG_FORMAT_STDOUT,
    TEST_RUN_LOG_FORMAT_STDERR,
)
from testlooper.vcs import Git


@dataclass
class CommandOutput:
    out: bytes
    err: bytes


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


class WorkerService(ServiceBase):
    """Waits for work, and does it.

    Methods:
    - boot
    - configure the bus
    - receive a request to do some work. Do the work. (Single-threaded, assume one worker per
      core).
    - send a response back to the dispatcher saying if you did it or not.

    - Tells the dispatcher when it first successfully connects. Tells the dispatcher that it
      has received the work request and is on it (or that its busy and the dispatcher should
      begone).
    - Tells the dispatcher when it has finished the work request.
    - Responds to heartbeat check.
    - Responds to shutdown request.
    """

    def initialize(self):
        self.db.subscribeToSchema(engine_schema, repo_schema, test_schema)
        with self.db.view():
            config = (
                engine_schema.MessageBusConfig.lookupAny()
            )  # dodgy, assumes only one config object
            if config is None:
                raise RuntimeError(
                    "No message bus config found - did you run configure() on the dispatcher?"
                )
            self.hostname = config.hostname
            self.port = config.port
            self.path_to_git_repo = config.path_to_git_repo
            self._logger = setup_logger(__name__, level=config.log_level)
            self.id = self.runtimeConfig.serviceInstance.service._identity
            self.artifact_store_config = config.artifact_store_config
        self.connected = False
        self.retries = 0
        self.max_retries = 5
        self.busy = False
        self.endpoint = (self.hostname, self.port)
        self.bus = MessageBus(
            busIdentity="TLMessageBusWorker",
            endpoint=None,
            inMessageType=Request,
            outMessageType=Response,
            onEvent=self._onEvent,
            authToken="tl_auth_token",
            serializationContext=SerializationContext(),
            certPath=None,
            wantsSSL=True,
            sslContext=None,
            extraMessageSizeCheck=True,
        )
        self.bus.start()
        self.connection_id = self.bus.connect((self.hostname, self.port))
        self._logger.info("Worker Bus started")

        self.source_control_store = Git.get_instance(self.path_to_git_repo)
        self.artifact_store = ArtifactStore.from_config(self.artifact_store_config)

        self.task_handlers = {
            engine_schema.TestPlanGenerationTask: self._generate_test_plan,
            engine_schema.BuildDockerImageTask: self._build_docker_image,
            engine_schema.TestSuiteGenerationTask: self._generate_test_suite,
            engine_schema.TestSuiteRunTask: self._run_test_suite,
            engine_schema.CommitTestDefinitionGenerationTask: self._generate_commit_test_defn,
            engine_schema.GenerateTestConfigTask: self._generate_test_config,
        }

    @staticmethod
    def serviceDisplay(
        service_object, instance=None, objType=None, queryArgs=None
    ) -> cells.Cell:
        cells.ensureSubscribedSchema(service_schema)
        service = service_schema.Service.lookupUnique(name="WorkerService")
        # service = self.runtimeConfig.serviceInstance.service
        instances = service_schema.ServiceInstance.lookupAll(service=service)
        layout = cells.Text(
            "Worker Services:"
        )  # {service_schema.ServiceInstance.lookupAll(service=service)}")
        for instance in instances:
            layout += cells.Text(f"Instance: {instance._identity}")
        return layout

    def _onEvent(self, event: MessageBusEvent) -> None:
        if event.matches.OutgoingConnectionFailed:
            if self.retries < self.max_retries:
                self.retries += 1
                self._logger.warning("Worker failed to connect to dispatcher, retrying")
                time.sleep(0.1)
                self.connection_id = self.bus.connect((self.hostname, self.port))
            else:
                self._logger.error("Worker failed to connect to dispatcher, giving up")
                raise RuntimeError("Failed to connect to dispatcher")
        elif event.matches.OutgoingConnectionEstablished:
            self.connected = True
        elif event.matches.IncomingMessage:
            # assumes the only kind of messages we get are requests for work.
            if not self.busy:
                self.busy = True
                self._extract_payload(event.message)
            else:
                # TODO: send a response back saying we're busy.
                self.bus.sendMessage(
                    connectionId=self.connection_id,
                    message=Response.v1(
                        message=f"Worker {self.id} is busy", task_succeeded=False
                    ),
                )
        else:
            self._logger.error(f"Unexpected event: {event}")

    def _extract_payload(self, message: Request) -> None:
        """Check the protocol version and extract the payload from the message."""
        assert isinstance(message, Request), f"Expected a Request, got {type(message)}"
        if message.matches.v1:
            payload = message.payload
            self._handle_payload(payload)
        else:
            message_protocol = message.Name
            raise TypeError(
                f"Wrong protocol version - expected v1, received {message_protocol}"
            )

    def _handle_payload(self, payload: TaskReference):
        """Given a TaskReference, dereference it to get the Task object, and then based on
        what kind of Task it is, do the relevant work. Return a Success or Fail at the end.
        """
        with self.db.view():
            task = payload.dereference()

        if type(task) not in self.task_handlers:
            raise TypeError(f"Unknown task type {type(task)}")

        result = self.task_handlers[type(task)](task)

        if result:
            self.busy = False
            self.bus.sendMessage(
                connectionId=self.connection_id,
                message=Response.v1(
                    message=f"Worker {self.id} succeeded", task_succeeded=True
                ),
            )
        else:
            self.busy = False
            self.bus.sendMessage(
                connectionId=self.connection_id,
                message=Response.v1(message=f"Worker {self.id} failed", task_succeeded=False),
            )

    def _generate_test_plan(self, task) -> bool:
        """Read the test config for the specified commit, and generate a TestPlan.

        Currently assumes that the commit already has a TestConfig attribute. Generates
        CommitTestDefinitionGenerationTasks on completion.

        Args:
            task (engine_schema.TestPlanGenerationTask): The task to be executed.

        Returns:
            bool: True if the task succeeded, False otherwise.
        """

        if not self._start_task(task, time.time()):
            return False
        try:
            with self.db.view():
                commit = task.commit
                commit_hash = commit.hash
                command = commit.test_config.command
                env_vars = commit.test_config.variables
                image_name = (
                    commit.test_config.image_name
                )  # assumes that the image has been built already
                test_plan = test_schema.TestPlan.lookupUnique(commit=commit)
                if test_plan is not None:
                    raise ValueError(f"Test plan already exists for commit {commit_hash}")
                if image_name is None:
                    raise ValueError(f"Docker build task not completed for {commit_hash}")

            # Run test-plan generation in a Docker container.
            # Requires that docker has access to /tmp/
            # Binds the tmpdir to /repo/ in the container
            mount_dir = "/repo"
            test_plan_file = "test_plan.yaml"
            with tempfile.TemporaryDirectory() as tmpdir:
                # check out the necessary commit
                self.source_control_store.create_worktree_and_reset_to_commit(
                    commit_hash, tmpdir
                )
                test_plan_output = os.path.join(mount_dir, test_plan_file)
                # get the image name from the config, which is either the image provided, or
                # the image given from the docker build
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
                    f"{image_name}:{commit_hash}",
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
                    self._logger.info("container logs: %s", logs)
                container.remove(force=True)

                with open(os.path.join(tmpdir, test_plan_file), "r") as fd:
                    test_plan_str = fd.read()

                # Check that the yaml is parseable.
                yaml.safe_load(test_plan_str)

        except Exception as e:
            self._logger.error(f"Failed to generate test plan: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        with self.db.transaction():
            plan = test_schema.TestPlan(plan=test_plan_str, commit=commit)
            _ = engine_schema.TestPlanGenerationResult(
                task=task,
                error="",
                data=plan,
                commit=commit,
            )
            _ = engine_schema.CommitTestDefinitionGenerationTask.create(
                commit=commit, test_plan=plan
            )
            task.completed(time.time())
        return True

    def _build_docker_image(self, task) -> bool:
        """Currently the Tasks are generated as part of the TestConfig and
        TestSuite creation process.

        Args:
            task (engine_schema.BuildDockerImageTask): The task to be executed.
        Returns:
            bool: True if the task succeeded, False otherwise.
        """
        if not self._start_task(task, time.time()):
            return False

        with self.db.view():
            commit = task.commit
            commit_hash = commit.hash
            dockerfile = task.dockerfile
            image_name = task.image

        try:
            # Build the docker image
            with tempfile.TemporaryDirectory() as tmpdir:
                # check out the necessary commit
                self.source_control_store.create_worktree_and_reset_to_commit(
                    commit_hash, tmpdir
                )
                output = subprocess.run(
                    [
                        "docker",
                        "build",
                        "-t",
                        f"{image_name}:{commit_hash}",
                        "-f",
                        os.path.join(tmpdir, dockerfile),
                        tmpdir,
                    ],
                    capture_output=True,
                )
                if output.returncode != 0:
                    print(output.stderr)
                    print(output.stdout)
                    raise RuntimeError(f"Failed to build docker image for task {task}")

        except Exception as e:
            self._logger.error(f"Failed to build docker image: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        with self.db.transaction():
            task.completed(time.time())
        return True

    def _generate_test_suite(self, task) -> bool:
        """
        Generates a TestSuite object by running the provided list_tests command
        on the provided commit.

        Tasks are generated by parse_test_plan in CommitTestDefintion, during
        CommitTestDefinitionGenerationTask execution.

        Args:
            task (engine_schema.TestSuiteGenerationTask): The task to be executed.

        Returns:
            bool: True if the task succeeded, False otherwise.
        """
        if not self._start_task(task, time.time()):
            return False

        with self.db.view():
            commit = task.commit
            commit_hash = task.commit.hash
            env = task.environment
            # env_name = env.name
            env_image = env.image
            env_image_name = env_image.name
            env_commit_hash = env.commit_hash
            env_variables = env.variables
            # dependencies = task.dependencies
            list_tests_command = task.list_tests_command
            run_tests_command = task.run_tests_command
            ctd = test_schema.CommitTestDefinition.lookupUnique(commit=commit)

        try:
            with self.db.view():
                if ctd.test_suites and task.name in ctd.test_suites:
                    raise ValueError(f"Test suite already exists for commit {commit_hash}")

            output = None
            suite = None
            mount_dir = "/repo"
            with tempfile.TemporaryDirectory() as tmpdir:
                self.source_control_store.create_worktree_and_reset_to_commit(
                    commit_hash, tmpdir
                )
                env = os.environ.copy()
                env["REPO_ROOT"] = tmpdir
                if env_variables is not None:
                    for key, value in env_variables.items():
                        env[key] = value

                client = docker.from_env()
                volumes = {tmpdir: {"bind": mount_dir, "mode": "rw"}}
                container = client.containers.run(
                    f"{env_image_name}:{env_commit_hash}",
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
                # TODO handle better if this is an error.
                # current exception is 'str object has no attribute 'get'', which is naff.
                # parse the output into Tests.
                test_dict = self._parse_list_tests_yaml(output)
                with self.db.transaction():
                    suite = test_schema.TestSuite(
                        name=task.name,
                        environment=task.environment,
                        tests=test_dict,
                        run_tests_command=run_tests_command,
                    )  # TODO this needs a TestSuiteParent
                    self._logger.info(
                        f"Generated test suite {suite.name} with {len(test_dict)} tests."
                    )

            with self.db.transaction():
                _ = engine_schema.TestSuiteGenerationResult(
                    task=task, error="", commit=commit, suite=suite
                )
                # add the test suite to the commit test definition: could be a
                # separate service, but have to do the copy dance so that ODB notices the
                # change.
                suites = dict(ctd.test_suites) if ctd.test_suites else {}
                suites[suite.name] = suite
                ctd.test_suites = suites
                task.completed(time.time())

        except Exception as e:
            self._logger.error(f"Failed to generate test suite: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        return True

    def _run_test_suite(self, task) -> bool:
        """Executes the Tests specified by the TestRunTask.

        In the local_engine_agent, the TestRunTasks are generated when CommitDesiredTestings
        are altered or created. generate_test_run_tasks() is a Reactor that works out what
        TestRunTasks to create. Then run_tests() will trigger, and batch them per commit. Then
        checkout_and_run runs on
        each commit. This is the thing that the worker should actually receive.

        this is only a single run on a single commit
        """

        if not self._start_task(task, time.time()):
            return False

        with self.db.view():
            commit = task.commit
            commit_hash = commit.hash
            suite = task.suite
            suite_name = suite.name
            image_name = suite.environment.image.name
            command = suite.run_tests_command
            test_node_ids = (
                task.test_node_ids
            )  # either None, in which case we run all tests, or a list of test node ids

        try:
            with tempfile.TemporaryDirectory() as tmp_commit_dir:
                with tempfile.TemporaryDirectory() as tmp_test_dir:
                    # checkout the commit
                    self.source_control_store.create_worktree_and_reset_to_commit(
                        commit_hash, tmp_commit_dir
                    )
                    # prep the env vars
                    mount_dir = "/repo"
                    env_vars = {
                        "REPO_ROOT": mount_dir,
                        "TEST_OUTPUT": os.path.join("/tmp", "test_output.json"),
                        "TEST_INPUT": os.path.join("/tmp", "test_input.txt")
                        if test_node_ids
                        else "",
                    }
                    env = self._prep_env_vars(**env_vars)

                    # generate the test input file, if we need it.
                    if test_node_ids:
                        test_input_path = os.path.join(tmp_test_dir, "test_input.txt")
                        self._generate_test_input_file(
                            test_node_ids, path_to_input_file=test_input_path
                        )

                    # run the command in docker
                    output = self._run_docker_command(
                        f"{image_name}:{commit_hash}",
                        command,
                        volumes={
                            tmp_commit_dir: {"bind": mount_dir, "mode": "rw"},
                            tmp_test_dir: {"bind": "/tmp", "mode": "rw"},
                        },
                        env=env,
                        working_dir=mount_dir,
                    )
                    self.artifact_store.save(
                        TEST_RUN_LOG_FORMAT_STDOUT.format(suite_name, commit_hash), output.out
                    )
                    self.artifact_store.save(
                        TEST_RUN_LOG_FORMAT_STDERR.format(suite_name, commit_hash), output.err
                    )
                    # evaluate the results.
                    self._evaluate_test_results(
                        path_to_test_output=os.path.join(tmp_test_dir, "test_output.json"),
                        task=task,
                    )

        except Exception as e:
            # TODO error out the suites.

            self._logger.error(f"Failed to run test suite: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        with self.db.transaction():
            task.completed(time.time())
        return True

    def _prep_env_vars(self, **kwargs):
        env = os.environ.copy()
        for key, value in kwargs.items():
            env[key] = value
        return env

    def _generate_test_input_file(self, test_node_ids: List, path_to_input_file: str):
        with open(path_to_input_file, "w") as flines:
            flines.write("\n".join(test_node_ids))

    def _run_docker_command(
        self, image_name: str, command: str, volumes: Dict, env: Dict, working_dir: str
    ) -> CommandOutput:
        client = docker.from_env()
        container = client.containers.run(
            image_name,
            [command],
            volumes=volumes,
            environment=env,
            working_dir=working_dir,
            detach=True,
            stdout=True,
            stderr=True,
        )
        container.wait()

        out = container.logs(stdout=True, stderr=False)
        err = container.logs(stdout=False, stderr=True)

        container.remove(force=True)

        return CommandOutput(out=out, err=err)

    def _evaluate_test_results(self, path_to_test_output: str, task):
        """Parse the test_output, which should be a json file adhering to the TestRunOutput
        schema above. Update ODB accordingly.
        """
        with self.db.view():
            commit = task.commit
            suite = task.suite
            total_tests_in_suite = len(suite.tests)
            tests_run = task.test_node_ids

        with open(path_to_test_output) as flines:
            test_results = json.load(flines)

        parsed_test_results = TestRunOutput(**test_results)
        assert parsed_test_results.exitcode in (
            0,
            1,
        ), f"unexpected exit code {parsed_test_results.exitcode}"
        number_of_tests_run = parsed_test_results.summary["total"]

        if tests_run is None:
            assert number_of_tests_run == total_tests_in_suite, (
                f"expected {total_tests_in_suite} tests to run",
                f"got {number_of_tests_run}",
            )
        else:
            assert number_of_tests_run == len(tests_run), (
                f"expected {len(tests_run)} tests to" f" run, got {number_of_tests_run}"
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

            with self.db.transaction():
                results_obj = test_schema.TestResults.lookupUnique(
                    test_and_commit=(suite.tests[test_name], commit)
                )
                if not results_obj:
                    results_obj = test_schema.TestResults(
                        test=suite.tests[test_name], commit=commit, results=[], suite=suite
                    )

                results_obj.add_test_run_result(test_run_result)

    def _generate_commit_test_defn(self, task) -> bool:
        """Builds a CommitTestDefinition object and runs set_test_plan() on it.

        Generated by successful TestPlanGenerationTasks.

        Args:
            task (engine_schema.CommitTestDefinitionGenerationTask): The task to be executed.

        Returns:
            bool: True if the task succeeded, False otherwise.
        """
        if not self._start_task(task, time.time()):
            return False

        with self.db.view():
            commit = task.commit
            test_plan = task.test_plan
            test_plan_commit = test_plan.commit

        try:
            if not test_plan_commit == commit:
                raise ValueError("Test plan commit must match task commit")

            if test_plan is None:
                raise ValueError(f"Task {task} has no test plan data")

            with self.db.transaction():
                if not test_schema.CommitTestDefinition.lookupUnique(commit=commit):
                    commit_definition = test_schema.CommitTestDefinition(commit=commit)
                    self._logger.debug(
                        f"Created CommitTestDefinition for commit {commit.hash}"
                    )
                    commit_definition.set_test_plan(test_plan)
                    task.completed(time.time())
                else:
                    raise RuntimeError(
                        f"CommitTestDefinition already exists for commit {commit.hash}"
                    )
        except Exception as e:
            self._logger.error(f"Failed to generate CommitTestDefinition: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        return True

    def _generate_test_config(self, task) -> bool:
        """When the Git monitor service receives information about a new commit, this
        Task is created to read the commit's config file, and make a new
        TestConfig object and parse if we need to. Generates BuildDockerImageTasks if
        required, and cues TestPlanGenerationTasks on completion.

        NB - we make a DockerBuildTask for every commit here.

        Args:
            task (engine_schema.GenerateTestConfigTask): The task to be executed.

        Returns:
            bool: True if the task is completed, False otherwise.
        """
        if not self._start_task(task, time.time()):
            return False

        with self.db.view():
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

            with self.db.transaction():
                config = repo_schema.TestConfig.lookupUnique(config_str=config_file_contents)
                if config is None:
                    config = repo_schema.TestConfig(
                        config_str=config_file_contents, repo=commit.repo
                    )
                    config.parse_config()
                docker_task = self._create_docker_build_task(commit, config)

        except RevisionConflictException:
            self._logger.warning("Tried to parse config twice")
            with self.db.transaction():
                config = repo_schema.TestConfig.lookupUnique(config_str=config_file_contents)
                docker_task = self._create_docker_build_task(commit, config)

        except Exception as e:
            self._logger.error(f"Failed to parse config file: {e}")
            with self.db.transaction():
                task.failed(time.time())
            return False

        with self.db.transaction():
            commit.test_config = config
            engine_schema.TestPlanGenerationTask.create(
                commit=commit, dependencies=[docker_task] if docker_task else []
            )
            task.completed(time.time())
        return True

    def _create_docker_build_task(
        self, commit: repo_schema.Commit, config: repo_schema.TestConfig
    ):
        if docker_config := config.image.get("docker"):
            if docker_config.get("dockerfile"):
                config_name = f"{config.name}.config"
                docker_task = engine_schema.BuildDockerImageTask.create(
                    commit=commit,
                    dockerfile=docker_config["dockerfile"],
                    image=config_name,
                )
                config.image_name = config_name
                return docker_task
            else:
                config.image_name = docker_config["image"]
        else:
            raise ValueError("No docker image specified in config.")

    def _start_task(self, task, start_time) -> bool:
        with self.db.transaction():
            status = task.status[0]
            if status is not StatusEvent.CREATED:
                self._logger.error(f"Task {task} was already started, has status {status}")
                return False
            else:
                task.started(start_time)
        return True

    def _parse_list_tests_yaml(self, list_tests_yaml: str) -> Dict[str, test_schema.Test]:
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
        return parsed_dict
