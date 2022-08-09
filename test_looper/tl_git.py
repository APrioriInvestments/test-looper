# The GIT class provides methods for interacting
# with GIT, github and related utilities

import os
import subprocess
import sys
import requests

# GitPython
from git import Repo


class GIT:
    def __init__(self, user=None, token=None, require_auth=False):
        self.user = user
        self.token = token
        self.session = requests.Session()
        self.require_auth = require_auth
        self.authenticated = False

    def authenticate(self):
        """
        I test credentials and set self.authenticated accordingly
        """
        self.session.auth = (self.user, self.token)
        # check the credentials are valid
        response = self.session.get(
            "https://api.github.com/users/%s" % self.user
        )
        if response.headers["X-RateLimit-Limit"] == "5000":
            self.authenticated = True
        elif self.require_auth:
            sys.exit("invalid github credentials")
        else:
            self.authenticated = False

    def clone(self, repo, directory, all_branches=False):
        """
        Parameters:
        ----------
        repo: str
            local path or url for repo
        directory: str
            path to target directory
        all_branches: bool, default False
            if True then clone with all remote branches
        """
        if not all_branches:
            return os.system(f"git clone {repo} {directory}")
        else:
            os.makedirs(directory, exist_ok=True)
            cmd = (
                f"cd {directory} && "
                f"git clone --mirror {repo} .git && "
                "git config --bool core.bare false && "
                "git reset --hard"
            )
            return subprocess.check_output(cmd, shell=True)

    def get_commit(self, repo, ref):
        return Repo(repo).commit(ref)

    def get_branch(self, repo, ref):
        for h in Repo(repo).heads:
            if h.name == ref:
                return h
        raise ValueError(f"{ref} branch was not found in {repo}")

    def list_branches(self, repo):
        return Repo(repo).heads

    def get_head(self, repo):
        return Repo(repo).head
