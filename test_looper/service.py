# The main service class that will run this TestLooper installation
from object_database.database_connection import DatabaseConnection

from test_looper.schema import test_looper_schema
from test_looper.service_schema import Config, ArtifactStorageConfig


class LooperService:
    """
    Defines the TestLooper service
    """

    def __init__(
        self,
        repo_url: str,
        temp_url: str,
        artifact_store: ArtifactStorageConfig,
    ):
        """
        Parameters
        ----------
        repo_url: str
            The root url where we're going to put cloned repos
        temp_url: str
            The root url for temporary data
        artifact_store: Artifactstorageconfig
            The storage for build and test artifacts
        """
        self.repo_url = repo_url
        self.temp_url = temp_url
        self.artifact_store = artifact_store

    @staticmethod
    def from_odb(conn: DatabaseConnection) -> "LooperService":
        """
        Construct a LooperService by connecting to an ODB
        instance at the given connectio

        Parameters
        ----------
        conn: DatabaseConnection
            The connection to odb
        """
        conn.subscribeToSchema(test_looper_schema)
        with conn.view():
            config: ArtifactStorageConfig = Config.lookupUnique()
            return LooperService(
                config.repo_url, config.temp_url, config.artifact_store
            )
