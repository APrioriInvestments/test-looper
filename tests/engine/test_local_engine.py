"""
test_local_engine.py

Tests the Reactors in LocalEngineService, to wit:

    - generate_test_configs
    - build_docker_images
    - generate_test_plans
    - generate_test_suites
    - run_tests
    - x generate_commit_test_definitions x
    - generate_test_run_tasks
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
    TEST_PLAN,
)

# ^ above generates two branches with 3 commits each (one shared):
#   {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}, TEST_PLAN

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


#  ############## generate_test_configs ###############
def test_generate_test_configs_need_dockerfile(
    local_engine_agent, test_config_reactor, testlooper_db, make_and_clear_repo
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
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
    local_engine_agent, testlooper_db, make_and_clear_repo
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
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
    local_engine_agent, testlooper_db, make_and_clear_repo
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
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


def test_generate_test_configs_idempotent(
    local_engine_service, testlooper_db, make_and_clear_repo
):
    """If we make a TestConfigTask with the same path and commit, we shouldn't run the
    process again."""

    # process the first
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
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
        commit = repo_schema.Commit.lookupUnique(hash="e")
        config_path = ".testlooper/config_no_dockerfile.yaml"
        test_config_task = engine_schema.GenerateTestConfigTask.create(
            commit=commit, config_path=config_path
        )

    wait_for_task(testlooper_db, test_config_task)

    with testlooper_db.view():
        assert len(engine_schema.BuildDockerImageTask.lookupAll(commit=commit)) == 0
        assert len(repo_schema.TestConfig.lookupAll()) == 1
        assert len(engine_schema.TestPlanGenerationTask.lookupAll(commit=commit)) == 1
        assert test_config_task.status[0] == StatusEvent.FAILED


def test_generate_test_configs_bad_config(
    local_engine_service, testlooper_db, make_and_clear_repo
):
    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="e")
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
        test_plan = repo_schema.TestPlan(plan=TEST_PLAN, commit=commit_one)
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
