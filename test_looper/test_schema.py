from typed_python import Alternative, NamedTuple, Dict, TupleOf, OneOf
from object_database import Indexed, Index, SubscribeLazilyByDefault

from test_looper import test_looper_schema


# model a command that produces a specific output
from test_looper.repo_schema import Commit


Command = NamedTuple(
    # named docker image
    dockerImageName=str,
    environmentVariables=Dict(str, str),
    bashCommand=str,
    timeoutSeconds=float
)


# model a single entry in a test plan. The collection of these must form a DAG
# with 'Test'
TestNodeDefinition = Alternative(
    "TestNodeDefinition",
    # run arbitrary code to produce a set of binary outputs
    Build=dict(
        inputs=TupleOf(str), # the named inputs
        outputs=TupleOf(str), # list of named outputs
        minCpus=int,
        minRamGb=float,
        command=Command,
    ),
    # run arbitrary code to produce the text of a docker image
    # then build that docker image
    DockerImage=dict(
        inputs=TupleOf(str), # the named inputs
    ),
    # run arbitrary code to produce a list of tests, and then run them
    Test=dict(
        inputs=TupleOf(str),  # named inputs
        minCpus=int,
        minRamGb=float,
        listTests=Command,
        runTests=Command
    )
)


@test_looper_schema.define
class TestNode:
    commit = Indexed(Commit)
    name = str

    commitAndName = Index('commit', 'name')

    definition = TestNodeDefinition

    # None means we haven't run it yet
    # Fail means we couldn't do the build, list tests, or execute tests.
    # Timeout means we timed out doing the same.
    # Success means we were able to perform the action. It doesn't mean that
    # the individual tests within the suite succeeded.
    # For a build node, success will mean that the artifact store has all build objects
    # populated, and that the artifact store has logs available
    executionResultSummary = OneOf(None, "Fail", "Timeout", "Success")

    # if we're a test (not a build), then some summary stats
    testsDefined = OneOf(None, int)
    testsExecutedAtLeastOnce = OneOf(None, int)
    testsFailing = OneOf(None, int)
    testsNewlyFailing = OneOf(None, int)
    testsNewlyFixed = OneOf(None, int)

    # crude proxy for the state machine we'll need to decide what to build/run
    needsMoreWork = Indexed(bool)

    isAssigned = Indexed(bool)


@test_looper_schema.define
class Worker:
    workerId = Indexed(str)

    startTimestamp = int  # nanoseconds since epoch

    # used to check if this worker is still alive
    lastHeartbeatTimestamp = OneOf(None, int)  # nanoseconds since epoch

    # used to check if it's safe to shutdown this worker
    lastTestCompletedTimestamp = OneOf(None, int)  # nanoseconds since epoch

    # machines are assigned to test nodes
    # TODO maybe create a separate Assignment object because Worker belongs with the Service
    currentAssignment = Indexed(OneOf(None, TestNode))


TestResult = NamedTuple(
    testId=str, # guid we can use to pull relevant logs from the artifact store
    testName=str,
    success=bool,
    startTime=int,  # nanoseconds since epoch
    executionTime=int  # nanoseconds
)


@test_looper_schema.define
@SubscribeLazilyByDefault
class TestResults:
    node = Indexed(TestNode)
    results = Dict(str, TupleOf(TestResult))
