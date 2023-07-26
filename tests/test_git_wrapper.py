"""
Generate a dummy repo using our git wrapper, test the various functions.
"""

import os
import tempfile

import pytest
from testlooper.vcs import Git

AUTHOR = "author <author@aprioriinvestments.com>"
DUMMY_REPO_PATH = "base_repo"


@pytest.fixture(scope="module")
def dummy_repo_and_path():
    """Initialise the repo in the temp dir"""
    with tempfile.TemporaryDirectory() as temp_dir:
        dummy_path = os.path.join(temp_dir, DUMMY_REPO_PATH)
        base_repo = Git(dummy_path)
        yield dummy_path, base_repo


def test_git_basic_commits(dummy_repo_and_path):
    """Test the basic commit functionality.

    Make two dependent repos, clone from the base repo,
    commit in both. push the commit, make a new branch. fetch origin.
    Ensure that the commits and branches are in the right place.
    """
    # Initialise a repo, make a blank commit, add a second commit, detach.
    base_repo_path, base_repo = dummy_repo_and_path
    base_repo.init()
    h1 = base_repo.commit("message1", author=AUTHOR)
    h2 = base_repo.create_commit(
        h1, {"file1": "hi", "dir/file2": "contents"}, "message2", AUTHOR
    )
    base_repo.detach_head()

    with tempfile.TemporaryDirectory() as temp_dir:
        # clone two new repos, commit in the first, push the commit.
        # ensure that the commit is picked up by the base repo.
        dep_repo = Git(os.path.join(temp_dir, "dep_repo"))
        dep_repo.clone_from(base_repo_path)
        dep_repo_2 = Git(os.path.join(temp_dir, "dep_repo_2"))
        dep_repo_2.clone_from(base_repo_path)

        h2_1 = dep_repo.create_commit(
            h2, {"file1": "hi2_1", "dir/file2": None}, "message3", AUTHOR
        )
        h2_2 = dep_repo.create_commit(
            h2, {"file1": "hi2_2", "dir/file2": None}, "message3\n\nnewline\n\n", AUTHOR
        )

        assert dep_repo.push_commit(h2_1, "master", create_branch=True)
        assert base_repo.commit_exists(h2_1)

        assert not dep_repo.push_commit(h2_2, "master")
        assert not base_repo.commit_exists(h2_2)

        assert dep_repo.push_commit(h2_2, "master", force=True)
        assert base_repo.commit_exists(h2_2)

        assert not dep_repo.push_commit(h2_2, "new_branch")
        assert dep_repo.push_commit(h2_2, "new_branch", create_branch=True)
        assert dep_repo.push_commit(h2_2, "new_branch", create_branch=True)

        # check everyone can see the new branches
        assert "new_branch" in dep_repo.list_branches_for_remote("origin")
        assert "new_branch" not in dep_repo_2.list_currently_known_branches_for_remote(
            "origin"
        )
        assert "new_branch" in dep_repo_2.list_branches_for_remote("origin")

        assert dep_repo_2.fetch_origin()

        assert "new_branch" in dep_repo_2.list_currently_known_branches_for_remote("origin")

        # get commit data, check matching
        h2_2_info, h2_info = dep_repo.git_commit_data_multi(h2_2, 2)
        assert h2_2_info[0] == h2_2
        assert h2_2_info[1] == [h2]
        assert h2_2_info[3] == "message3\n\nnewline"
        assert h2_info[0] == h2
        assert h2_info[1] == [h1]
        assert h2_info[3] == "message2"


def test_git_status(dummy_repo_and_path):
    base_repo_path, base_repo = dummy_repo_and_path
    base_repo.init()

    h1 = base_repo.commit("message1", author=AUTHOR)
    base_repo.create_commit(h1, {"file1": "hi", "dir/file2": "contents"}, "message2", AUTHOR)

    with open(os.path.join(base_repo_path, "test.py"), "w") as f:
        f.write("hi\n")

    with open(os.path.join(base_repo_path, "file1"), "w") as f:
        f.write("hi2\n")

    assert base_repo.status() == {"test.py": "?", "file1": "M"}

    with open(os.path.join(base_repo_path, "dir", "file3"), "w") as f:
        f.write("contents")

    os.remove(os.path.join(base_repo_path, "dir", "file2"))

    base_repo.stage(".")

    assert base_repo.status() == {
        "test.py": " ",
        "file1": " ",
        "dir/file2": "renamed",
        "dir/file3": " ",
    }


@pytest.mark.slow
def test_git_most_recent_hash_for_subpath(dummy_repo_and_path):
    _, base_repo = dummy_repo_and_path
    base_repo.init()

    h1 = base_repo.commit("message1", author=AUTHOR)
    h2 = base_repo.create_commit(
        h1,
        {"file1": "hi", "dir1/file2": "contents", "dir2/file3": "contents"},
        "message2",
        AUTHOR,
    )
    h3 = base_repo.create_commit(h2, {"dir1/file2": "contents_2"}, "message3", AUTHOR)
    h4 = base_repo.create_commit(h3, {"dir2/file2": "contents_2"}, "message4", AUTHOR)
    h5 = base_repo.create_commit(
        h4, {"dir2/file2": "contents_2", "dir2": None}, "message4", AUTHOR
    )
    assert base_repo.most_recent_hash_for_subpath(h1, "dir1") is None
    assert base_repo.most_recent_hash_for_subpath(h1, "dir2") is None
    assert base_repo.most_recent_hash_for_subpath(h2, "dir1") == h2
    assert base_repo.most_recent_hash_for_subpath(h2, "dir2") == h2
    assert base_repo.most_recent_hash_for_subpath(h4, "dir1") == h3
    assert base_repo.most_recent_hash_for_subpath(h4, "dir2") == h4
    assert base_repo.most_recent_hash_for_subpath(h5, "dir2") == h5

    h6_left = base_repo.create_commit(h5, {"dir1/file2": "contents_left"}, "message", AUTHOR)
    h6_left_2 = base_repo.create_commit(
        h6_left, {"dir1/file2": "contents_final"}, "message", AUTHOR
    )

    h6_right = base_repo.create_commit(h5, {"dir1/file2": "contents_right"}, "message", AUTHOR)
    h6_right_2 = base_repo.create_commit(
        h6_right, {"dir1/file2": "contents_final"}, "message", AUTHOR
    )

    h7 = base_repo.create_merge(h6_left_2, [h6_right_2], "merge commit", AUTHOR)
    assert base_repo.most_recent_hash_for_subpath(h7, "dir1") == h6_left_2
