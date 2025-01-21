import pytest

def pytest_addoption(parser):
    """
    Add a command-line option --truffle-hunt to enable the trufflepig fixture.
    """
    parser.addoption(
        "--truffle-hunt",
        action="store_true",
        default=False,
        help="Enable the trufflepig fixture which wraps all other fixtures."
    )


def pytest_configure(config):
    """
    Register the TrufflepigPlugin if --truffle-hunt is set.
    """
    if config.getoption("--truffle-hunt"):
        config.pluginmanager.register(TrufflepigPlugin(), "trufflepig-plugin")


class TrufflepigPlugin:
    """
    When active, this plugin injects 'trufflepig' as the first fixture for each test.
    """

    def pytest_collection_modifyitems(self, session, config, items):
        """
        After tests are collected, insert 'trufflepig' as the first fixture
        for each test item if it isn't already in the list.
        """
        for item in items:
            if "trufflepig" not in item.fixturenames:
                # Insert as the first fixture so it sets up before anything else
                item.fixturenames.insert(0, "trufflepig")
