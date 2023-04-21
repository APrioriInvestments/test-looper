from typed_python import Alternative
from object_database import Schema, Indexed, Index

# schema for test-looper repository objects
repo_schema = Schema("test_looper_repo")

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
    Ssh=dict(url=str, privateKey=bytes),
    Http=dict(url=str),
    Local=dict(path=str),
    FromService=dict(repo_name=str, service=GitService),
)


@repo_schema.define
class Repo:
    name = Indexed(str)
    config = RepoConfig


@repo_schema.define
class Commit:
    hash = Indexed(str)
    repo = Indexed(Repo)
    repo_and_hash = Index("repo", "hash")

    commit_text = str
    author = str

    # allows us to ask which commits need us to parse their tests. One of our services
    # is a little state machine that will run through Commit objects that are not parsed
    test_plan_generated = Indexed(bool)

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


@repo_schema.define
class CommitParent:
    """Model the parent-child relationshp between two commits"""

    parent = Indexed(Commit)
    child = Indexed(Commit)

    parent_and_child = Index("parent", "child")


@repo_schema.define
class Branch:
    repo = Indexed(Repo)
    name = str

    repo_and_name = Index("repo", "name")
    top_commit = Commit
