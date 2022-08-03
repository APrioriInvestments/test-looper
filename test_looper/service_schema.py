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
