"""
utils.py
"""
from . import TL_SERVICE_NAME


def get_tl_link(instance) -> str:
    type_name = f"{instance.__schema__.name}.{type(instance).__name__}"
    return f"/services/{TL_SERVICE_NAME}/{type_name}/{instance._identity}"
