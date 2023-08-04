from typed_python import Alternative
from testlooper.schema.engine_schema import TaskReference

from testlooper.schema.schema import engine_schema

DISPATCHED_TASKS = [
    engine_schema.TestPlanGenerationTask,
    engine_schema.BuildDockerImageTask,
    engine_schema.TestSuiteGenerationTask,
    engine_schema.TestSuiteRunTask,
    engine_schema.CommitTestDefinitionGenerationTask,
    engine_schema.GenerateTestConfigTask,
]


Request = Alternative("Request", v1={"payload": TaskReference})
Response = Alternative("Response", v1=dict(message=str, task_succeeded=bool))


# doesn't pass the odb object.
# make an alternative with a lookup method that generates the object from a unique reference
# then give the task a define that generate the unique reference for the object.
