import pytest
import string
import random
from sl_status import SLStatus


# List of Test cases for scan:
# test scan in different modes - client, ap, apsta and eap
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['client', 'ap', 'apsta', 'eap'])
def test_wifi_scan_in_different_modes(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    result = wifi_dut.interfaces.wifi.scan(ssid=None,
                                           expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP if
                                           wifi_init_mode == 'ap' else SLStatus.SL_STATUS_OK)
    print(result)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_scan_with_valid_ssid(wifi_dut, wifi_access_point):
    result = wifi_dut.interfaces.wifi.scan(ssid=wifi_access_point.interfaces.wifi.ssid)
    print(result)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_scan_with_invalid_ssid(wifi_dut):
    dummy_ssid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    result = wifi_dut.interfaces.wifi.scan(ssid=dummy_ssid, expected_status=SLStatus.SL_STATUS_SI91X_NO_AP_FOUND)
    print(result)


# test scan on interfaces - client, ap, client_5g and ap_5g
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('interface', ['client', 'ap', 'client_5g', 'ap_5g'])
def test_wifi_scan_on_interface(wifi_dut, interface):
    if interface == 'client':
        expected_error = SLStatus.SL_STATUS_OK
    elif interface == 'client_5g':
        expected_error = SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP
    else:
        expected_error = SLStatus.SL_STATUS_NOT_SUPPORTED
    result = wifi_dut.interfaces.wifi.scan(ssid=None, interface=interface, expected_status=expected_error)
    print(result)


# test scan on valid channels - 1,6,11
# channel=0 means default i.e. scan on all channels
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('channel', ['0', '1', '6', '11'])
def test_wifi_scan_on_valid_channels(wifi_dut, channel):
    wifi_dut.interfaces.wifi.scan(ssid=None, channel=channel)


# If invalid channel is provided as input to scan then FW will select channel 0/auto for scan
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_scan_on_invalid_channel(wifi_dut):
    wifi_dut.interfaces.wifi.scan(ssid=None, channel=36)


# test scan without init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_scan_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.scan(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Tests for wifi_scan() with bgscan enabled:
# Call wifi_scan() with bg_scan argument before calling wifi_connect()
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('wifi_init_mode', ['client', 'apsta', 'eap', 'ap'])
def test_wifi_bg_scan_before_connect(wifi_dut, wifi_init_mode):
    wifi_dut.interfaces.wifi.init(mode=wifi_init_mode)
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True, interface='ap' if wifi_init_mode == 'ap' else 'client',
                                  expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE
                                  if wifi_init_mode != 'ap' else SLStatus.SL_STATUS_NOT_SUPPORTED)


# Call wifi_scan() with bg_scan argument after connecting to ap()
@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_bg_scan_after_connect(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)


# Call wifi_scan() with bg_scan argument after connecting to ap() and after calling start_ip()
@pytest.mark.start_state('wifi_dut', wifi='networked')
def test_wifi_bg_scan_after_connect_and_start_ip(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)


# Call wifi_scan() with bg_scan type when inited in AP mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_bg_scan_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode="ap")
    wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True,
                                  expected_status=SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


# Test bg scan in given sequence: init -> connect -> bg scan -> disconnect -> connect -> bg scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_bg_scan_sequence_init_connect_bgscan_disconnect_connect_bgscan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.leave()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)


# Test bg scan in given sequence: init -> connect -> bg scan -> deinit -> init -> connect -> bg scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_bg_scan_sequence_init_connect_bgscan_deinit_init_connect_bgscan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.deinit()
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)


# Test bg scan by calling back to back twice with same periodicity
@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_bg_scan_after_connect_with_same_periodicity(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True, bg_scan_periodicity=10)
    print(result)
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True, bg_scan_periodicity=10)
    print(result)


# Test bg scan by calling back to back twice with different periodicity
@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_bg_scan_after_connect_with_different_periodicity(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True, bg_scan_periodicity=10)
    wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True, bg_scan_periodicity=20)


# Tests for wifi_scan_stop():
# Call stop_scan() without init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_stop_scan_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.stop_scan(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Call stop_scan() before connect and after foreground scan
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_stop_scan_before_connect_and_after_foreground_scan(wifi_dut):
    wifi_dut.interfaces.wifi.scan(ssid=None)
    wifi_dut.interfaces.wifi.stop_scan(expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


# Call stop_scan() without scan initiated
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_stop_scan_without_scan_initiated(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.stop_scan(expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


# Call stop_scan() which inited in AP mode and AP interface
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_stop_scan_in_ap_mode_with_ap_interface(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode="ap")
    wifi_dut.interfaces.wifi.stop_scan(interface="ap", expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


# Call stop_scan() after bg scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_stop_scan_after_bg_scan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()


# Call stop_scan() twice after bg scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_stop_scan_twice_after_bg_scan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()
    wifi_dut.interfaces.wifi.stop_scan(expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


# Test stop_scan in sequence: init -> connect -> bgscan -> stop_scan -> bgscan -> stop_scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_scan_stop_sequence_init_connect_bg_scan_stopscan_bgscan_stopscan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()


# Test stop_scan in sequence: init -> connect -> bgscan -> stop_scan -> deinit -> init -> connect -> bgscan -> stop_scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_scan_stop_sequence_init_connect_bg_scan_stopscan_deinit_init_connect_bgscan_stopscan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()
    wifi_dut.interfaces.wifi.deinit()
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()


# Test stop_scan in sequence: init -> connect -> bgscan -> stop_scan -> disconnect -> connect -> bgscan -> stop_scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_scan_stop_sequence_init_connect_bg_scan_stopscan_disconnect_connect_bgscan_stopscan(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()
    wifi_dut.interfaces.wifi.leave()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    result = wifi_dut.interfaces.wifi.scan(ssid=None, bgscan=True)
    print(result)
    wifi_dut.interfaces.wifi.stop_scan()


# Tests for wifi_set_advanced_scan_configuration():
# Test wifi_set_advanced_scan_configuration() before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_advanced_scan_configuration_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_set_advanced_scan_configuration() after init
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_advanced_scan_configuration_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()


# Test wifi_set_advanced_scan_configuration() after deinit
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_advanced_scan_configuration_after_deinit(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    wifi_dut.interfaces.wifi.deinit()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_set_advanced_scan_configuration() in sequence: init -> set_adv_scan -> deinit -> init -> set_adv_scan
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_advanced_scan_configuration_sequence_init_set_deinit_init_set(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()
    wifi_dut.interfaces.wifi.deinit()
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.set_advanced_scan_configuration()


# Tests for wifi_get_advanced_scan_configuration():
# Test wifi_get_advanced_scan_configuration() before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_advanced_scan_configuration_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_advanced_scan_configuration(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_get_advanced_scan_configuration() after init
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_advanced_scan_configuration_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_advanced_scan_configuration()


# sl_wifi_wait_for_scan_results() not supported after multithreading changes, required to fix this API
# Test wifi synchronous scan
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('channel', ['0', '1', '6', '11'])
def test_wifi_scan_sync_on_valid_channels(wifi_dut, channel):
    wifi_dut.interfaces.wifi.scan(ssid=None, channel=channel, sync=1)


# test scan on interfaces - client, ap, client_5g and ap_5g
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('interface', ['client', 'ap', 'client_5g', 'ap_5g'])
def test_wifi_scan_sync_on_interface(wifi_dut, interface):
    wifi_dut.interfaces.wifi.scan(ssid=None, interface=interface, sync=1)
