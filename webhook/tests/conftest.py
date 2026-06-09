import pytest


# Configure pytest-asyncio to auto mode so all async test functions
# are treated as asyncio coroutines without needing explicit markers.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as asyncio coroutine"
    )
