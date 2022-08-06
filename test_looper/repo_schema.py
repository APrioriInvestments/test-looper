# Define the schema related to repos, branchs, and commits
from typed_python import Alternative, NamedTuple
from object_database import Indexed, Index


from test_looper import test_looper_schema


# describe generic services, which can provide lots of different repos
GitService = Alternative(
    "GitService",
    Github=dict(
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        owner=str,  # owner we use to specify which projects to look at
        access_token=str,
        auth_disabled=bool,
        github_url=str,  # usually https://github.com
        github_login_url=str,  # usually https://github.com
        github_api_url=str,  # usually https://github.com/api/v3
        github_clone_url=str,  # usually git@github.com
    ),
    Gitlab=dict(
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        group=str,  # group we use to specify which projects to show
        private_token=str,
        auth_disabled=bool,
        gitlab_url=str,  # usually https://gitlab.mycompany.com
        gitlab_login_url=str,  # usually https://gitlab.mycompany.com
        gitlab_api_url=str,  # usually https://gitlab.mycompany.com/api/v3
        gitlab_clone_url=str,  # usually git@gitlab.mycompany.com
    ),
)


# describe how to get access to a specific repo
RepoConfig = Alternative(
    "RepoConfig",
    Ssh=dict(url=str, private_key=bytes),
    Https=dict(url=str),
    Local=dict(path=str),  # TODO identify the host at this ID?
    S3=dict(url=str),
    FromService=dict(repo_name=str, service=GitService),
)


@test_looper_schema.define
class Repository:
    config = RepoConfig
    name = Indexed(str)


# TODO do we actually want to manage local clones in ODB?
@test_looper_schema.define
class RepoClone:
    remote = Indexed(Repository)
    clone = Indexed(Repository)
    # TODO add a machine id here since clones are local?


@test_looper_schema.define
class Commit:
    repo = Indexed(Repository)
    summary = str
    author_name = Indexed(str)
    author_email = str
    sha = Indexed(str)

    # allows us to ask which commits need us to parse their tests.
    is_parsed = Indexed(bool)

    @property
    def parents(self):
        """Return a list of parent commits"""
        return [c.parent for c in CommitParent.lookupAll(child=self)]

    @property
    def children(self):
        return [c.child for c in CommitParent.lookupAll(parent=self)]

    def setParents(self, parents):
        """Utility function to manage CommitParent objects"""
        curParents = self.parents
        for p in curParents:
            if p not in parents:
                CommitParent.lookupOne(parentAndChild=(p, self)).delete()

        for p in parents:
            if p not in curParents:
                CommitParent(parent=p, child=self)


@test_looper_schema.define
class CommitParent:
    """Model the parent-child relationshp between two commits"""

    parent = Indexed(Commit)
    child = Indexed(Commit)

    parentAndChild = Index("parent", "child")


@test_looper_schema.define
class Branch:
    repo = Indexed(Repository)
    name = str

    repoAndName = Index("repo", "name")
    top_commit = Commit

    # allows us to ask "what are the prioritized branches"
    is_prioritized = Indexed(bool)
