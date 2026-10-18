"""Guards for the test harness itself."""

import socket

import httpx
import pytest
from pytest_socket import SocketBlockedError


def test_network_is_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_unmocked_http_fails_loudly():
    with pytest.raises((SocketBlockedError, httpx.HTTPError)):
        httpx.get("https://api.open-meteo.com/v1/forecast", timeout=1)
