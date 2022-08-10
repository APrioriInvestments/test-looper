"""Define the core objects and ODB schema for test-looper."""
from typed_python import OneOf, Alternative, TupleOf, Dict, NamedTuple
from object_database import Indexed, Index, SubscribeLazilyByDefault


from test_looper import test_looper_schema


ArtifactStorageConfig = Alternative(
    "ArtifactStorageConfig",
    LocalDisk=dict(
        build_artifact_path=str,
        test_artifact_path=str,
    ),
    S3=dict(
        bucket=str,
        region=str,
        build_artifact_key_prefix=str,
        test_artifact_key_prefix=str,
    ),
    # TODO: something else fancy?
)


@test_looper_schema.define
class Config:
    """Configuration for the entire test-looper install"""

    repo_url = str  # local cloned repositories
    temp_url = str  # local temp data
    artifact_store = ArtifactStorageConfig


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

