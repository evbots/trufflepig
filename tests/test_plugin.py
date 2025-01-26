import pytest
import requests


def test_http_request_logged():
    """
    Tests that an external HTTP request is logged correctly.
    """
    requests.get("http://www.example.com")

    # observe truffles.log to see the requests logged!
