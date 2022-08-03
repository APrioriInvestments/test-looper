# The main service class that will run this TestLooper installation
import contextlib
from typing import Union, Dict
from urllib.parse import urlparse

from object_database.database_connection import DatabaseConnection
from test_looper.schema import test_looper_schema
from test_looper.service_schema import ArtifactStorageConfig, Config
from test_looper.repo_schema import Repository, RepoConfig


class LooperService:
    """
    Defines the TestLooper service
    """

    def __init__(
        self,
        repo_url: str,
        temp_url: str,
        artifact_store: ArtifactStorageConfig,
        db: DatabaseConnection,
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
        db: DatabaseConnection
            ODB connection
        """
        self.repo_url = repo_url
        self.temp_url = temp_url
        self.artifact_store = artifact_store
        self.db = db

    @staticmethod
    def from_odb(db: DatabaseConnection) -> "LooperService":
        """
        Construct a LooperService by connecting to an ODB
        instance at the given connectio

        Parameters
        ----------
        db: DatabaseConnection
            The connection to odb
        """
        db.subscribeToSchema(test_looper_schema)
        with db.view():
            config: Config = Config.lookupUnique()
            return LooperService(
                config.repo_url, config.temp_url, config.artifact_store, db
            )

    @contextlib.contextmanager
    def add_repo(
        self,
        name: str,
        config: Union[str, RepoConfig],
        default_scheme="ssh",
        private_key=bytes,
    ):
        """
        Parameters
        ----------
        name: str
            The name used to uniquely identify this repo in odb
        config: str or RepoConfig
            If str then parse it and create a RepoConfig
        default_scheme: str, default "ssh"
            If the config is str and no scheme was parsed.
            (by default this works for git@github.com:org/repo style url)
        private_key: bytes
            The SSH key

        yields
        -------
        Repository: inside the same db transaction that created it
        """
        if isinstance(config, str):
            config = parse_repo_url(config, default_scheme, private_key)
        with self.db.transaction():
            repo = Repository(name=name, config=config)
            yield repo

    def get_repo_config(self, name: str) -> RepoConfig:
        with self.db.view():
            repo = Repository.lookupOne(name=name)
            return repo.config

    def get_all_repos(self) -> Dict[str, RepoConfig]:
        with self.db.view():
            return {repo.name: repo.config for repo in Repository.lookupAll()}


def parse_repo_url(
    url: str, default_scheme: str = None, private_key: bytes = None
) -> RepoConfig:
    rs = urlparse(url)
    scheme = rs.scheme
    if not scheme:
        # make a reasonable effort to guess for common formats
        if url.startswith("git@github.com"):
            return RepoConfig.Ssh(url=url)
        if url.startswith("/"):
            return RepoConfig.Local(path=url)
        scheme = default_scheme

    if scheme == "https":
        return RepoConfig.Https(url=url)
    if scheme == "ssh":
        return RepoConfig.Ssh(url=url, private_key=private_key)
    if scheme == "file":
        path = rs.path if not rs.netloc else f"/{rs.netloc}{rs.path}"
        return RepoConfig.Local(path=path)
    if scheme == "s3":
        return RepoConfig.S3(url=url)
    raise NotImplementedError(f"No recognized scheme for {url}")
