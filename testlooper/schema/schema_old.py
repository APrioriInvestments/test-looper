"""Define the core objects and ODB schema for test-looper."""
from typed_python import OneOf, Alternative, TupleOf, Dict, NamedTuple
from object_database import Schema, Indexed, Index
from .repo_schema import Commit


# primary schema for test-looper objects
test_looper_schema = Schema("test_looper")


# model a command that produces a specific output
Command = NamedTuple(
    # named docker image
    dockerImageName=str,
    environmentVariables=Dict(str, str),
    bashCommand=str,
    timeoutSeconds=float,
)


# model a single entry in a test plan. The collection of these must form a DAG
# with 'Test'
TestNodeDefinition = Alternative(
    "TestNodeDefinition",
    # run arbitrary code to produce a set of binary outputs
    Build=dict(
        inputs=TupleOf(str),  # the named inputs
        outputs=TupleOf(str),  # list of named outputs
        minCpus=int,
        minRamGb=float,
        command=Command,
    ),
    # run arbitrary code to produce the text of a docker image
    # then build that docker image
    DockerImage=dict(
        inputs=TupleOf(str),  # the named inputs
    ),
    # run arbitrary code to produce a list of tests, and then run them
    Test=dict(
        inputs=TupleOf(str),  # named inputs
        minCpus=int,
        minRamGb=float,
        listTests=Command,
        runTests=Command,
    ),
)


HardwareConfig = NamedTuple(cpus=int, gbRam=float)

WorkerConfig = Alternative(
    "WorkerConfig",
    # boot workers in AWS
    Aws=dict(
        region=str,  # region to boot into
        vpc_id=str,  # id of vpc to boot into
        subnet=str,  # id of subnet to boot into
        security_group=str,  # id of security group to boot into
        keypair=str,  # security keypair name to use
        bootstrap_bucket=str,  # bucket to put windows bootstrap scripts into.
        bootstrap_key_prefix=str,  # key prefix for windows bootstrap scripts.
        windows_password=str,  # password to use for booted-up windows boxes
        worker_name=str,  # name of workers. This should be unique to this install.
        worker_iam_role_name=str,  # AIM role to boot workers into
        linux_ami=str,  # default linux AMI to use when booting linux workers
        windows_ami=str,  # default AMI to use when booting windows workers.
        # Can be overridden for one-shot workers.
        path_to_keys=str,  # path to ssh keys to place on workers to access source control.
        instance_types=Dict(HardwareConfig, str),
        # dict from hardware configuration to instance types we're willing to boot
        host_ips=Dict(str, str),
        # dict from hostname to ip address to make available to workers
        # this is primarily useful when workers don't have access to dns
        # but we still want certs to all be valid
        max_cores=OneOf(
            None, int
        ),  # cap on the number of cores we're willing to boot. None means no limit
        max_ram_gb=OneOf(
            None, int
        ),  # cap on the number of gb of ram we're willing to boot. None means no limit
        max_workers=OneOf(
            None, int
        ),  # cap on the number of workers we're willing to boot. None means no limit
    ),
    # run workers in-proc in the server
    Local=dict(
        local_storage_path=str,  # local disk storage we can use for workers
        docker_scope=str,  # local scope to augment dockers with
        max_cores=OneOf(
            None, int
        ),  # cap on the number of cores we're willing to boot. means no limit
        max_ram_gb=OneOf(
            None, int
        ),  # cap on the number of gb of ram we're willing to boot. means no limit
        max_workers=OneOf(
            None, int
        ),  # cap on the number of workers we're willing to boot. means no limit
    ),
    # run workers in-proc in the server
    Dummy=dict(
        max_cores=OneOf(
            None, int
        ),  # cap on the number of cores we're willing to boot. None means no limit
        max_ram_gb=OneOf(
            None, int
        ),  # cap on the number of gb of ram we're willing to boot. None means no limit
        max_workers=OneOf(
            None, int
        ),  # cap on the number of workers we're willing to boot. None means no limit
    ),
)


@test_looper_schema.define
class Config:
    """Configuration for the entire test-looper install"""

    # where we are allowed to locally clone git repos
    pathToLocalGitStorage = str

    # how we can construct an artifact store
    # artifactStorageConfig = ArtifactStorageConfig

    workerConfig = WorkerConfig


@test_looper_schema.define
class TestNode:
    commit = Indexed(Commit)
    name = str

    commitAndName = Index("commit", "name")

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


@test_looper_schema.define
class Machine:
    """Models a single "booted machine" that's online and capable of doing work for us."""

    machineId = int

    # machines have to heartbeat
    # periodically we clean up any machine that has not had a heartbeat
    lastHeartbeatTimestamp = float

    # machines that have not had a test in a while and that are idle can be shut down
    lastTestCompletedTimestamp = OneOf(None, float)

    # machines are assigned to test nodes
    currentAssignment = Indexed(OneOf(None, TestNode))
