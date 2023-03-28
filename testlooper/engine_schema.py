from object_database import Schema
from .test_schema import test_schema

# schema for test-looper engine
engine_schema = Schema("test_looper_engine")


TaskStatus = str  # Figure out our state machine states here


class TestPlanGenerationTask:
    """Keep track of a task to generate a test plan."""

    commit_config = test_schema.CommitTestConfiguration
    status = TaskStatus


class TestSuiteGenerationTask:
    test_suite = test_schema.TestSuite
    status = TaskStatus


class TestRunTask:
    test_results = test_schema.TestResults
    status = TaskStatus
