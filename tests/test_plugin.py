import pytest
import requests


def test_http_request_logged(monitor_http_requests):
    """
    Tests that an external HTTP request is logged correctly.
    """
    requests.get("http://www.example.com")

    # observe http_requests.log to see the requests logged!
