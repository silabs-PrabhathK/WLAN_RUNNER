import pytest
from sl_status import SLStatus

IP_ADDR: str = "192.168.0.100"
DST_IP_ADDR: str = "192.168.0.198"


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'client'])
def test_sl_net_init_with_valid_input(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=wifi_init_mode)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_init_with_invalid_parameters(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='thread', expected_status=SLStatus.SL_STATUS_FAIL)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['ap', 'client'])
def test_sl_net_init_twice(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode, expected_status=SLStatus.SL_STATUS_ALREADY_INITIALIZED)


# Test net_up in client mode and ap mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_up_with_valid_inputs(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_up(mode=mode, profile_id=0)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_up_before_init(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_up(mode=mode, profile_id=0, expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_up_twice(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_up(mode=mode, profile_id=0)
    if mode == 'client':
        expected_error = SLStatus.SL_STATUS_SI91X_SCAN_ISSUED_IN_ASSOCIATED_STATE
    else:
        expected_error = SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE
    wifi_dut.interfaces.wifi.sl_net_up(mode=mode, profile_id=0, expected_status=expected_error)


# test it manually
# @pytest.mark.start_state('wifi_dut', wifi='deinit')
# @pytest.mark.parametrize('mode', ['ap', 'client'])
# def test_sl_net_up_with_invalid_profile_id(wifi_dut, mode):
#     wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
#     wifi_dut.interfaces.wifi.sl_net_up(mode=mode, profile_id=17, expected_status=SLStatus.SL_STATUS_INVALID_RANGE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_init_in_ap_mode_and_net_up_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='ap')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0,
                                       expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_init_in_client_mode_and_net_up_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='ap', profile_id=0,
                                       expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


# **Test deinit**
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_deinit_with_valid_parameters(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_up(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_deinit(mode=mode)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_deinit_before_init(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_deinit(mode=mode, expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_deinit_before_net_up(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_deinit_after_net_down(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_down(mode='client')
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_init_in_client_mode_and_deinit_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='ap', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_init_in_ap_mode_and_deinit_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='ap')
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'ap'])
def test_sl_net_deinit_twice(wifi_dut, mode):
    wifi_dut.interfaces.wifi.sl_net_init(mode=mode)
    if mode == 'ap':
        wifi_dut.interfaces.wifi.sl_net_up(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_deinit(mode=mode)
    wifi_dut.interfaces.wifi.sl_net_deinit(mode=mode, expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Test net down
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_down(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_down(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_down_before_net_up(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_down(mode='client',
                                         expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_down_in_loop(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    for i in range(0, 4):
        wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
        wifi_dut.interfaces.wifi.sl_net_down(mode='client')


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_call_net_up_in_client_mode_net_down_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_down(mode='ap', expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_call_net_down_after_net_deinit(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client')
    wifi_dut.interfaces.wifi.sl_net_down(mode='client', expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_down_after_send_data_to_remote(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    wifi_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    wifi_dut.interfaces.wifi.bsdSocketSend(socket_fd=0, data='Hello')
    wifi_dut.interfaces.wifi.bsdSockClose(socket_fd=0)
    wifi_dut.interfaces.wifi.sl_net_down(mode='client')


# Test Data integrity (make sure that all the data are we receiving from server or not)
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_receive_data_from_server(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    wifi_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    wifi_dut.interfaces.wifi.bsdSocketReceive(socket_fd=0)
    wifi_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bidirectional data transfer (note: open server in the another system)
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_sl_net_bidirectional_data_transfer(wifi_dut):
    wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    wifi_dut.interfaces.wifi.sl_net_up(mode='client', profile_id=0)
    wifi_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    wifi_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    wifi_dut.interfaces.wifi.bsdSocketReceive(socket_fd=0)
    wifi_dut.interfaces.wifi.bsdSocketSend(socket_fd=0, data="Thisisfromclient")
    wifi_dut.interfaces.wifi.bsdSockClose(socket_fd=0)
    wifi_dut.interfaces.wifi.sl_net_deinit(mode='client')
