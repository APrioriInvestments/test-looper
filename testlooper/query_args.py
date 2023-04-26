"""
Validates and parses query arguments.

NB: not currently in use.
"""
from dataclasses import dataclass


@dataclass
class QueryArgs:
    qargs_dict: dict
    _valid_qargs = {"repo", "branch", "commit", "test"}
    _current_page = None

    def __post_init__(self):
        if not self._validate():
            raise ValueError("Invalid query args")

    @property
    def current_page(self):
        if not self._current_page:
            self._current_page = self.get_current_page_type()
        return self._current_page

    def _validate(self):
        """Check that the qargs passed make sense.

        The menu bar flow is main -> repo -> branch -> commit, so
        if any of these qargs are present, the previous ones must
        also be. Other qargs ignored.
        """
        if self.qargs_dict.get("commit"):
            return self.qargs_dict.get("branch") and self.qargs_dict.get("repo")
        elif self.qargs_dict.get("branch"):
            return self.qargs_dict.get("repo")
        else:
            return True

    def get_current_page_type(self):
        """Returns the current page based on the query args."""
        if self.qargs_dict.get("commit"):
            return "commit"
        elif self.qargs_dict.get("branch"):
            return "branch"
        elif self.qargs_dict.get("repo"):
            return "repo"
        elif not self.qargs_dict:
            return "main"
        else:
            assert len(self.qargs_dict) == 1
            return list(self.qargs_dict.keys())[0]
