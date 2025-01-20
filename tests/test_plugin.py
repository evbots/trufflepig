import pytest
import requests
import os
from trufflepig.plugin import LOG_FILE
import json

# Helper function to read the log file and parse entries
def get_log_entries():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return [json.loads(line) for line in f]

def test_http_request_logged(monitor_http_requests):
    """
    Tests that an external HTTP request is logged correctly.
    """
    requests.get("https://www.example.com")

    entries = get_log_entries()
    assert len(entries) == 1
    entry = entries[0]

    assert entry["test_name"] == "test_http_request_logged"
    assert entry["http_host"] == "www.example.com"
    assert entry["http_method"] == "GET"
    assert entry["http_request_uri"].startswith("https://www.example.com")

def test_local_request_not_logged(monitor_http_requests):
    """
    Tests that a request to localhost is not logged.
    """
    try:
        requests.get("http://localhost:8080")
    except requests.exceptions.ConnectionError:
        pass  # We expect a connection error

    entries = get_log_entries()
    assert len(entries) == 0

def test_multiple_requests(monitor_http_requests):
    """
    Tests that multiple external HTTP requests are logged.
    """
    requests.get("https://www.google.com")
    requests.get("https://www.example.com/some/path")

    entries = get_log_entries()
    assert len(entries) == 2

    assert entries[0]["http_host"] == "www.google.com"
    assert entries[1]["http_host"] == "www.example.com"

# Clean up the log file after all tests in this module have run
@pytest.fixture(scope="module", autouse=True)
def cleanup_log_file():
    yield  # Run the tests
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)