
import pytest

def pytest_addoption(parser):
    parser.addoption("--collect-tests-and-markers", action="store_true",
                     help="Collect all tests and their markers")

class MarkerCollectorPlugin:

    def pytest_collection_modifyitems(self, session, config, items):
        if config.getoption("--collect-tests-and-markers"):
            for item in items:
                print(f"{item.nodeid}::{'|'.join(x.name for x in item.own_markers)}")
            pytest.exit("Done collecting tests and markers", returncode=0)
def pytest_configure(config):
    if config.getoption("--collect-tests-and-markers"):
        config.pluginmanager.register(MarkerCollectorPlugin())




