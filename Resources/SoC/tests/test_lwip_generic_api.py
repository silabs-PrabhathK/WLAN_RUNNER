import pytest
from sl_status import SLStatus


# Test Lwip init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_init_with_valid_input(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_lwip_init_with_invalid_parameters(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='thread', expected_status=SLStatus.SL_STATUS_FAIL)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_lwip_init_twice(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client', expected_status=SLStatus.SL_STATUS_ALREADY_INITIALIZED)


# Test net_up
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_up_with_valid_inputs(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_up_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0, expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_up_twice(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0,
                                       expected_status=SLStatus.SL_STATUS_SI91X_SCAN_ISSUED_IN_ASSOCIATED_STATE)


# Test deinit
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_deinit_with_valid_parameters(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_deinit_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Test net down
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_down(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_down(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_down_before_net_up(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_down(mode='client',
                                         expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_lwip_net_down_in_loop(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    for i in range(0, 5):
        wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
        wifi_dut.interfaces.wifi.sl_net_down(mode='client')
