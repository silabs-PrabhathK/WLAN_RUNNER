import pytest
from sl_status import SLStatus

MULTICAST_ADDR = "239.0.0.0"


# Test cases for star_ip()
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_start_ip(wifi_associated_dut):
    wifi_associated_dut.interfaces.wifi.start_ip()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_start_ip_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.start_ip(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_start_ip_before_connect(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.start_ip(expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_start_ip_before_disconnect_and_after_reconnect(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.start_ip()
    wifi_dut.interfaces.wifi.leave(interface='client')
    wifi_dut.interfaces.wifi.start_ip(expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_join_multicast_address(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.join_multicast_address(interface="client", multicast_address=MULTICAST_ADDR)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_join_multicast_address_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.join_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                    expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_join_multicast_address_without_connect(wifi_inited_dut):
    wifi_inited_dut.interfaces.wifi.join_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                           expected_status=
                                                           SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_net_join_multicast_address_without_start_ip(wifi_associated_dut):
    wifi_associated_dut.interfaces.wifi.join_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                               expected_status=
                                                               SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_leave_multicast_address(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.leave_multicast_address(interface="client", multicast_address=MULTICAST_ADDR)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_leave_multicast_address_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.leave_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                     expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_net_leave_multicast_address_without_connect(wifi_inited_dut):
    wifi_inited_dut.interfaces.wifi.leave_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                            expected_status=
                                                            SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_net_leave_multicast_address_without_start_ip(wifi_associated_dut):
    wifi_associated_dut.interfaces.wifi.leave_multicast_address(interface="client", multicast_address=MULTICAST_ADDR,
                                                                expected_status=
                                                                SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)
