import pytest
from typing import Generator
from utf.devices import Device
from utf.utils.fixtures import get_fixture_params
from utf.harness import Harness
# from utf.utils.fixtures import set_device_state


@pytest.fixture()
def tls_server(
    request: pytest.FixtureRequest, harness
) -> Generator[Device, None, None]:
    server = harness.create_device_for_role(request.fixturename, request)
    fixture_params = get_fixture_params(request)
    server.update_config(**fixture_params)
    yield server
    server.restore_config()
