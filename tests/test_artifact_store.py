"""
test_artifact_store.py

NB we aren't testing s3 here as there's a moto/aiobotocore incompatibility.
parameterization is in hope this is resolved in future releases.
"""

import pytest
from testlooper.artifact_store import ArtifactStore
import tempfile

from fsspec.implementations.local import LocalFileSystem

local_test_dir = tempfile.mkdtemp()
s3_test_dir = "s3://will-testlooper-test"
local_artifact_store = ArtifactStore("local", local_test_dir)


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load(artifact_store):
    artifact_store.save("test.txt", b"Hello, World!")
    assert artifact_store.load("test.txt") == b"Hello, World!"


@pytest.mark.parametrize(
    "artifact_store, fs_type",
    [
        (local_artifact_store, LocalFileSystem),
    ],
)
def test_get_fs(artifact_store, fs_type):
    assert isinstance(artifact_store.get_fs(), fs_type)


def test_unsupported_storage_type():
    with pytest.raises(ValueError):
        ArtifactStore("unsupported", "path").get_fs()


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load_nonexistent_file(artifact_store):
    with pytest.raises(FileNotFoundError):
        artifact_store.load("nonexistent.txt")


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load_empty_file(artifact_store):
    artifact_store.save("empty.txt", b"")
    assert artifact_store.load("empty.txt") == b""


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load_large_file(artifact_store):
    large_data = b"A" * 1024 * 1024  # 1MB of data
    artifact_store.save("large.txt", large_data)
    assert artifact_store.load("large.txt") == large_data


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load_special_characters(artifact_store):
    special_data = b"!@#$%^&*()_+{}:\"<>?[];',./~`-="
    artifact_store.save("special.txt", special_data)
    assert artifact_store.load("special.txt") == special_data


@pytest.mark.parametrize("artifact_store", [local_artifact_store])
def test_save_and_load_unicode(artifact_store):
    unicode_data = "こんにちは世界".encode("utf-8")
    artifact_store.save("unicode.txt", unicode_data)
    assert artifact_store.load("unicode.txt") == unicode_data
