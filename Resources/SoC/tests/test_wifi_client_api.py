import pytest
import string
import random
from sl_status import SLStatus

random_ssid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
random_passphrase = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))


# List of Test cases for connect and disconnect:
# > Basic client connect in wpa/wpa2 personal security mode
# > Calling client connect when client is already connected in wpa/wpa2 personal security mode
# > Call WiFi client disconnect
# > Call WiFi client connect without initializing
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_personal(wifi_dut, wifi_access_point):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.join_ap(wifi_access_point)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_connect_without_disconnect(wifi_dut):
    wifi_dut.interfaces.wifi.join(expected_status=SLStatus.SL_STATUS_SI91X_SCAN_ISSUED_IN_ASSOCIATED_STATE)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect(wifi_dut):
    wifi_dut.interfaces.wifi.leave()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_personal_wrong_credentials(wifi_dut, wifi_access_point):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.join(ssid=wifi_access_point.interfaces.wifi.ssid, passphrase=random_passphrase,
                                  expected_status=SLStatus.SL_STATUS_SI91X_DEAUTHENTICATION)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_personal_non_existing_network(wifi_dut):
    wifi_dut.interfaces.wifi.join(ssid=random_ssid, expected_status=SLStatus.SL_STATUS_SI91X_NO_AP_FOUND)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.join(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# List of Test cases for get signal strength:
# get_signal_strength after init and connect
# get_signal_strength for all interfaces
# get_signal_strength for ap interfaces
# get_signal_strength before init
# get_signal_strength before connect()
# Call wifi_init() -> wifi_connect() -> wifi_get_signal_strength() -> disconnect()-> wifi_get_signal_strength() -> wifi_connect() -> wifi_get_signal_strength()

@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_get_signal_strength(wifi_dut):
    wifi_dut.interfaces.wifi.get_signal_strength()


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_get_signal_strength_for_2_4g_and_5g_interfaces(wifi_dut):
    wifi_dut.interfaces.wifi.get_signal_strength('client')
    wifi_dut.interfaces.wifi.get_signal_strength('client_5g', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_get_signal_strength_for_ap_interfaces(wifi_dut):
    wifi_dut.interfaces.wifi.get_signal_strength(interface='ap', expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_get_signal_strength_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_signal_strength(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_get_signal_strength_before_connect(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.get_signal_strength(expected_status=
                                                 SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_get_signal_strength_before_disconnect_and_after_reconnect(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.get_signal_strength(expected_status=
                                                 SLStatus.SL_STATUS_SI91X_COMMAND_GIVEN_IN_INVALID_STATE)
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.get_signal_strength()


# List of Test cases for join:
# Call wifi_connect() after wifi_init() in ap interface   
# Call wifi_connect() with timeout_ms = 0 and max value to uint32_t
# Call wifi_connect() with all security

@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_ap_interface(wifi_dut):
    wifi_dut.interfaces.wifi.join(interface='ap', expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_zero_time_out(wifi_dut):
    wifi_dut.interfaces.wifi.join(timeout_ms=0)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_max_time_out(wifi_dut):
    wifi_dut.interfaces.wifi.join(timeout_ms=4294967295)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_open_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="open")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_wpa_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="wpa")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_wep_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="wep")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_wpa_wpa2_mixed_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="wpa_wpa2_mixed")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_wpa3_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="wpa3")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_connect_with_wpa3_transition_wifi_security(wifi_dut):
    wifi_dut.interfaces.wifi.join(security="wpa3_transition")


# List of Test cases for leave:
# Call wifi_disconnect() after wifi_init() and wifi_connect()
# Call wifi_disconnect() without wifi_init()
# Call wifi_disconnect() without wifi_connect()
# Call wifi_disconnect() with ap interface
# Call wifi_disconnect() with 2.4g interfaces
# Call wifi_disconnect() with 5g interfaces
# Call wifi_init() -> wifi_connect() -> disconnect()--> wifi_connect()-> disconnect()

@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect(wifi_dut):
    wifi_dut.interfaces.wifi.leave()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_disconnect_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.leave(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_client_disconnect_without_connect(wifi_dut):
    wifi_dut.interfaces.wifi.leave(expected_status=SLStatus.SL_STATUS_SI91X_UNASSOCIATED)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect_with_ap_interface(wifi_dut):
    wifi_dut.interfaces.wifi.leave(interface='ap', expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect_with_2_4g_interface(wifi_dut):
    wifi_dut.interfaces.wifi.leave(interface='client')


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect_with_5g_interface(wifi_dut):
    wifi_dut.interfaces.wifi.leave(interface='client_5g', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_disconnect_twice(wifi_dut):
    wifi_dut.interfaces.wifi.leave()
    wifi_dut.interfaces.wifi.join()
    wifi_dut.interfaces.wifi.leave()


# Tests for wifi_set_roam_configuration():
# Test wifi_set_roam_configuration() before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_roam_configuration_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_roam_configuration(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Test wifi_set_roam_configuration() with different valid values for trigger_level
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('trigger_level', ['-40', '-50', '-55', '-60'])
def test_wifi_set_roam_configuration_with_different_valid_trigger_level_params(wifi_dut, trigger_level):
    wifi_dut.interfaces.wifi.set_roam_configuration(trigger_level=trigger_level)


# Test wifi_set_roam_configuration() with different valid values for trigger_level_change
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('trigger_level_change', ['40', '50', '55', '60'])
def test_wifi_set_roam_configuration_with_different_valid_trigger_level_change_params(wifi_dut, trigger_level_change):
    wifi_dut.interfaces.wifi.set_roam_configuration(trigger_level_change=trigger_level_change)


# Test wifi_set_roam_configuration() with invalid values for trigger_level
# NWP Firmware should validate trigger_level values, NWP JIRA created
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('trigger_level', ['5', '-5', '-110'])
def test_wifi_set_roam_configuration_with_different_invalid_trigger_level_params(wifi_dut, trigger_level):
    wifi_dut.interfaces.wifi.set_roam_configuration(trigger_level=trigger_level,
                                                    expected_status=SLStatus.SL_STATUS_FAIL)


# Test wifi_set_roam_configuration() with invalid values for trigger_level_change
# NWP Firmware should validate trigger_level_change values, NWP JIRA created
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('trigger_level_change', ['-10', '100'])
def test_wifi_set_roam_configuration_with_different_invalid_trigger_level_change_params(wifi_dut, trigger_level_change):
    wifi_dut.interfaces.wifi.set_roam_configuration(trigger_level_change=trigger_level_change,
                                                    expected_status=SLStatus.SL_STATUS_FAIL)


# Test wifi_set_roam_configuration() with ap interface
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_roam_configuration_with_ap_interface(wifi_dut):
    wifi_dut.interfaces.wifi.set_roam_configuration(interface="ap", expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


# Test wifi_client_configuration with valid credentials without timeout
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'apsta'])
def test_wifi_client_configuration_valid_input_with_timeout(wifi_dut, mode):
    wifi_dut.interfaces.wifi.init(mode=mode)
    wifi_dut.interfaces.wifi.wifi_test_client_configuration()


# Test wifi_client_configuration with invalid credentials without timeout
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'apsta'])
def test_wifi_client_configuration_invalid_input_without_timeout(wifi_dut, mode):
    wifi_dut.interfaces.wifi.init(mode=mode)
    wifi_dut.interfaces.wifi.wifi_test_client_configuration(passphrase='abcdefgh@123',
                                                            expected_status=SLStatus.SL_STATUS_SI91X_DEAUTHENTICATION)


# Test wifi_client_configuration with valid credentials with timeout
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'apsta'])
def test_wifi_client_configuration_valid_input_and_timeout(wifi_dut, mode):
    wifi_dut.interfaces.wifi.init(mode=mode)
    wifi_dut.interfaces.wifi.wifi_test_client_configuration(time=8000)


# Test wifi_client_configuration with invalid credentials without timeout
@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.mark.parametrize('mode', ['client', 'apsta'])
def test_wifi_client_configuration_invalid_input_and_without_timeout(wifi_dut, mode):
    wifi_dut.interfaces.wifi.init(mode=mode)
    wifi_dut.interfaces.wifi.wifi_test_client_configuration(passphrase='abcdefgh@123',
                                                            expected_status=SLStatus.SL_STATUS_SI91X_DEAUTHENTICATION)


# test wifi_client_configuration with valid credentials in invalid mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_configuration_invalid_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.wifi_test_client_configuration(expected_status=
                                                            SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)
    wifi_dut.interfaces.wifi.deinit()


# test wifi_client_configuration client configuration after connect to ap
@pytest.mark.start_state('wifi_dut', wifi='associated')
def test_wifi_client_configuration_after_connect_to_ap(wifi_dut):
    wifi_dut.interfaces.wifi.wifi_test_client_configuration(expected_status=
                                                            SLStatus.SL_STATUS_SI91X_SCAN_ISSUED_IN_ASSOCIATED_STATE)