# The main service class that will run this TestLooper installation
from typing import Optional, Union
from urllib.parse import urlparse

from object_database.database_connection import DatabaseConnection

from test_looper import test_looper_schema
from test_looper.repo_schema import (
    Branch,
    Commit,
    CommitParent,
    Repository,
    RepoConfig,
)
from test_looper.service_schema import ArtifactStorageConfig, Config

from test_looper.tl_git import GIT
from test_looper.utils.db import ServiceMixin, transaction, view


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
        super(LooperService, self).__init__(db, repo_url)
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
        on_exist="ignore"
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
        on_exist: str, default "ignore"
            "ignore", "error", "overwrite" => what to do if the name already
            exists

        yields
        -------
        Repository: inside the same db transaction that created it
        """
        if isinstance(config, str):
            config = parse_repo_url(config, default_scheme, private_key)
        repo = Repository.lookupAny(name=name)
        if not repo:
            repo = Repository(name=name, config=config)
        else:
            if on_exist == "error":
                raise ValueError(f"Repo {name} is already registered")
            elif on_exist == "overwrite":
                repo.delete()
                repo = Repository(name=name, config=config)
        return repo.config

    @transaction
    def scan_repo(self, repo_name: str, branch: Optional[str]):
        """
        Scan the specified repo. If no branch is specified, only the
        default branch is scanned.
        """
        repo = Repository.lookupOne(name=repo_name)
        if repo is None:
            raise KeyError(f"Repository {repo_name} is not registered")
        is_found, clone_path = self.get_clone(repo)
        if not is_found:
            _create_clone(repo.config, clone_path)
        g = GIT()
        if branch is None:
            to_scan = [g.get_head(clone_path)]
        elif branch == "*":
            to_scan = g.list_branches(clone_path)
        elif isinstance(branch, str):
            to_scan = [g.get_branch(clone_path, branch)]
        elif isinstance(branch, (list, tuple)):
            to_scan = [g.get_branch(clone_path, b) for b in branch]
        else:
            raise NotImplementedError()
        for b in to_scan:
            parse_branch(repo, b)


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
    repo: Repository
        The (remote) repo we want associate commits with
    commit: git.Commit (GitPython)
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


def _create_clone(conf: RepoConfig, clone_path):
    if isinstance(conf, RepoConfig.Https):
        GIT().clone(conf.url, clone_path, all_branches=True)
    elif isinstance(conf, RepoConfig.Local):
        GIT().clone(conf.path, clone_path, all_branches=True)
    else:
        raise NotImplementedError("Only public https cloning supported")
