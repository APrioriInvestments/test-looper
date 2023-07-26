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


def test_generate_test_suites(local_engine_agent, testlooper_db, generate_repo):
    """SOP"""
    pass


def test_generate_test_suites_bad_list_command(
    local_engine_agent, testlooper_db, generate_repo
):
    pass


def test_generate_test_suites_ensure_docker(local_engine_agent, testlooper_db, generate_repo):
    """We need the docker image to already exist prior to this task running."""
    pass


def test_generate_test_suites_no_double_generation(
    local_engine_agent, testlooper_db, generate_repo
):
    """If the commit test definition already exists, short circuit."""
    pass


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
    local_engine_service, testlooper_db, make_and_clear_repo
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
    local_engine_service, testlooper_db, make_and_clear_repo
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
    local_engine_service, testlooper_db, make_and_clear_repo
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
    local_engine_service, testlooper_db, make_and_clear_repo
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
