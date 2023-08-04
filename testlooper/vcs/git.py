"""
git.py

NB: this is ported code. All unchecked methods have been made private - if you need to use
a method, please check it, add a docstring, pep8ify, etc, then remove the leading underscore.
"""


import logging
import subprocess
import uuid
import os
import threading
import errno
import shutil
import re

from typing import Dict, Optional, List, Tuple

from testlooper.utils import setup_logger

__all__ = ["Git"]


logger = setup_logger(__name__, level=logging.ERROR)

sha_pattern = re.compile("^[a-f0-9]{40}$")


def is_sha_hash(committish):
    return sha_pattern.match(committish)


class Git:
    """
    A simple wrapper for local git operations.
    """

    # if we have multiple Git instances for the same repo, our lock is pointless
    # The lock may blow up in multithreaded/multiprocessing situations anyway.
    _instances: Dict[str, "Git"] = {}

    def __init__(self, path_to_repo: str):
        if path_to_repo in Git._instances:
            raise ValueError(f"Git instance already exists for {path_to_repo}")
        assert isinstance(path_to_repo, str)

        self.path_to_repo = str(path_to_repo)

        self.git_repo_lock = threading.RLock()

    @classmethod
    def get_instance(cls, path_to_repo: str) -> "Git":
        if path_to_repo not in cls._instances:
            cls._instances[path_to_repo] = cls(path_to_repo)
        return cls._instances[path_to_repo]

    def __repr__(self):
        return f"Git({self.path_to_repo})"

    def init(self, bare=False) -> None:
        """Initialise a git repo at the given path."""
        if not os.path.exists(self.path_to_repo):
            os.makedirs(self.path_to_repo)

        with self.git_repo_lock:
            if (
                self._subprocess_check_call(
                    ["git", "init", "."] + (["--bare"] if bare else [])
                )
                != 0
            ):
                msg = "Failed to init re at %s" % self.path_to_repo
                logger.error(msg)
                raise Exception(msg)

    def commit(self, msg, author, timestamp_override=None, dir_override=None):
        """Commit the current state of the repo and return the commit hash."""
        assert isinstance(author, str)

        with self.git_repo_lock:
            if dir_override is None:
                dir_override = self.path_to_repo

            assert dir_override is not None, dir_override

            assert self._subprocess_check_call_alt_dir(dir_override, ["git", "add", "."]) == 0

            env = dict(os.environ)

            if timestamp_override:
                timestamp_override_options = ["--date", str(timestamp_override) + " -0500"]
                env["GIT_COMMITTER_DATE"] = str(timestamp_override) + " -0500"
            else:
                timestamp_override_options = []

            env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = author.rsplit(" ", 1)

            cmds = (
                ["git", "commit", "--allow-empty", "-m", msg]
                + timestamp_override_options
                + ["--author", author]
            )

            res = self._subprocess_check_call_alt_dir(dir_override, cmds, env=env)
            assert res == 0, (res, cmds)

            return self._subprocess_check_output_alt_dir(
                dir_override, ["git", "log", "-n", "1", "--format=format:%H"]
            )

    def create_commit(
        self,
        commit_hash: str,
        file_contents: Dict[str, Optional[str]],
        commit_message: str,
        author: str,
        timestamp_override=None,
        on_branch=None,
    ) -> str:
        """Create a new commit.

        Args:
            commit_hash - the base commit to use, or None if we should use the current commit.
            file_contents - a dictionary of modifications to make. Keys are paths.
                Values are strings of file contents, or None which means to delete the file.
            on_branch - if not None, a string representing the branch to create or checkout
                for the commit.

        Returns:
            the sha hash of the new commit.
        """
        assert isinstance(author, str)

        with self.git_repo_lock:
            if commit_hash is not None:
                # if we're making a new branch, reset_to_commit would drop commits.
                if on_branch is None:
                    assert self._reset_to_commit(commit_hash)
                else:
                    assert self._is_valid_branch_name(on_branch)
                    if on_branch not in self.list_branches():
                        self._subprocess_check_call(
                            ["git", "checkout", "-b", on_branch, commit_hash]
                        )
                    else:
                        if not self.get_top_local_commit(on_branch) == commit_hash:
                            raise NotImplementedError(
                                "Can't create a commit on a branch that already exists \
                                        and has a different head."
                            )

            for file, contents in file_contents.items():
                path = os.path.join(self.path_to_repo, file)

                if contents is None:
                    if os.path.exists(path):
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                else:
                    self._ensure_directory_exists(os.path.split(path)[0])
                    with open(path, "w") as f:
                        f.write(contents)

            return self.commit(commit_message, author, timestamp_override)

    def detach_head(self) -> bool:
        with self.git_repo_lock:
            res = self._subprocess_check_call(["git", "checkout", "--detach", "HEAD"])
            if res != 0:
                logger.error("Failed to detach HEAD: git returned %s", res)
                return False
        return True

    def clone_from(self, source_repo: str) -> bool:
        if not os.path.exists(self.path_to_repo):
            os.makedirs(self.path_to_repo)

        with self.git_repo_lock:
            res = self._subprocess_check_call(["git", "clone", source_repo, "."])
            if res != 0:
                logger.error(
                    "Failed to clone source repo %s: git returned %s", source_repo, res
                )
                return False

        return True

    def push_commit(self, commit_hash, branch, force=False, create_branch=False) -> bool:
        """push a sha-hash to a branch and return True if successful."""
        assert commit_hash and isinstance(commit_hash, str)
        assert commit_hash.isalnum()
        assert " " not in branch

        if create_branch:
            branch = "refs/heads/" + branch

        return (
            self._subprocess_check_call(
                ["git", "push", "origin", "%s:%s" % (commit_hash, branch)]
                + (["-f"] if force else [])
            )
            == 0
        )

    def commit_exists(self, commit_hash):
        try:
            return commit_hash in self._subprocess_check_output(
                ["git", "rev-parse", "--quiet", "--verify", "%s^{commit}" % commit_hash]
            )
        except Exception:
            return False

    def list_branches(self) -> List[str]:
        """List the local branches, return a list of branch names."""
        with self.git_repo_lock:
            output = (
                self._subprocess_check_output(["git", "branch", "--list"]).strip().split("\n")
            )

            output = [line.strip() for line in output if line]
            output = [line[1:] if line[0] == "*" else line for line in output if line]
            output = [line.strip() for line in output if line]

            return [line for line in output if line and self._is_valid_branch_name(line)]

    def list_branches_for_remote(self, remote):
        """Check the remote and return a map from branchname->hash"""
        with self.git_repo_lock:
            lines = (
                self._subprocess_check_output(["git", "ls-remote", remote]).strip().split("\n")
            )

        res = {}
        for line in lines:
            if line.strip():
                hashcode, refname = line.split("\t", 1)
                hashcode = hashcode.strip()
                refname = refname.strip()
                if refname.startswith("refs/heads/"):
                    res[refname[len("refs/heads/") :]] = hashcode

        return res

    def list_currently_known_branches_for_remote(self, remote):
        """List the branches we currently know about"""
        with self.git_repo_lock:
            lines = self._subprocess_check_output(["git", "branch", "-r"]).strip().split("\n")
            lines = [
                line[: line.find(" -> ")].strip() if " -> " in line else line.strip()
                for line in lines
            ]
            lines = [line[7:].strip() for line in lines if line.startswith(f"{remote}/")]

            return [r for r in lines if r != "HEAD"]

    def fetch_origin(self) -> bool:
        with self.git_repo_lock:
            if self._subprocess_check_call(["git", "fetch", "-p"]) != 0:
                logger.error("Failed to fetch from origin: %s" % self.path_to_repo)
                return False
        return True

    def git_commit_data_multi(self, commit_hash: str, depth: int):
        """Get information on the previous <depth> commits from <commit_hash>.

        Returns:
            A list of tuples of (first commit, later commits, timestamp, message,
            author, authorEmail) for each commit.
        """

        with self.git_repo_lock:
            data = None
            try:
                uuid_line = "--" + str(uuid.uuid4()) + "--"
                uuid_item = "--" + str(uuid.uuid4()) + "--"

                result = []

                commandResult = self._subprocess_check_output(
                    [
                        "git",
                        "--no-pager",
                        "log",
                        "-n",
                        str(depth),
                        "--topo-order",
                        commit_hash,
                        "--format=format:"
                        + uuid_item.join(["%H %P", "%ct", "%B", "%an", "%ae"])
                        + uuid_line,
                    ]
                )

                for data in commandResult.split(uuid_line):
                    if data.strip():
                        commits, timestamp, message, author, authorEmail = data.split(
                            uuid_item
                        )
                        commits = [c.strip() for c in commits.split(" ") if c.strip()]

                        result.append(
                            (
                                commits[0],
                                commits[1:],
                                timestamp,
                                message.strip(),
                                author,
                                authorEmail,
                            )
                        )

                return result
            except Exception as e:
                logger.error("Failed to get git info on %s. data=%s", commit_hash, data)
                raise e

    def status(self) -> Dict[str, str]:
        """Return the status of the repo as a dict from filename to status."""
        with self.git_repo_lock:
            lines = self._subprocess_check_output(["git", "status", "--short"]).split("\n")

        res = {}
        for ln in lines:
            if ln:
                status = ln[1]
                fname = ln[3:]
                if " -> " in fname:
                    source, dest = fname.split(" -> ", 1)
                    res[source] = "renamed"
                    res[dest] = status
                else:
                    res[fname] = status

        return res

    def stage(self, file: str):
        """Stage file (or directory), relative to REPO_ROOT.

        E.g. to stage everything, use file='.'.
        """
        with self.git_repo_lock:
            self._subprocess_check_call(["git", "add", file])

    def create_merge(
        self,
        commit_hash: str,
        other_commits: List[str],
        commit_message: str,
        author: str,
        timestamp_override=None,
    ) -> str:
        """Create a merge commit.

        Args:
            commit_hash: The commit to merge into.
            other_commits: The commits to merge in.
        Returns:
            The hash of the merge commit

        """
        with self.git_repo_lock:
            self._reset_to_commit(commit_hash)

            env = dict(os.environ)

            if timestamp_override:
                timestamp_override_options = ["--date", str(timestamp_override) + " -0500"]
                env["GIT_COMMITTER_DATE"] = str(timestamp_override) + " -0500"
            else:
                timestamp_override_options = []

            cmds = (
                ["git", "merge"]
                + other_commits
                + ["-m", commit_message]
                + timestamp_override_options
            )

            env["EMAIL"] = author.rsplit(" ", 1)[1]

            assert self._subprocess_check_call(cmds, env=env) == 0

            return self._subprocess_check_output(
                ["git", "log", "-n", "1", "--format=format:%H"]
            ).strip()

    def get_top_local_commit(self, branch: str) -> str:
        """For a given branch name, return the top commit hash."""
        with self.git_repo_lock:
            return self._subprocess_check_output(["git", "rev-parse", branch]).strip()

    def get_commit_message(self, commit_hash: str) -> str:
        """Return the commit message for a given hash."""
        return self._subprocess_check_output(
            ["git", "show", "-s", "--format=format:%B", commit_hash]
        ).strip()

    def get_commit_author(self, commit_hash: str) -> str:
        """Return the commit author for a given hash."""
        return self._subprocess_check_output(
            ["git", "show", "-s", "--format=format:%an <%ae>", commit_hash]
        ).strip()

    def get_commit_author_name(self, commit_hash: str) -> str:
        """Return the commit author name for a given hash."""
        return self._subprocess_check_output(
            ["git", "show", "-s", "--format=format:%an", commit_hash]
        ).strip()

    def get_commit_author_email(self, commit_hash: str) -> str:
        """Return the commit author email for a given hash."""
        return self._subprocess_check_output(
            ["git", "show", "-s", "--format=format:%ae", commit_hash]
        ).strip()

    def get_commit_short_message(self, commit_hash: str) -> str:
        """Return the commit message for a given hash."""
        return self._subprocess_check_output(
            ["git", "show", "-s", "--format=format:%s", commit_hash]
        ).strip()

    def get_commit_chain(self, branch_name: str) -> List[Tuple[str, str]]:
        """From the top commit of a branch, return a list of (child, parent) commits.
        The final commit will just be (child,)
        """
        with self.git_repo_lock:
            return [
                tuple(x.split(" "))
                for x in self._subprocess_check_output(
                    ["git", "rev-list", "--parents", branch_name]
                ).split("\n")
                if x.strip()
            ]

    def get_top_commits_for_branch(self, branch_name: str, n) -> List[str]:
        """Return the top N commits for a branch."""
        return self._subprocess_check_output(
            ["git", "rev-list", "--reverse", "--max-count", str(n), branch_name]
        ).split("\n")

    def create_worktree_and_reset_to_commit(self, commit_hash, directory):
        with self.git_repo_lock:
            assert isinstance(commit_hash, str), commit_hash

            directory = os.path.abspath(directory)

            self._ensure_directory_exists(directory)

            logger.info("Resetting to revision %s in %s", commit_hash, directory)

            if not self._pull_latest():
                raise Exception("Couldn't pull latest from origin")

            if not self.commit_exists(commit_hash):
                raise Exception(
                    "Can't find commit %s at %s" % (commit_hash, self.path_to_repo)
                )

            if self._subprocess_check_call(
                ["git", "worktree", "add", "--detach", directory, commit_hash]
            ):
                raise Exception("Failed to create working tree at %s" % directory)

            if self._subprocess_check_call_alt_dir(
                directory, ["git", "reset", "--hard", commit_hash]
            ):
                raise Exception("Failed to checkout revision %s" % commit_hash)

    def get_file_contents(self, commit, path):
        with self.git_repo_lock:
            try:
                return self._subprocess_check_output(["git", "show", "%s:%s" % (commit, path)])
            except Exception:
                return None

    def _write_file(self, name, text):
        with open(os.path.join(self.path_to_repo, name), "w") as f:
            f.write(text)

    def _list_remotes(self):
        res = self._subprocess_check_output(["git", "remote"])
        return [x.strip() for x in res.split("\n") if x.strip() != ""]

    def _get_url_for_remote(self, remote="origin"):
        return self._subprocess_check_output(["git", "remote", "get-url", remote]).strip()

    def _get_source_repo_name(self, remote="origin"):
        url = self._get_url_for_remote(remote)
        if url.startswith("git@"):
            repo = url.split(":")[1]
            if repo.endswith(".git"):
                return repo[:-4]

        raise UserWarning("Can't detect source repo for " + url)

    def _pull_latest(self):
        remotes = self._list_remotes()
        if "origin" in remotes:
            return self._subprocess_check_call(["git", "fetch", "origin", "-p"]) == 0
        else:
            return True

    def _reset_to_commit(self, revision):
        logger.info("Resetting to revision %s", revision)

        if not self._pull_latest():
            return False

        return self._subprocess_check_call(["git", "reset", "--hard", revision]) == 0

    def _checkout_commit(self, revision):
        logger.info("Checking out revision %s", revision)

        if not self.commit_exists(revision):
            return False

        return self._subprocess_check_call(["git", "checkout", revision]) == 0

    def _ensure_directory_exists(self, path):
        if os.path.exists(path):
            return
        try:
            os.makedirs(path)
        except os.error as e:
            if e.errno != errno.EEXIST:
                raise

    def _list_files(self, commit):
        return [
            x.strip()
            for x in self._subprocess_check_output(
                ["git", "ls-tree", "--name-only", "-r", commit]
            ).split("\n")
            if x.strip()
        ]

    def _delete_remote_branch(self, branch, remote="origin"):
        return self._subprocess_check_call(["git", "push", "origin", ":%s" % (branch)]) == 0

    def _current_file_diff(self):
        return [
            x.strip()
            for x in self._subprocess_check_output(["git", "diff", "--name-only"]).split("\n")
            if x.strip()
        ]

    def _files_changed_between_commits(self, firstCommit, secondCommit):
        return [
            x.strip()
            for x in self._subprocess_check_output(
                ["git", "diff", "--name-only", firstCommit, secondCommit]
            ).split("\n")
            if x.strip()
        ]

    def _is_initialized(self):
        logger.debug("Checking existence of %s", os.path.join(self.path_to_repo, ".git"))
        return os.path.exists(os.path.join(self.path_to_repo, ".git"))

    def _closest_branch_for(self, hash, remoteName="origin", maxSearchDepth=100):
        """Find the branch closest to a given commit"""
        branches = []

        for b in self.list_currently_known_branches_for_remote(remoteName):
            hashes = [x[0] for x in self.git_commit_data_multi("origin/" + b, maxSearchDepth)]

            if hash in hashes:
                ix = hashes.index(hash)
                branches.append((ix, b))

        if branches:
            branches = sorted(branches)
            ix, branch = branches[0]

            return branch

    def _distance_for_commit_in_branch(self, hash, branch, maxSearchDepth=100):
        hashes = [x[0] for x in self.git_commit_data_multi("origin/" + branch, maxSearchDepth)]
        if hash not in hashes:
            return None
        return hashes.find(hash)

    def _standard_commit_message_for(self, commitHash):
        with self.git_repo_lock:
            return self._subprocess_check_output(["git", "log", "-n", "1", commitHash])

    def most_recent_hash_for_subpath(self, commitHash, subpath):
        with self.git_repo_lock:
            return (
                self._subprocess_check_output(
                    ["git", "log", "--format=format:%H", "-n", "1", commitHash, "--", subpath]
                )
                or None
            )

    def _git_commit_data(self, commitHash):
        """For a commit or revision, returns a tuple
        (hash, [parent hashes], timestamp, commit_summary, author, authorEmail)
        """
        return self.git_commit_data_multi(commitHash, depth=1)[0]

    def _reset_hard(self):
        with self.git_repo_lock:
            self._subprocess_check_output(["git", "reset", "--hard"])

    def _current_checked_out_commit(self):
        with self.git_repo_lock:
            try:
                commandResult = self._subprocess_check_output(
                    ["git", "--no-pager", "log", "-n", "1", "--format=format:%H"]
                )
                return commandResult.strip()
            except Exception:
                return None

    def _get_entire_tree(self, commit):
        with self.git_repo_lock:
            self._checkout_commit(commit)

            res = {}

            def walk(subdir):
                for item in os.listdir(os.path.join(self.path_to_repo, subdir)):
                    grab(os.path.join(subdir, item))

            def grab(path):
                fullPath = os.path.join(self.path_to_repo, path)

                if os.path.isfile(fullPath):
                    try:
                        with open(fullPath, "r") as f:
                            res[path] = f.read()
                    except Exception:
                        with open(fullPath, "rb") as f:
                            res[path] = f.read()
                else:
                    walk(path)

            for item in os.listdir(self.path_to_repo):
                if item != ".git":
                    grab(item)

        return res

    @staticmethod
    def _is_valid_branch_name(name):
        return name and "/HEAD" not in name and "(" not in name and "*" not in name

    def _subprocess_check_call_alt_dir(self, altDir, *args, **kwds):
        return SubprocessCheckCall(altDir, args, kwds)()

    def _subprocess_check_call(self, *args, **kwds):
        return self._subprocess_check_call_alt_dir(self.path_to_repo, *args, **kwds)

    def _subprocess_check_output(self, *args, **kwds):
        return SubprocessCheckOutput(self.path_to_repo, args, kwds)()

    def _subprocess_check_output_alt_dir(self, dir, *args, **kwds):
        return SubprocessCheckOutput(dir, args, kwds)()


class DirectoryScope:
    def __init__(self, directory: str):
        self.directory = directory

    def __enter__(self):
        self.cwd = os.getcwd()
        os.chdir(self.directory)

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.cwd)


class SubprocessCheckCall:
    def __init__(self, path: str, args, kwargs) -> None:
        self.path = path
        self.args = args
        self.kwargs = kwargs

    def __call__(self) -> int:
        with DirectoryScope(self.path):
            try:
                subprocess.check_output(*self.args, stderr=subprocess.STDOUT, **self.kwargs)
                return 0
            except subprocess.CalledProcessError as e:
                logger.error(
                    "call to git %s errored with code %s:\n%s",
                    self.args,
                    e.returncode,
                    e.output,
                )
                return e.returncode


class SubprocessCheckOutput:
    def __init__(self, path, args, kwargs) -> None:
        self.path = path
        self.args = args
        self.kwargs = kwargs

    def __call__(self) -> str:
        with DirectoryScope(self.path):
            return subprocess.check_output(
                *self.args, stderr=subprocess.STDOUT, **self.kwargs
            ).decode("utf-8")
