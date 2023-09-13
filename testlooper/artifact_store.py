"""An interface to either local storage or s3, based on fsspec."""
import fsspec
import os

from testlooper.schema.engine_schema import ArtifactStoreConfig


class ArtifactStore:
    def __init__(self, filesystem: fsspec.AbstractFileSystem, path: str):
        """Stores and loads artifacts.

        Args:
            filesystem: an fsspec implementation.
            path: the root path to use when reading/writing.
        """
        self.fs = filesystem
        self.path = path

    @classmethod
    def from_config(cls, config: ArtifactStoreConfig) -> "ArtifactStore":
        if config.matches.LocalDisk:
            return ArtifactStore(filesystem=fsspec.filesystem("file"), paths=config.root_path)
        elif config.matches.S3:
            return ArtifactStore(
                storage_type=fsspec.filesystem("s3"), path=f"s3://{config.bucket}"
            )
        else:
            raise ValueError(f"Unsupported config type: {config}")

    def save(self, filename: str, data: bytes):
        full_path = os.path.join(self.path, filename)
        dir_path = self.fs._parent(full_path)
        self.fs.makedirs(dir_path, exist_ok=True)
        with self.fs.open(full_path, "wb") as f:
            f.write(data)

    def load(self, filename):
        with self.fs.open(self.path + "/" + filename, "rb") as f:
            return f.read()
