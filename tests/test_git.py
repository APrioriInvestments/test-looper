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
