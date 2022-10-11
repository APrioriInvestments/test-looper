# The GIT class provides methods for interacting
# with GIT, github and related utilities

import os
import uuid
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
            # TODO clean this up and make thread-safe
            tmp_dir = f"/tmp/{str(uuid.uuid4())}"
            os.makedirs(tmp_dir, exist_ok=True)
            os.makedirs(directory, exist_ok=True)
            cmd = (
                f"cd {tmp_dir} && "
                f"git clone --mirror {repo} .git && "
                "git config --bool core.bare false && "
                "git reset --hard && "
                f"rm -rf {directory} && "
                f"mv {tmp_dir} {directory}"
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

    def read_file(self, repo, file_path, ref) -> str:
        """Get a file from repo at a given reference"""
        cmd = f'cd {repo} && git show {ref}:{file_path} | cat'
        with subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              shell=True) as proc:
            stderr = proc.stderr.read().decode('utf-8').strip()
            stdout = proc.stdout.read().decode('utf-8').strip()
            err = f"fatal: path '{file_path}' does not exist in '{ref}'"
            if stderr == err:
                raise FileNotFoundError(stderr)
            if len(stdout) == 0:
                raise ValueError("test_looper.json was empty")
            return stdout

    @staticmethod
    def checkout(repo, ref):
        os.system(f"cd {repo} && git checkout {ref}")

    @staticmethod
    def init_repo(repo):
        cmd = (f'cd {repo} && '
               'git init && '
               'git add . && '
               'git commit -m "initial commit"')
        subprocess.check_call(cmd, shell=True)
