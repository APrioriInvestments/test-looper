"""
utils.py
"""
import hashlib
import logging
import os

from typing import Dict, Callable, Union

import object_database.web.cells as cells


TL_SERVICE_NAME = "TestlooperService"
H1_FONTSIZE = 25
H2_FONTSIZE = 20


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
