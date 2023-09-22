"""
utils.py
"""
import hashlib
import logging
import os
import re

from typing import Dict, Callable, Union

import object_database.web.cells as cells


TL_SERVICE_NAME = "TestlooperService"
H1_FONTSIZE = 25
H2_FONTSIZE = 20

# suite, then hash.
TEST_RUN_LOG_FORMAT_STDOUT = "test_run_{}_{}_{}_stdout.txt"
TEST_RUN_LOG_FORMAT_STDERR = "test_run_{}_{}__{}_stderr.txt"


def get_tl_link(instance) -> str:
    type_name = f"{instance.__schema__.name}.{type(instance).__name__}"
    return f"/services/{TL_SERVICE_NAME}/{type_name}/{instance._identity}"


def add_menu_bar(cell: cells.Cell, menu_items: Dict[str, Union[str, Callable]]) -> cells.Cell:
    """Given a cell representing a page, add a menu above.

    Args:
        cell: The cell representing the page layout.
        menu_items: A dict in which the keys are the button text and the
            values the string or function passed to Button.
            TODO: If the value is a list, generate a Dropdown
    """
    menu = cells.HorizontalSequence(
        [cells.Button(text, link) for text, link in menu_items.items()]
    )
    menu_bar_spacing = 25
    return cells.Padding(bottom=menu_bar_spacing) * menu + cell


def hash_docker_build_env(dockerfile: str) -> str:
    """Returns an MD5 hash of a docker-build environment.

    A docker-build environment is the collection of files present in the
    directory of the dockerfile.

    Args:
        dockerfile [str]: the path to a dockerfile or to a directory containing
            a 'Dockerfile'
    """
    if not os.path.exists(dockerfile):
        raise OSError(f"Path does not exist: {dockerfile}")

    if os.path.isdir(dockerfile):
        dockerdir = dockerfile
        dockerfile = os.path.join(dockerdir, "Dockerfile")
        if not os.path.isfile(dockerfile):
            raise OSError(f"Path does not exist: {dockerfile}")

    else:
        assert os.path.isfile(dockerfile)
        dockerdir, _ = os.path.split(dockerfile)

    digest = hashlib.md5()
    for root, dirs, files in os.walk(dockerdir):
        dirs.sort()
        for file in sorted(files):
            with open(os.path.join(root, file), "r") as fd:
                digest.update(fd.read())

    return digest.hexdigest()


# Define the ANSI escape codes for various colors
COLORS = {
    "WARNING": "\033[33m",  # Yellow
    "INFO": "\033[32m",  # Green
    "DEBUG": "\033[34m",  # Blue
    "CRITICAL": "\033[35m",  # Purple
    "ERROR": "\033[31m",  # Red
}

# Reset color
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record):
        colored_record = record
        levelname = colored_record.levelname
        seq = COLORS.get(levelname, RESET)
        colored_levelname = f"{seq}{levelname}{RESET}"
        colored_record.levelname = colored_levelname
        return super().format(colored_record)


def setup_logger(name, level=logging.DEBUG):
    """Function setup as many loggers as you want"""

    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


def parse_test_filter(db, test_filter, all_test_results):
    """Filter is on labels, paths, suites, and regex on name.

    Args:
        db (DatabaseConnection): The connection to ODB.
        test_filter (test_schema.TestFilter): The filter to apply.
        all_test_results (test_schema.TestResults): The set of test results to filter.

    Returns:
        Set[test_schema.TestResults]: The filtered set of test results.

    """
    # this is used in a thread so somewhat bad practice, but all the function does is
    # lookups so can't be avoided
    # (and we don't need our reactor to re-trigger on any of these variables).
    with db.view():
        filtered_tests = parse_test_filter_within_view(
            test_filter=test_filter, all_test_results=all_test_results
        )

    return filtered_tests


def parse_test_filter_within_view(test_filter, all_test_results):
    """As above, but assumes we are already within an ODB view when called."""
    filtered_tests = set()
    # Filter by labels
    if test_filter.labels == "Any" or test_filter.labels is None:
        filtered_tests = set(all_test_results)
    else:
        for test_result in all_test_results:
            for label in test_filter.labels:
                if test_result.test.label.startswith(label):
                    filtered_tests.add(test_result)

    # Filter by path prefixes
    path_set = set()
    if test_filter.path_prefixes is not None and test_filter.path_prefixes != "Any":
        for test_result in filtered_tests:
            for path_prefix in test_filter.path_prefixes:
                if test_result.test.path.startswith(path_prefix):
                    path_set.add(test_result)
        filtered_tests &= path_set

    # Filter by suites
    suite_set = set()
    if test_filter.suites is not None and test_filter.suites != "Any":
        for test_result in filtered_tests:
            for suite_name in test_filter.suites:
                if test_result.suite.name == suite_name:
                    suite_set.add(test_result)
        filtered_tests &= suite_set

    # Filter by regex
    regex_set = set()
    if test_filter.regex is not None:
        for test_result in filtered_tests:
            if re.match(test_filter.regex, test_result.test.name):
                regex_set.add(test_result)

        filtered_tests &= regex_set

    return filtered_tests


def get_node_id(test):
    """A test has a path and a name - the node_id used by pytest used in specifying which
    tests to run is a concatenation of these two."""
    return test.path + "::" + test.name


def filter_keys(d, cls):
    return {k: v for k, v in d.items() if k in cls.__annotations__}
