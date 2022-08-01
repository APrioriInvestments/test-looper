import json
import os

from test_looper.git import GIT, Repo


class TestGit:

    GIT = None

    @classmethod
    def setup_class(cls):
        """
        Check is git credentials are present
        """
        cred_file = "./.git_credentials"
        if os.path.isfile(cred_file):
            print("GIT credentials found")
            credentials = json.load(open(cred_file))
            cls.GIT = GIT(user=credentials["user"], token=credentials["token"])
            cls.GIT.authenticate()
            if cls.GIT.authenticated:
                print("authenticated")
            else:
                print("Credentials invalid; continuing with lower rate limit")
        else:
            print("No credentials found; continuing")

    def test_success(self):
        assert 1 == 1

    def test_fail(self):
        assert 0 == 1

    @classmethod
    def teardown_class(cls):
        return


def test_list_commits(tmp_path):
    test_looper = "https://github.com/aprioriinvestments/test-looper"
    git = GIT()
    git.clone(test_looper, str(tmp_path))
    commits = list(git.list_commits(str(tmp_path)))
    assert len(commits) > 0
    for c in commits:
        for prop in [c.hexsha, c.author.name, c.author.email, c.summary]:
            assert prop is not None
            assert len(prop) > 0
