import json
import os
import pathlib

import pytest

from test_looper.tl_git import GIT
from test_looper.tl_git import Repo as GitPythonRepo


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

    @pytest.mark.knownfailure
    def test_fail(self):
        assert 0 == 1

    def test_clone_repo(self, tmp_path: pathlib.Path):
        url = "https://github.com/aprioriinvestments/test-looper"
        clone_path = tmp_path / 'test-looper'
        GIT().clone(url, str(clone_path), all_branches=True)
        assert clone_path.exists()
        GitPythonRepo(clone_path)  # raises if it's not a git repository

    @classmethod
    def teardown_class(cls):
        return
