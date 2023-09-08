"""An interface to either local storage or s3, based on fsspec."""
import fsspec


class ArtifactStore:
    def __init__(self, storage_type: str, path: str):
        """Stores and loads artifacts.

        Args:
            storage_type: Either 'local' or 's3'
            path: The root directory for the storage.
        """
        self.storage_type = storage_type
        self.path = path

    def get_fs(self):
        if self.storage_type == "local":
            return fsspec.filesystem("file")
        elif self.storage_type == "s3":
            return fsspec.filesystem("s3")
        else:
            raise ValueError(f"Unsupported storage type: {self.storage_type}")

    def save(self, filename, data):
        fs = self.get_fs()
        with fs.open(self.path + "/" + filename, "w") as f:
            f.write(data)

    def load(self, filename):
        fs = self.get_fs()
        with fs.open(self.path + "/" + filename, "r") as f:
            return f.read()
