"""An interface to either local storage or s3, based on fsspec."""
import fsspec
import os

from testlooper.schema.engine_schema import ArtifactStoreConfig


class ArtifactStore:
    def __init__(self, storage_type: str, path=".", region="us-east-1"):
        """Stores and loads artifacts.

        Args:
            storage_type: Either 'local' or 's3'
            # TODO chuck the filesystem in directly
            path (optional): The root directory for the storage. Defaults to '.'
            # region (optional): The region to use, if using s3. Seems like an antipattern to
            #     have it here.
        """
        self.storage_type = storage_type
        self.path = path
        # self.region = region

    @classmethod
    def from_config(cls, config: ArtifactStoreConfig) -> "ArtifactStore":
        if config.matches.LocalDisk:
            return ArtifactStore(storage_type="local", path=config.root_path)
        elif config.matches.S3:
            return ArtifactStore(storage_type="s3", path=f"s3://{config.bucket}")

    def get_fs(self):
        if self.storage_type == "local":
            return fsspec.filesystem("file")
        elif self.storage_type == "s3":
            return fsspec.filesystem("s3")
        else:
            raise ValueError(f"Unsupported storage type: {self.storage_type}")

    def save(self, filename: str, data: bytes):
        fs = self.get_fs()
        full_path = os.path.join(self.path, filename)
        dir_path = fs._parent(full_path)
        fs.makedirs(dir_path, exist_ok=True)
        with fs.open(full_path, "wb") as f:
            f.write(data)

    def load(self, filename):
        fs = self.get_fs()
        with fs.open(self.path + "/" + filename, "rb") as f:
            return f.read()
