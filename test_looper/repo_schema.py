# Define the schema related to repos, branchs, and commits
from typed_python import Alternative
from object_database import Indexed


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
    Local=dict(path=str),
    S3=dict(url=str),
    FromService=dict(repo_name=str, service=GitService),
)


@test_looper_schema.define
class Repository:
    config = RepoConfig
    name = Indexed(str)


@test_looper_schema.define
class RepoClone:
    remote = Indexed(Repository)
    clone = Indexed(Repository)
