"""base abstractions for reporting test metadata and state"""
from abc import ABC, abstractmethod


class TestReporter(ABC):
    # TODO report results, commit, etc

    @abstractmethod
    def report_tests(self, tests: list):
        """Report collected test names"""
        pass

