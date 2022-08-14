import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from functools import wraps
import logging
from typing import Callable

from object_database.database_connection import DatabaseConnection

from test_looper.repo_schema import Repository, RepoConfig
from test_looper.tl_git import GIT

logger = logging.getLogger('TestLooper')
logger.setLevel(logging.DEBUG)


def view(f):
    @wraps(f)
    def view_func(self, *args, **kwargs):
        with self.db.view():
            return f(self, *args, **kwargs)
    return view_func


def transaction(f):
    @wraps(f)
    def trans_func(self, *args, **kwargs):
        with self.db.transaction():
            return f(self, *args, **kwargs)
    return trans_func


def synchronized(func):
    func.__lock__ = threading.Lock()

    @wraps(func)
    def synced_func(*args, **kws):
        with func.__lock__:
            return func(*args, **kws)
    return synced_func


class ServiceMixin(ABC):

    def __init__(self, db: DatabaseConnection, repo_url: str):
        """
        Parameters
        ----------
        db: DatabaseConnection
            ODB connection
        repo_url: str
            The root url where we're going to put cloned repos
        """
        self.db = db
        self._shutdown = False
        self.logger = logger
        self.repo_url = repo_url

    @abstractmethod
    def start(self):
        # start threadloops
        pass

    def shutdown(self):
        self._shutdown = True

    @synchronized
    def start_threadloop(self, func: Callable, thread_name=None):
        if thread_name is None:
            thread_name = func.__name__
        attr_name = f'_{thread_name}_thread'
        t: threading.Thread = getattr(self, attr_name)
        if not t or not t.is_alive():
            t = threading.Thread(target=self.loop, name=thread_name,
                                 args=[func])
            setattr(self, attr_name, t)
            t.start()
        else:
            self.logger.info(f"Threadloop already running for {thread_name}")

    def loop(self, func, poll_interval=1):
        while not self._shutdown:
            func()
            time.sleep(poll_interval)

    def get_clone(self, repo: Repository):
        clone_path = os.path.join(self.repo_url, repo.name)
        is_found = os.path.exists(clone_path)
        return is_found, clone_path
