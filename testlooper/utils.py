"""
utils.py
"""
from typing import Dict, Callable, Union

import object_database.web.cells as cells


TL_SERVICE_NAME = "TestlooperService"
HEADER_FONTSIZE = 25


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
