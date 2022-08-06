"""Define the core objects and ODB schema for test-looper."""
from typed_python import OneOf, Alternative, TupleOf, Dict, NamedTuple
from object_database import Schema, Indexed, Index, SubscribeLazilyByDefault


# primary schema for test-looper objects
test_looper_schema = Schema("test_looper")


# describe generic services, which can provide lots of different repos
GitService = Alternative(
    "GitService",
    Github=dict(
        account_name=str,  # for display
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        owner=str,  # owner we use to specify which projects to look at
        access_token=str,
        auth_disabled=bool,
        github_url=str,  # usually https://github.com
        github_login_url=str,  # usually https://github.com
        github_api_url=str,  # usually https://github.com/api/v3
        github_clone_url=str,  # usually git@github.com
    ),
    Gitlab=dict(
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        group=str,  # group we use to specify which projects to show
        private_token=str,
        auth_disabled=bool,
        gitlab_url=str,  # usually https://gitlab.mycompany.com
        gitlab_login_url=str,  # usually https://gitlab.mycompany.com
        gitlab_api_url=str,  # usually https://gitlab.mycompany.com/api/v3
        gitlab_clone_url=str,  # usually git@gitlab.mycompany.com
    )
)


# describe how to get access to a specific repo
RepoConfig = Alternative(
    "RepoConfig",
    Ssh=dict(url=str, privateKey=bytes),
    Http=dict(url=str),
    Local=dict(path=str),
    FromService=dict(
        repoName=str,
        service=GitService
    )
)


ArtifactStorageConfig = Alternative(
    "ArtifactStorageConfig",
    LocalDisk=dict(
        path_to_build_artifacts=str,
        path_to_test_artifacts=str,
    ),
    S3=dict(
        bucket=str,
        region=str,
        build_artifact_key_prefix=str,
        test_artifact_key_prefix=str
    ),
    # TODO: something else fancy?
)


# model a command that produces a specific output
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
        inputs=TupleOf(str), # named inputs
        minCpus=int,
        minRamGb=float,
        listTests=Command,
        runTests=Command
    )
)


TestResult = NamedTuple(
    # guid we can use to pull relevant logs from the artifact store
    testId=str,
    success=bool,
    startTime=float,
    executionTime=float
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
        windows_ami=str,  # default AMI to use when booting windows workers. Can be overridden for one-shot workers.
        path_to_keys=str,  # path to ssh keys to place on workers to access source control.
        instance_types=Dict(HardwareConfig, str),
        # dict from hardware configuration to instance types we're willing to boot
        host_ips=Dict(str, str),
        # dict from hostname to ip address to make available to workers
        # this is primarily useful when workers don't have access to dns
        # but we still want certs to all be valid
        max_cores=OneOf(None, int),  # cap on the number of cores we're willing to boot. None means no limit
        max_ram_gb=OneOf(None, int),  # cap on the number of gb of ram we're willing to boot. None means no limit
        max_workers=OneOf(None, int),  # cap on the number of workers we're willing to boot. None means no limit
    ),
    # run workers in-proc in the server
    Local=dict(
        local_storage_path=str,  # local disk storage we can use for workers
        docker_scope=str,  # local scope to augment dockers with
        max_cores=OneOf(None, int),  # cap on the number of cores we're willing to boot. means no limit
        max_ram_gb=OneOf(None, int),  # cap on the number of gb of ram we're willing to boot. means no limit
        max_workers=OneOf(None, int),  # cap on the number of workers we're willing to boot. means no limit
    ),
    # run workers in-proc in the server
    Dummy=dict(
        max_cores=OneOf(None, int),  # cap on the number of cores we're willing to boot. None means no limit
        max_ram_gb=OneOf(None, int),  # cap on the number of gb of ram we're willing to boot. None means no limit
        max_workers=OneOf(None, int),  # cap on the number of workers we're willing to boot. None means no limit
    )
)


@test_looper_schema.define
class Config:
    """Configuration for the entire test-looper install"""

    # where we are allowed to locally clone git repos
    pathToLocalGitStorage = str

    # how we can construct an artifact store
    artifactStorageConfig = ArtifactStorageConfig

    workerConfig = WorkerConfig


@test_looper_schema.define
class Repo:
    config = RepoConfig
    name = Indexed(str)


@test_looper_schema.define
class Commit:
    repo = Indexed(Repo)
    commitText = str
    author = str

    # allows us to ask which commits need us to parse their tests. One of our services
    # is a little state machine that will run through Commit objects that are not parsed
    hasTestsParsed = Indexed(bool)

    @property
    def parents(self):
        """Return a list of parent commits"""
        return [c.parent for c in CommitParent.lookupAll(child=self)]

    @property
    def children(self):
        return [c.child for c in CommitParent.lookupAll(parent=self)]

    def setParents(self, parents):
        """Utility function to manage CommitParent objects"""
        curParents = self.parents
        for p in curParents:
            if p not in parents:
                CommitParent.lookupOne(parentAndChild=(p, self)).delete()

        for p in parents:
            if p not in curParents:
                CommitParent(parent=p, child=self)


@test_looper_schema.define
class CommitParent:
    """Model the parent-child relationshp between two commits"""
    parent = Indexed(Commit)
    child = Indexed(Commit)

    parentAndChild = Index('parent', 'child')


@test_looper_schema.define
class Branch:
    repo = Indexed(Repo)
    name = str

    repoAndName = Index('repo', 'name')
    topCommit = Commit

    # allows us to ask "what are the prioritized branches"
    isPrioritized = Indexed(bool)


@test_looper_schema.define
class TestNode:
    # commit = Indexed(Commit)
    name = str

    # commitAndName = Index('commit', 'name')

    # definition = TestNodeDefinition

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
@SubscribeLazilyByDefault
class TestResults:
    node = Indexed(TestNode)

    testResults = Dict(str, TupleOf(TestResult))


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
