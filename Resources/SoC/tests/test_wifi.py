import pytest
from sl_status import SLStatus

# Test wifi init and deinit sequence
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_double_deinit(wifi_dut):
    wifi_dut.interfaces.wifi.deinit(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_double_init(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.init(mode='client', expected_status=SLStatus.SL_STATUS_ALREADY_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_deinit(wifi_dut):
    wifi_dut.interfaces.wifi.deinit()


# List of Test cases for performance_profile get and set:
# test get_performance_profile
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_performance_profile(wifi_dut):
    wifi_dut.interfaces.wifi.get_performance_profile()


# test set_performance_profile with invalid param
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_performance_profile_invalid_param(wifi_dut):
    wifi_dut.interfaces.wifi.set_performance_profile(mode='dummy', expected_status=SLStatus.SL_STATUS_INVALID_PARAMETER)


# test set and get performance_profile without wifi_init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_performance_profile_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_performance_profile(mode='power_saver',
                                                     expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_performance_profile_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_performance_profile(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# test set_performance_profile with valid params
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('profile_mode', ['high_performance', 'power_saver', 'power_saver_low_latency'])
def test_wifi_set_performance_profile_with_valid_params(wifi_dut, profile_mode):
    wifi_dut.interfaces.wifi.set_performance_profile(mode=profile_mode)
    result = wifi_dut.interfaces.wifi.get_performance_profile()
    if result == profile_mode.replace('_', ' '):
        wifi_dut.interfaces.wifi.logger.info(f"Matched {result} & {profile_mode}")
    else:
        wifi_dut.interfaces.wifi.logger.debug("Not matching!!")
    wifi_dut.interfaces.wifi.deinit()


# test set_performance_profile ultra_power_saver
# it requires wifi_init to be called after setting this mode
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_performance_profile_ups(wifi_dut):
    wifi_dut.interfaces.wifi.set_performance_profile(mode='ultra_power_saver')
    wifi_dut.interfaces.wifi.init()
    profile_mode = 'high_performance'
    result = wifi_dut.interfaces.wifi.get_performance_profile()
    if result == profile_mode.replace('_', ' '):
        wifi_dut.interfaces.wifi.logger.info(f"Matched {result} & {profile_mode}")
    else:
        wifi_dut.interfaces.wifi.logger.info(f"Not matching!!expected : {profile_mode} but recieved {result}")


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_init_deinit_cycle(wifi_dut):
    for i in range(10):
        wifi_dut.interfaces.wifi.init()
        wifi_dut.interfaces.wifi.deinit()


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_fw_version(wifi_dut):
    wifi_dut.interfaces.wifi.get_fw_version()


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_mac_address(wifi_dut):
    wifi_dut.interfaces.wifi.get_mac_address()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_mac_address_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_mac_address(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_statistics_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_statistics(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.skip
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_statistics_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.get_statistics(expected_status=SLStatus.SL_STATUS_SI91X_FEATURE_NOT_AVAILABLE)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_is_interface_up_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.is_interface_up("client", expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_is_interface_up(wifi_dut):
    wifi_dut.interfaces.wifi.is_interface_up("client")


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_is_interface_up_on_not_inited_interface(wifi_dut):
    wifi_dut.interfaces.wifi.is_interface_up("ap", expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_default_interface(wifi_dut):
    wifi_dut.interfaces.wifi.get_default_interface()


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_default_interface(wifi_dut):
    wifi_dut.interfaces.wifi.set_default_interface("ap")


@pytest.mark.skip
@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_wifi_get_statistics_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.get_statistics()


# Test cases for sl_wifi_set_transmit_rate API
# This API should be used before calling wifi_connect() and wifi_ap_up()
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_transmit_rate_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="auto", data_rate="auto",
                                               expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_transmit_rate_after_init_with_valid_param(wifi_dut):
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="auto", data_rate="auto")
    wifi_dut.interfaces.wifi.start_ap()


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_transmit_rate_with_invalid_protocol_and_rate_combinations(wifi_dut):
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="auto", data_rate="1Mbps",
                                               expected_status=SLStatus.SL_STATUS_INVALID_CONFIGURATION)
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="802.11b", data_rate="6Mbps",
                                               expected_status=SLStatus.SL_STATUS_INVALID_CONFIGURATION)
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="802.11g", data_rate="11Mbps",
                                               expected_status=SLStatus.SL_STATUS_INVALID_CONFIGURATION)
    wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="802.11n", data_rate="36Mbps",
                                               expected_status=SLStatus.SL_STATUS_INVALID_CONFIGURATION)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_transmit_rate_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_transmit_rate(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_get_transmit_rate_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_transmit_rate()


# Tests for wifi_generate_wps_pin
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_generate_wps_pin_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.generate_wps_pin(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_generate_wps_pin_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.generate_wps_pin()


# List of Test cases for set antenna :
# test set antenna before and after init
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_set_antenna_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_antenna()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_set_antenna_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_antenna(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# test set antenna all possible options
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('antenna', ['0', '1', '2', '3', '4'])
def test_wifi_set_antenna_options(wifi_dut, antenna):
    wifi_dut.interfaces.wifi.set_antenna(antenna=antenna)


# test set antenna on interfaces - client, ap, client_5g and ap_5g
@pytest.mark.start_state('wifi_dut', wifi='init')
@pytest.mark.parametrize('interface', ['client', 'ap', 'client_5g', 'ap_5g'])
def test_wifi_set_antenna_on_interfaces(wifi_dut, interface):
    wifi_dut.interfaces.wifi.set_antenna(interface=interface,
                                         expected_status=SLStatus.SL_STATUS_OK if interface == 'client' else
                                         SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_set_tx_power_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_tx_power(2, SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='init')
def test_set_tx_power_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_tx_power(6)


@pytest.mark.start_state('wifi_dut', wifi="init")
def test_get_tx_power_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.set_tx_power(6)
    wifi_dut.interfaces.wifi.get_tx_power(6)


@pytest.mark.start_state('wifi_dut', wifi="deinit")
def test_get_tx_power_before_set_tx_power_and_after_init(wifi_dut):
    wifi_dut.interfaces.wifi.init()
    wifi_dut.interfaces.wifi.get_tx_power(0)


@pytest.mark.start_state('wifi_dut', wifi="deinit")
def test_set_power_followed_by_connect_and_get_tx(wifi_dut, wifi_access_point):
    dBm_values = [0, 4, 6]

    for dBm_value in dBm_values:
        wifi_dut.interfaces.wifi.init()
        wifi_dut.interfaces.wifi.set_tx_power(dBm_value)
        wifi_dut.interfaces.wifi.join_ap(wifi_access_point)
        wifi_dut.interfaces.wifi.get_tx_power(dBm_value)
        wifi_dut.interfaces.wifi.deinit()


@pytest.mark.start_state('wifi_dut', wifi="deinit")
def test_set_tx_followed_by_ap_up_and_get_tx(wifi_dut):
    dBm_values = [0, 5, 7]

    for dBm_value in dBm_values:
        wifi_dut.interfaces.wifi.init()
        wifi_dut.interfaces.wifi.set_tx_power(dBm_value)
        wifi_dut.interfaces.wifi.start_ap()
        wifi_dut.interfaces.wifi.get_tx_power(dBm_value)
        wifi_dut.interfaces.wifi.deinit()


# Test wifi_start_statistic_report and wifi_stop_statistic_report
@pytest.mark.start_state('wifi_dut', wifi='init')
def test_wifi_statistic_report_start_and_stop(wifi_dut):
    wifi_dut.interfaces.wifi.start_statistic_report()
    wifi_dut.interfaces.wifi.stop_statistic_report()


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_statistic_report_start_and_stop_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.start_statistic_report(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)
    wifi_dut.interfaces.wifi.stop_statistic_report(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Tests for getting channel information in ap and client interfaces
# For apsta mode, both client and soft AP should be configured in the same channel.
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_valid_channel_in_apsta_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='apsta')
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_channel_info(interface='ap')
    wifi_dut.interfaces.wifi.get_channel_info(interface='client')


# Test to get channel value
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_valid_channel_in_client_mode(wifi_dut, wifi_access_point):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.join(ssid=wifi_access_point.interfaces.wifi.ssid,
                                  passphrase=wifi_access_point.interfaces.wifi.passphrase)
    wifi_dut.interfaces.wifi.get_channel_info(interface='client')


# Get channel info before init
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_channel_without_init(wifi_dut):
    wifi_dut.interfaces.wifi.get_channel_info(interface='client', expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


# Get channel of an access point interface in client mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_channel_of_ap_interface_after_init_in_client_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='client')
    wifi_dut.interfaces.wifi.get_channel_info('ap', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


# Get channel of a client interface in access point mode
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_get_channel_of_client_interface_after_init_in_ap_mode(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.start_ap()
    wifi_dut.interfaces.wifi.get_channel_info('client', expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_ap_start_wps_before_init(wifi_dut):
    wifi_dut.interfaces.wifi.start_wps(expected_status=SLStatus.SL_STATUS_NOT_INITIALIZED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_ap_start_wps_before_ap_up(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='ap')
    wifi_dut.interfaces.wifi.start_wps(expected_status=SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP)


@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_ap_start_wps_with_incorrect_interface(wifi_dut):
    wifi_dut.interfaces.wifi.start_wps(interface="client", expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_ap_start_wps_with_incorrect_wps_mode(wifi_dut):
    wifi_dut.interfaces.wifi.start_wps(wps_mode="pin", expected_status=SLStatus.SL_STATUS_NOT_SUPPORTED)


@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_ap_start_wps_with_wep_as_security_type(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode="ap")
    wifi_dut.interfaces.wifi.start_ap(security="wep")
    wifi_dut.interfaces.wifi.start_wps()


@pytest.mark.start_state('wifi_dut', wifi='softap')
def test_ap_start_wps_with_wpa2_as_security_type(wifi_dut):
    wifi_dut.interfaces.wifi.start_wps()


# Note: Known Firmware issue
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_ap_start_wps_with_wpa_security_as_security_type(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode="ap")
    wifi_dut.interfaces.wifi.start_ap(security="wpa")
    wifi_dut.interfaces.wifi.start_wps()
