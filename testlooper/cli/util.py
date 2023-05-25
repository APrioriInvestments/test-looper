class ClickContext:
    def __init__(self, ctx):
        ctx.ensure_object(dict)
        self.obj = ctx.obj

    def _set(self, key: str, value):
        self.obj[key] = value

    def _get(self, key: str, default=None):
        return self.obj.get(key, default)

    @property
    def verbosity(self):
        return self._get("verbosity", 0)

    @verbosity.setter
    def verbosity(self, value):
        return self._set("verbosity", value)

    @property
    def git_path(self):
        return self._get("git-path", None)

    @git_path.setter
    def git_path(self, value):
        return self._set("git-path", value)
