"""
Generate a dummy repo using our git wrapper, test the various functions.
"""

import os
import tempfile

import pytest
from testlooper.vcs import Git


@pytest.fixture(scope="module")
def dummy_repo():
    """Initialise the repo in the temp dir"""
    with tempfile.TemporaryDirectory() as temp_dir:
        base_repo = Git.Git(os.path.join(temp_dir, "base_repo"))
        yield base_repo


def test_basic_commits(dummy_repo):
    """Test the basic commit functionality"""
    dummy_repo.init()
    dummy_repo.commit("Initial commit")
    assert dummy_repo.get_commit_count() == 1
