import pytest
import time
import random
from sl_status import SLStatus

random_mac_address = ':'.join([hex(random.randint(0, 255))[2:].zfill(2)] * 6)


# Tests for DUT in Access point mode

@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.start_ap()


# Test start_ap before wifi_init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_ap_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.start_ap(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test start_ap after wifi_init in client or eap mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_start_ap_with_deinit_and_init_in_client_or_eap_mode(wifi_dut):
    for type in ['client', 'eap']:
        wifi_dut.interfaces.wifi.init(mode=type)
        wifi_dut.interfaces.wifi.start_ap(expected_status=SLStatus.SL_STATUS_SI91X_CLIENT_MAX_SUPPORTED_EXCEEDED)
        wifi_dut.interfaces.wifi.deinit()


# Test start_ap after wifi_init in ap or apsta mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_start_ap_with_deinit_and_init_in_ap_or_apsta_mode(wifi_dut):
    for type in ['ap', 'apsta']:
        wifi_dut.interfaces.wifi.init(mode=type)
        wifi_dut.interfaces.wifi.start_ap()
        wifi_dut.interfaces.wifi.deinit()


# Test to get the client/s information in Access point mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_wifi_get_client_information_in_ap_or_apsta_mode(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    time.sleep(10)
    wifi_dut.interfaces.wifi.get_client_info()
    wifi_dut.interfaces.wifi.deinit()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_wifi_get_client_info_without_start_ap(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.get_client_info(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_client_info_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_client_info(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['client', 'eap'])
def test_wifi_get_client_info_in_client_or_eap_mode(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.get_client_info(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_get_client_info_with_init_deinit_flow(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_client_info()
    wifi_dut.interfaces.wifi.deinit()
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_client_info()


# Tests for disconnecting the connected stations in AP mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_disconnect_clients(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    time.sleep(10)
    mac_list = wifi_dut.interfaces.wifi.get_client_info()
    if mac_list is not None:
        wifi_dut.interfaces.wifi.disconnect_ap_client(client_mac=mac_list[random.randint(0, len(mac_list) - 1)])
    else:
        wifi_dut.interfaces.wifi.disconnect_ap_client(expected_status=SLStatus.SL_STATUS_INVALID_PARAMETER)


# Test for disconnecting the client with Random mac address
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_disconnect_clients_with_invalid_mac_address(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_client_info()
    wifi_dut.interfaces.wifi.disconnect_ap_client(client_mac=random_mac_address,
                                                  expected_status=SLStatus.SL_STATUS_SI91X_INVALID_MAC_SUPPLIED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['ap', 'apsta'])
def test_wifi_get_statistics_in_ap_mode(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_statistics()


# Test wifi_get_ap_client_list
@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_wifi_get_ap_client_list(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_get_ap_client_list()


# Test wifi_get_ap_client_list before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_list_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_get_ap_client_list(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_get_ap_client_list without start_ap
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_list_without_start_ap(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.wifi_get_ap_client_list(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Test wifi_get_ap_client_list in client mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_list_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.wifi_get_ap_client_list(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)
    wifi_dut.interfaces.wifi.deinit()


# Test wifi_get_ap_client_count
@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_wifi_get_ap_client_count(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_get_ap_client_count()


# Test wifi_get_ap_client_count before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_count_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_get_ap_client_count(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_get_ap_client_count without start_ap
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_count_without_start_ap(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.wifi_get_ap_client_count(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Test wifi_get_ap_client_count in client mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_client_count_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.wifi_get_ap_client_count(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Test get ap configuration before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_config(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_get_ap_config(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_config_before_ap_up(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.wifi_get_ap_config(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_ap_config_after_ap_up(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.wifi_get_ap_config()
