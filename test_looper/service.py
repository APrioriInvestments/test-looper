# The main service class that will run this TestLooper installation
import os
import click
from typing import Dict, Optional, Union
from urllib.parse import urlparse
import uuid

from object_database.database_connection import DatabaseConnection
from test_looper.tl_git import GIT
from test_looper.repo_schema import (
    Branch,
    Commit,
    CommitParent,
    Repository,
    RepoConfig,
    RepoClone,
)
from test_looper import test_looper_schema
from test_looper.service_schema import ArtifactStorageConfig, Config
from test_looper.utils import ServiceMixin, transaction, view


class LooperService(ServiceMixin):
    """
    Defines the TestLooper service
    """

    def __init__(
        self,
        db: DatabaseConnection,
        repo_url: str = None,
        temp_url: str = None,
        artifact_store: ArtifactStorageConfig = ArtifactStorageConfig,
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
        super(LooperService, self).__init__(db)
        self.repo_url = repo_url
        self.temp_url = temp_url
        self.artifact_store = artifact_store

    def start(self):
        # 1. Get all repos
        # 2. Clone all repos
        # 3. Scan all clones
        # 4. Delete all clones
        pass

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
                db, config.repo_url, config.temp_url, config.artifact_store
            )

    @transaction
    def add_repo(
        self,
        name: str,
        config: Union[str, RepoConfig],
        default_scheme="ssh",
        private_key=bytes,
    ) -> RepoConfig:
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
        repo = Repository.lookupAny(name=name)
        if repo:
            assert repo.config == config
        else:
            repo = Repository(name=name, config=config)
        return repo.config

    @view
    def get_repo_config(self, name: str) -> Optional[RepoConfig]:
        repo = Repository.lookupAny(name=name)
        if repo is not None:
            return repo.config

    @view
    def get_all_repos(self) -> Dict[str, RepoConfig]:
        return {repo.name: repo.config for repo in Repository.lookupAll()}

    def clone_repo(
        self, name: str, clone_name: str = None
    ) -> (str, RepoConfig):
        """
        Clone a registered repo with the given name to this service's
        repo storage. A RepoClone link will be added between the remote
        repo storage. A RepoClone link will be added between the remote
        and local clone

        Parameters
        ----------
        name: str
            The odb name of the repo to be cloned
        clone_name: str, default None
            The odb name of the clone. If not provided, then it will
            be <name>-clone-<uuid>

        Returns
        -------
        (clone_name, clone_config): (str, RepoConfig)
        """
        if clone_name is None:
            clone_name = f"{name}-clone-{str(uuid.uuid4())}"
        with self.db.view():
            clone_repo = Repository.lookupAny(name=clone_name)
            if clone_repo is not None:
                return clone_repo.name, clone_repo.config

        clone_path = os.path.join(self.repo_url, clone_name)
        to_clone = self.get_repo_config(name)
        if to_clone is None:
            raise KeyError(f"Repo {name} is not registered in odb")
        _create_clone(to_clone, clone_path)
        with self.db.transaction():
            clone_conf = RepoConfig.Local(path=clone_path)
            clone_repo = Repository(name=clone_name, config=clone_conf)
            orig_repo = Repository.lookupOne(name=name)
            RepoClone(remote=orig_repo, clone=clone_repo)
            return clone_name, clone_repo.config

    @view
    def get_remote(self, clone_name: str) -> (str, RepoConfig):
        """
        Get the remote repo that originated the local repo with the given
        clone_name
        """
        clone = Repository.lookupOne(name=clone_name)
        remote = RepoClone.lookupOne(clone=clone).remote
        return remote.name, remote.config

    @transaction
    def scan_repo(self, repo_name: str, branch: Optional[str]):
        """
        Scan the given repo / branch and add Branches/Commits etc to odb.

        Parameters
        ----------
        repo_name: str
            Name of the local odb repository to scan
        branch: str or list-like of str, default None
            If None then just the default branch is scanned.
            If it's a str then assume it's branch name
            If the string is '*' then scan all branches
        """
        repo = Repository.lookupOne(name=repo_name)
        if not isinstance(repo.config, RepoConfig.Local):
            repo = RepoClone.lookupOne(remote=repo).clone
        g = GIT()
        if branch is None:
            to_scan = [g.get_head(repo.config.path)]
        elif branch == "*":
            to_scan = g.list_branches(repo.config.path)
        elif isinstance(branch, str):
            to_scan = [g.get_branch(repo.config.path, branch)]
        elif isinstance(branch, (list, tuple)):
            to_scan = [g.get_branch(repo.config.path, b) for b in branch]
        else:
            raise NotImplementedError()
        for b in to_scan:
            parse_branch(repo, b)


def _create_clone(conf: RepoConfig, clone_path):
    if isinstance(conf, RepoConfig.Https):
        GIT().clone(conf.url, clone_path, all_branches=True)
    else:
        raise NotImplementedError("Only public https cloning supported")


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


def parse_branch(repo: Repository, branch: "git.Head") -> Branch:
    """
    Go through the designated branch and register everything as necessary
    in odb. This includes 1) the branch itself, 2) commits and parents
    and 3) commit parent relationship
    """
    top_commit = parse_commits(repo, branch.commit)
    odb_b = Branch.lookupAny(repoAndName=(repo, branch.name))
    if odb_b is None:
        Branch(
            repo=repo,
            name=branch.name,
            top_commit=top_commit,
            is_prioritized=False,
        )
    else:
        odb_b.top_commit = top_commit
    return odb_b


def parse_commits(repo: Repository, commit: "git.Commit") -> Commit:
    """
    Start from the commit sha given in `head` and keep traversing commit
    parents until all parents are already in odb or no more parents exist.

    Parameters
    ----------
    repo: RepoConfig.Local
        The local repo whose active branch we want to parse commits from
    head: str
        The commit SHA where we want to start from (usually tip of a branch)

    Returns
    -------
    c: Commit
        The top commit as an ODB object
    """
    top_commit = make_commit(repo, commit)
    to_process = [(top_commit, commit.parents)]
    while len(to_process) > 0:
        odb_c, parents = to_process.pop()
        for p in parents:
            odb_p = Commit.lookupAny(sha=p.hexsha)
            if odb_p is None:
                odb_p = make_commit(repo, p)
                if len(p.parents) > 0:
                    to_process.append((odb_p, p.parents))
            rel = CommitParent.lookupAny(parentAndChild=(odb_p, odb_c))
            if rel is None:
                CommitParent(parent=odb_p, child=odb_c)
    return top_commit


def make_commit(repo, c):
    return Commit(
        repo=repo,
        sha=c.hexsha,
        summary=c.summary,
        author_name=c.author.name,
        author_email=c.author.email,
        is_parsed=False,
    )


@click.command()
@click.option('-h', '--host', default='localhost')
@click.option('-p', '--port', default='8000')
@click.option('-t', '--token', default='TOKEN')
def main(host, port, token):
    odb = connect(host, port, token)
    service = LooperService(odb)
    service.add_repo(
        "test-looper", "https://github.com//aprioriinvestments/test-looper"
    )
    service.clone_repo("test-looper", "my-test-looper-clone")
    service.scan_repo("my-test-looper-clone", branch="*")


if __name__ == '__main__':
    from object_database import connect
    main()
