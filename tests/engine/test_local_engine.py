"""
test_local_engine.py

Tests the Reactors in LocalEngineService, to wit:

    - generate_test_configs
    - generate_commit_test_definitions
    - generate_test_plans
    - generate_test_suites
    - build_docker_images
    - run_tests TODO
    - generate_test_run_tasks TODO
"""
import time
import pytest

from object_database import Reactor

from testlooper.schema.schema import engine_schema, repo_schema, test_schema
from testlooper.schema.engine_schema import StatusEvent
from testlooper.schema.test_schema import DesiredTesting, Image, TestFilter
from ..utils import (  # noqa
    local_engine_agent,
    local_engine_service,
    testlooper_db,
    make_and_clear_repo,
    generate_repo,
    clear_tasks,
    config_no_dockerfile,
    config_bad_command,
    TEST_PLAN,
)

# ^ above generates two branches with 3 commits each (one shared):
#   {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}, TEST_PLAN

#
bad_test_plan_str = """
version: 1
this is incorrect yaml.
"""

MAX_RETRIES = 10


DEFAULT_DESIRED_TESTING = DesiredTesting(
    runs_desired=1,
    fail_runs_desired=0,
    flake_runs_desired=0,
    new_runs_desired=0,
    filter=TestFilter(labels="Any", path_prefixes="Any", suites="Any", regex=None),
)


def wait_for_task(
    testlooper_db,
    task,
    wait_statuses=(StatusEvent.CREATED, StatusEvent.STARTED),
    break_status=StatusEvent.COMPLETED,
):
    for _ in range(MAX_RETRIES):
        with testlooper_db.transaction():
            status = task.status[0]
        if status in wait_statuses:
            time.sleep(0.1)
        elif status == break_status:
            break
        else:
            raise ValueError(f"Task failed to complete properly, got status: {status}")


@pytest.fixture(scope="module")
def test_config_reactor(testlooper_db, local_engine_agent):
    reactor = Reactor(testlooper_db, local_engine_agent.generate_test_configs)
    with reactor.running() as r:
        yield r


@pytest.fixture(scope="module")
def test_plan_reactor(testlooper_db, local_engine_agent):
    reactor = Reactor(testlooper_db, local_engine_agent.generate_test_plans)
    with reactor.running() as r:
        yield r


@pytest.fixture(scope="module")
def test_suite_reactor(testlooper_db, local_engine_agent):
    reactor = Reactor(testlooper_db, local_engine_agent.generate_test_suites)
    with reactor.running() as r:
        yield r


@pytest.fixture(scope="module")
def test_run_reactor(testlooper_db, local_engine_agent):
    reactor = Reactor(testlooper_db, local_engine_agent.run_tests)
    with reactor.running() as r:
        yield r


@pytest.fixture(scope="module")
def test_run_generator_reactor(testlooper_db, local_engine_agent):
    reactor = Reactor(testlooper_db, local_engine_agent.generate_test_run_tasks)
    with reactor.running() as r:
        yield r


# ############### generate_test_plans #################
"""
TestPlanGenerationTask is made when TestConfig is made for a commit.
Inputs:
    - a TestPlanGenerationTask
        - contains: literaly just has a commit, plus the status

Assumes:
   - the commit has a proper test_config
  - the  Docker image exists already. (image_name is set)

Outputs:
    - a TestPlanGenerationResult
        - contains: a commit, a TestPlan, a task., the error
    - a CommitTestDefinitionGenerationTask
    - a TestPlan
"""


def test_generate_test_plan(
    local_engine_agent, testlooper_db, generate_repo, test_plan_reactor, clear_tasks
):
    """Given a commit with a test config already generated, successfully generate a
    test plan.

    NB: this needs the image specified in the config file to exist already.
    """
    feature_branch = generate_repo["feature"]  # get a commit hash
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        # need to have a config ready to go.
        config = repo_schema.TestConfig(config_str=config_no_dockerfile, repo=commit.repo)
        config.parse_config()
        config.image_name = config.image["docker"]["image"]
        commit.test_config = config

        plan_generation_task = engine_schema.TestPlanGenerationTask.create(commit=commit)

    wait_for_task(testlooper_db, plan_generation_task)

    with testlooper_db.view():
        assert plan_generation_task.status[0] == StatusEvent.COMPLETED
        result = engine_schema.TestPlanGenerationResult.lookupAny(task=plan_generation_task)
        assert result is not None
        assert result.data is not None


def test_generate_test_plan_bad_config(
    local_engine_agent, testlooper_db, generate_repo, test_plan_reactor, clear_tasks
):
    """If the config command is parseable/valid yaml but malformed, fail gracefully."""
    feature_branch = generate_repo["feature"]  # get a commit hash
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        # need to have a config ready to go.
        config = repo_schema.TestConfig(config_str=config_bad_command, repo=commit.repo)
        config.parse_config()
        config.image_name = config.image["docker"]["image"]
        commit.test_config = config

        plan_generation_task = engine_schema.TestPlanGenerationTask.create(commit=commit)

    wait_for_task(testlooper_db, plan_generation_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert plan_generation_task.status[0] == StatusEvent.FAILED
        result = engine_schema.TestPlanGenerationResult.lookupAny(task=plan_generation_task)
        assert result is not None
        assert result.data is None
        assert result.error


def test_generate_test_plan_no_docker(
    local_engine_agent, testlooper_db, generate_repo, test_plan_reactor, clear_tasks
):
    """If the docker image we need isn't built yet, then fail gracefully (the scheduler is
    responsible for avoiding this)."""
    feature_branch = generate_repo["feature"]  # get a commit hash
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        # need to have a config ready to go.
        config = repo_schema.TestConfig(config_str=config_no_dockerfile, repo=commit.repo)
        config.parse_config()
        config.image_name = "bad_image:latest"
        commit.test_config = config

        plan_generation_task = engine_schema.TestPlanGenerationTask.create(commit=commit)

    wait_for_task(testlooper_db, plan_generation_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert plan_generation_task.status[0] == StatusEvent.FAILED
        result = engine_schema.TestPlanGenerationResult.lookupAny(task=plan_generation_task)
        assert result is not None
        assert result.data is None
        assert result.error


def test_generate_test_plan_no_config(
    local_engine_agent, testlooper_db, generate_repo, test_plan_reactor, clear_tasks
):
    """If the commit is missing a config, fail gracefully (as before, the scheduler is
    responsible for ensuring this doesn't happen)"""
    feature_branch = generate_repo["feature"]  # get a commit hash
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        # need to have a config ready to go.
        plan_generation_task = engine_schema.TestPlanGenerationTask.create(commit=commit)

    wait_for_task(testlooper_db, plan_generation_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert plan_generation_task.status[0] == StatusEvent.FAILED
        result = engine_schema.TestPlanGenerationResult.lookupAny(task=plan_generation_task)
        assert result is not None
        assert result.data is None
        assert result.error


def test_generate_test_plan_no_double_generation(
    local_engine_agent, testlooper_db, generate_repo, test_plan_reactor, clear_tasks
):
    """If the commit already has a test plan, short circuit."""

    feature_branch = generate_repo["feature"]  # get a commit hash
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        # need to have a config ready to go.
        config = repo_schema.TestConfig(config_str=config_no_dockerfile, repo=commit.repo)
        config.parse_config()
        config.image_name = config.image["docker"]["image"]
        commit.test_config = config
        plan_generation_task = engine_schema.TestPlanGenerationTask.create(commit=commit)

    wait_for_task(testlooper_db, plan_generation_task)

    # go again
    with testlooper_db.transaction():
        second_plan_generation_task = engine_schema.TestPlanGenerationTask.create(
            commit=commit
        )

    wait_for_task(testlooper_db, second_plan_generation_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert second_plan_generation_task.status[0] == StatusEvent.FAILED


# ############### generate_test_suites #################

"""
Test Suite GenerationTask is made by parse_test_plan in CommitTestDefinition, during
CommitTestDefinitionGenerationTask.

Input:
    - a Task with a Commit, an Environment, Dependencies (not used right now), name,
      list_tests_command, run_tests_command.

Process:
    - read the attrs
    - check the commit out
    - run the list_tests_command.
    - parse the output


Assumes;
- commit hash  exists in the repo
- env is well configured, env has an image name, and that image has already been built.

Output:
    - TestSuiteGenerationResult
      TestSuite
      suites in CommitTestDefinition
"""


def test_generate_test_suites(
    local_engine_agent, testlooper_db, generate_repo, test_suite_reactor, clear_tasks
):
    """SOP test
    TODO: assumes docker env built"""
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )
        list_tests = "python .testlooper/collect_pytest_tests.py"
        run_tests = "python .testlooper/run_pytest_tests.py"
        timeout = 60
        commit_test_definition = test_schema.CommitTestDefinition(
            commit=commit, test_plan=None, test_suites=None
        )
        task = engine_schema.TestSuiteGenerationTask.create(
            commit=commit,
            environment=env,
            name="test",
            timeout_seconds=timeout,
            list_tests_command=list_tests,
            run_tests_command=run_tests,
        )

    wait_for_task(testlooper_db, task)

    with testlooper_db.view():
        assert task.status[0] == StatusEvent.COMPLETED
        result = engine_schema.TestSuiteGenerationResult.lookupUnique(task=task)
        assert result is not None
        assert len(result.suite.tests) == 2
        assert len(commit_test_definition.test_suites) == 1


def test_generate_test_suites_bad_list_command(
    local_engine_agent, testlooper_db, generate_repo, test_suite_reactor, clear_tasks
):
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )
        list_tests = "python bad_command.py"
        run_tests = "python .testlooper/run_pytest_tests.py"
        timeout = 60
        _ = test_schema.CommitTestDefinition(commit=commit, test_plan=None, test_suites=None)
        task = engine_schema.TestSuiteGenerationTask.create(
            commit=commit,
            environment=env,
            name="test",
            timeout_seconds=timeout,
            list_tests_command=list_tests,
            run_tests_command=run_tests,
        )

    wait_for_task(testlooper_db, task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert task.status[0] == StatusEvent.FAILED


def test_generate_test_suites_ensure_docker(
    local_engine_agent, testlooper_db, test_suite_reactor, generate_repo, clear_tasks
):
    """We need the docker image to already exist prior to this task running.

    The task should block until it does."""
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper_needs_build:latest", with_docker=True),
        )
        list_tests = "python .testlooper/collect_pytest_tests.py"
        run_tests = "python .testlooper/run_pytest_tests.py"
        timeout = 60
        commit_test_definition = test_schema.CommitTestDefinition(
            commit=commit, test_plan=None, test_suites=None
        )
        task = engine_schema.TestSuiteGenerationTask.create(
            commit=commit,
            environment=env,
            name="test",
            timeout_seconds=timeout,
            list_tests_command=list_tests,
            run_tests_command=run_tests,
        )

    wait_for_task(testlooper_db, task)

    with testlooper_db.view():
        assert task.status[0] == StatusEvent.COMPLETED
        result = engine_schema.TestSuiteGenerationResult.lookupUnique(task=task)
        assert result is not None
        assert len(result.suite.tests) == 2
        assert len(commit_test_definition.test_suites) == 1


def test_generate_test_suites_no_double_generation(
    local_engine_agent, testlooper_db, test_suite_reactor, generate_repo, clear_tasks
):
    """If the commit test definition already has the suite, short circuit."""
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )
        list_tests = "python .testlooper/collect_pytest_tests.py"
        run_tests = "python .testlooper/run_pytest_tests.py"
        timeout = 60
        commit_test_definition = test_schema.CommitTestDefinition(
            commit=commit, test_plan=None, test_suites=None
        )
        task = engine_schema.TestSuiteGenerationTask.create(
            commit=commit,
            environment=env,
            name="test",
            timeout_seconds=timeout,
            list_tests_command=list_tests,
            run_tests_command=run_tests,
        )

    wait_for_task(testlooper_db, task)

    with testlooper_db.view():
        assert task.status[0] == StatusEvent.COMPLETED
        result = engine_schema.TestSuiteGenerationResult.lookupUnique(task=task)
        assert result is not None
        assert len(result.suite.tests) == 2
        assert len(commit_test_definition.test_suites) == 1

    # go again
    with testlooper_db.transaction():
        task = engine_schema.TestSuiteGenerationTask.create(
            commit=commit,
            environment=env,
            name="test",
            timeout_seconds=timeout,
            list_tests_command=list_tests,
            run_tests_command=run_tests,
        )

    wait_for_task(testlooper_db, task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert task.status[0] == StatusEvent.FAILED
        assert len(test_schema.TestSuite.lookupAll()) == 1


# ############### build_docker_images #################
"""
TODO immediately - we need to alter the dag to ensure that run tests, list tests, and the test
plan and suite generation tasks block
on the docker image build.

DockerBuildTask is made when?

TODO our docker builds are actually not interacting with Environment in the correct way."""


def test_blocked_tasks_start_after_docker_image_build():
    """Make some tasks, ensure they don't start until after the docker image is built."""
    pass


#  ############## generate_test_configs ###############
def test_generate_test_configs_need_dockerfile(
    local_engine_agent, test_config_reactor, testlooper_db, generate_repo, clear_tasks
):
    feature_branch = generate_repo["feature"]

    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/config_dockerfile.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )
        # this task is failing, path is bad

    wait_for_task(testlooper_db, test_config_task)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 1
        assert len(repo_schema.TestConfig.lookupAll()) == 1
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 1
        assert test_config_task.status[0] == StatusEvent.COMPLETED


def test_generate_test_configs_no_dockerfile(
    local_engine_agent, testlooper_db, generate_repo, clear_tasks
):
    feature_branch = generate_repo["feature"]

    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/config_no_dockerfile.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 1
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 1
        assert test_config_task.status[0] == StatusEvent.COMPLETED


def test_generate_test_configs_bad_path(
    local_engine_agent, testlooper_db, generate_repo, clear_tasks
):
    feature_branch = generate_repo["feature"]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/bad_path.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 0
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 0
        assert test_config_task.status[0] == StatusEvent.FAILED


def test_generate_test_configs_no_double_generation(
    local_engine_service, testlooper_db, generate_repo, clear_tasks
):
    """If we make a TestConfigTask with the same path and commit, we shouldn't run the
    process again."""

    feature_branch = generate_repo["feature"]
    # process the first
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/config_no_dockerfile.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 1
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 1
        assert test_config_task.status[0] == StatusEvent.COMPLETED

    # process the second
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/config_no_dockerfile.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 1
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 1
        assert test_config_task.status[0] == StatusEvent.FAILED


def test_generate_test_configs_bad_config(
    local_engine_service, testlooper_db, generate_repo, clear_tasks
):
    feature_branch = generate_repo["feature"]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=feature_branch[-1])
        config_path = ".testlooper/config_bad.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task, break_status=StatusEvent.FAILED)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 0
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 0
        assert test_config_task.status[0] == StatusEvent.FAILED


#  ############### generate_commit_test_definitions ################
def test_generate_commit_test_definitions(
    local_engine_service, testlooper_db, make_and_clear_repo, clear_tasks
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
        test_plan = test_schema.TestPlan(plan=TEST_PLAN, commit=commit)
        generate_ctd_task = engine_schema.CommitTestDefinitionGenerationTask.create(
            commit=commit, test_plan=test_plan
        )

    wait_for_task(testlooper_db, generate_ctd_task)

    with testlooper_db.view():
        assert len(test_schema.CommitTestDefinition.lookupAll(commit=commit)) == 1


def test_generate_commit_test_definitions_wrong_commit(
    local_engine_service, testlooper_db, make_and_clear_repo, clear_tasks
):
    with testlooper_db.transaction():
        commit_one = repo_schema.Commit.lookupUnique(hash="e")
        commit_two = repo_schema.Commit.lookupUnique(hash="c")
        test_plan = test_schema.TestPlan(plan=TEST_PLAN, commit=commit_one)
        generate_ctd_task = engine_schema.CommitTestDefinitionGenerationTask.create(
            commit=commit_two, test_plan=test_plan
        )

    wait_for_task(testlooper_db, generate_ctd_task, break_status=StatusEvent.FAILED)

    # might need a ping loop
    with testlooper_db.transaction():
        assert generate_ctd_task.status[0] == StatusEvent.FAILED
        assert not test_schema.CommitTestDefinition.lookupAll(commit=commit_one)
        assert not test_schema.CommitTestDefinition.lookupAll(commit=commit_two)


def test_generate_commit_test_definitions_malformed_test_plan(
    local_engine_service, testlooper_db, make_and_clear_repo, clear_tasks
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
        bad_test_plan = test_schema.TestPlan(plan=bad_test_plan_str, commit=commit)
        generate_ctd_task = engine_schema.CommitTestDefinitionGenerationTask.create(
            commit=commit, test_plan=bad_test_plan
        )
    wait_for_task(testlooper_db, generate_ctd_task, break_status=StatusEvent.FAILED)

    with testlooper_db.transaction():
        assert generate_ctd_task.status[0] == StatusEvent.FAILED


def test_generate_commit_test_definitions_double_generate(
    local_engine_service, testlooper_db, make_and_clear_repo, clear_tasks
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
        test_plan = test_schema.TestPlan(plan=TEST_PLAN, commit=commit)
        generate_ctd_task = engine_schema.CommitTestDefinitionGenerationTask.create(
            commit=commit, test_plan=test_plan
        )
    wait_for_task(testlooper_db, generate_ctd_task, break_status=StatusEvent.COMPLETED)

    # try to generate a second commit test definition, should fail

    with testlooper_db.transaction():
        generate_ctd_task_2 = engine_schema.CommitTestDefinitionGenerationTask.create(
            commit=commit, test_plan=test_plan
        )
    wait_for_task(testlooper_db, generate_ctd_task_2, break_status=StatusEvent.FAILED)

    with testlooper_db.transaction():
        assert generate_ctd_task_2.status[0] == StatusEvent.FAILED


# ############### generate_test_run_tasks ################
""" Trigger: a new or updated CommitDesiredTesting object
    Assumptions: We have a CommitDesiredTesting and a CommitTestDefinition object.
    The CommitTestDefinition has suites.

    Step 1: We get all the commit_test_definitions with altered testing. We bundle them
    into a list [commit, desired_testing, all_test_results]

    Step 2: Each desired testing filter gets parsed. Then the TestRunTask is created as
    appropriate.



    Inputs: The commitdesiredtestings
    Outputs: TestRunTasks.
"""


def test_generate_test_run_tasks(
    local_engine_agent, testlooper_db, generate_repo, test_run_generator_reactor, clear_tasks
):
    """Standard operation - set up the CommitTestDefinition, then make a new
    CommitDesiredTesting.

    Assert that we generate the right number of TestRunTasks.

    """
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        commit_test_definition = test_schema.CommitTestDefinition(
            commit=commit, test_plan=None, test_suites=None
        )
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )

        test_dict = {
            "test_1": test_schema.Test(name="test_1", labels=[], path="test_path"),
            "test_2": test_schema.Test(name="test_2", labels=[], path="test_path"),
        }
        test_suite = test_schema.TestSuite(
            name="test", environment=env, tests=test_dict, run_tests_command="test"
        )
        commit_test_definition.test_suites = {"test": test_suite}

        _ = test_schema.CommitDesiredTesting(
            commit=commit, desired_testing=DEFAULT_DESIRED_TESTING
        )
    max_retries = 5
    for _ in range(max_retries):
        with testlooper_db.view():
            if len(engine_schema.TestRunTask.lookupAll(commit=commit)) == 2:
                break
        time.sleep(0.1)
    else:
        assert False, "TestRunTasks not generated"

    with testlooper_db.view():
        test_run_tasks = engine_schema.TestRunTask.lookupAll(commit=commit)
        for task in test_run_tasks:
            assert task.runs_desired == 1


def test_generate_test_run_tasks_updated_testing(
    local_engine_agent, testlooper_db, generate_repo, test_run_generator_reactor, clear_tasks
):
    """Check that if we update the CommitDesiredTesting (here bumping the runs_desired) new
    TestRunTasks are generated."""

    # make the initial tasks
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        commit_test_definition = test_schema.CommitTestDefinition(
            commit=commit, test_plan=None, test_suites=None
        )
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )

        test_dict = {
            "test_1": test_schema.Test(name="test_1", labels=[], path="test_path"),
            "test_2": test_schema.Test(name="test_2", labels=[], path="test_path"),
        }
        test_suite = test_schema.TestSuite(
            name="test", environment=env, tests=test_dict, run_tests_command="test"
        )
        commit_test_definition.test_suites = {"test": test_suite}

        commit_desired_testing = test_schema.CommitDesiredTesting(
            commit=commit, desired_testing=DEFAULT_DESIRED_TESTING
        )
    max_retries = 5
    for _ in range(max_retries):
        with testlooper_db.view():
            if len(engine_schema.TestRunTask.lookupAll(commit=commit)) == 2:
                break
        time.sleep(0.1)
    else:
        assert False, "TestRunTasks not generated"

    with testlooper_db.view():
        test_run_tasks = engine_schema.TestRunTask.lookupAll(commit=commit)
        for task in test_run_tasks:
            assert task.runs_desired == 1

    # now update the desired testing

    with testlooper_db.transaction():
        commit_desired_testing.desired_testing = (
            commit_desired_testing.desired_testing.replacing(runs_desired=3)
        )

    for _ in range(max_retries):
        with testlooper_db.view():
            if len(engine_schema.TestRunTask.lookupAll(commit=commit)) == 4:
                break
        time.sleep(0.1)
    else:
        assert False, "TestRunTasks not generated"

    with testlooper_db.view():
        new_test_run_tasks = engine_schema.TestRunTask.lookupAll(commit=commit)
        for task in new_test_run_tasks:
            if task not in test_run_tasks:
                assert task.runs_desired == 2


# ############## run_tests ################
""" Trigger: New TestRunTasks

    Take a commit, and a batch of suites and tests to run. Checkout the commit, and run the
    suites' run_tests command in the provided container.
    We read the test output (specified via env vars) and parse it into a TestRunResult object.
    Make a TestResults object if required (shouldn't ever be required) and add the result to
    it. If any of the tests fail, then we fail the whole lot.
    Assumptions:
    Inputs: TestRunTasks
    Outputs: Updated TestResults, completed Tasks


TODO this too will need Docker builds.
"""


mock_run_test_command = """echo '{
  "created": 1691006618.8062782,
  "duration": 0.01,
  "exitcode": 0,
  "root": "/home/testlooper",
  "environment": {},
  "summary": {
    "passed": 2,
    "total": 2,
    "collected": 2
  },
  "collectors": [],
  "tests": [
    {
      "nodeid": "test_dummy1.py::test_1",
      "outcome": "passed",
      "lineno": 1,
      "setup": {
        "duration": 1.042643011896871,
        "outcome": "passed"
      },
      "call": {
        "duration": 0.02529199793934822,
        "outcome": "passed"
      },
      "teardown": {
        "duration": 0.05340163595974445,
        "outcome": "passed"
      },
      "keywords": []
    },
    {
      "nodeid": "test_dummy2.py::test_2",
      "outcome": "passed",
      "lineno": 1,
      "setup": {
        "duration": 1.042643011896871,
        "outcome": "passed"
      },
      "call": {
        "duration": 0.02529199793934822,
        "outcome": "passed"
      },
      "teardown": {
        "duration": 0.05340163595974445,
        "outcome": "passed"
      },
      "keywords": []
    }
  ]
}' > "$TEST_OUTPUT"
"""


def test_run_tests_single_commit(
    testlooper_db, local_engine_agent, generate_repo, test_run_reactor, clear_tasks
):
    # make the necessary test run tasks, ensure they get run.
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )

        test_dict = {
            "test_1": test_schema.Test(name="test_1", labels=[], path="test_path"),
            "test_2": test_schema.Test(name="test_2", labels=[], path="test_path"),
        }
        test_suite = test_schema.TestSuite(
            name="test",
            environment=env,
            tests=test_dict,
            run_tests_command=mock_run_test_command,
        )

        results = []
        for test in test_dict.values():
            test_result = test_schema.TestResults(
                test=test, commit=commit, suite=test_suite, runs_desired=0
            )
            results.append(test_result)

        tasks = []
        for result in results:
            task = engine_schema.TestRunTask.create(
                test_results=result, runs_desired=1, commit=commit, suite=test_suite
            )
            tasks.append(task)

    for task in tasks:
        wait_for_task(testlooper_db, task, break_status=StatusEvent.COMPLETED)

    with testlooper_db.view():
        for task in tasks:
            assert task.test_results.runs_completed == 1
            assert task.test_results.runs_passed == 1


def test_run_tests_needs_docker_build(
    testlooper_db, local_engine_agent, generate_repo, test_run_reactor, clear_tasks
):
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper_needs_build:latest", with_docker=True),
        )

        test_dict = {
            "test_1": test_schema.Test(name="test_1", labels=[], path="test_path"),
            "test_2": test_schema.Test(name="test_2", labels=[], path="test_path"),
        }
        test_suite = test_schema.TestSuite(
            name="test",
            environment=env,
            tests=test_dict,
            run_tests_command=mock_run_test_command,
        )

        results = []
        for test in test_dict.values():
            test_result = test_schema.TestResults(
                test=test, commit=commit, suite=test_suite, runs_desired=0
            )
            results.append(test_result)

        tasks = []
        for result in results:
            task = engine_schema.TestRunTask.create(
                test_results=result, runs_desired=1, commit=commit, suite=test_suite
            )
            tasks.append(task)

    for task in tasks:
        wait_for_task(testlooper_db, task, break_status=StatusEvent.COMPLETED)


def test_run_tests_pan_suite(
    testlooper_db, local_engine_agent, generate_repo, test_run_reactor, clear_tasks
):
    """When we get a run-all command (as happens when a  new commit is pushed), generate
    results for every individual test."""
    commit_hash = generate_repo["feature"][-1]
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash=commit_hash)
        env = test_schema.Environment(
            name="test",
            variables={},
            image=Image.DockerImage(name="testlooper:latest", with_docker=True),
        )

        test_dict = {
            "test_1": test_schema.Test(name="test_1", labels=[], path="test_path"),
            "test_2": test_schema.Test(name="test_2", labels=[], path="test_path"),
        }
        test_suite = test_schema.TestSuite(
            name="test",
            environment=env,
            tests=test_dict,
            run_tests_command=mock_run_test_command,
        )

        task = engine_schema.TestRunTask.create(
            test_results=None, runs_desired=1, commit=commit, suite=test_suite
        )

    wait_for_task(testlooper_db, task, break_status=StatusEvent.COMPLETED)

    with testlooper_db.view():
        results = test_schema.TestResults.lookupAll()
        assert len(results) == 2
        for result in results:
            assert result.runs_completed == 1
            assert result.runs_passed == 1
