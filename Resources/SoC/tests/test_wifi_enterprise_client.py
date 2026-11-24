import pytest
import string
import random
from sl_status import SLStatus

invalid_passphrase = ''.join(random.choices(string.ascii_uppercase + string.digits, k=32))
invalid_ssid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=32))
EAP_SSID = 'enterprise'
EAP_USERNAME = 'user1'
EAP_PASSWORD = 'password1'
EAP_SECURITY = 'wpa2_enterprise'


def enterprise_ap_available():
    return False


@pytest.mark.start_state('wifi_dut', wifi='deinit')
@pytest.fixture()
def wifi_enterprise_dut(wifi_dut):
    wifi_dut.interfaces.wifi.init(mode='eap')
    yield wifi_dut


@pytest.mark.skipif(not enterprise_ap_available(), reason="Enterprise AP not available")
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_tls_enterprise(wifi_enterprise_dut):
    wifi_enterprise_dut.interfaces.wifi.join(ssid=EAP_SSID, passphrase=EAP_PASSWORD, uid=EAP_USERNAME,
                                             security=EAP_SECURITY, enc='tls')


@pytest.mark.skipif(not enterprise_ap_available(), reason="Enterprise AP not available")
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_ttls_enterprise(wifi_enterprise_dut):
    wifi_enterprise_dut.interfaces.wifi.join(ssid=EAP_SSID, passphrase=EAP_PASSWORD, uid=EAP_USERNAME,
                                             security=EAP_SECURITY, enc='ttls')


@pytest.mark.skipif(not enterprise_ap_available(), reason="Enterprise AP not available")
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_enterprise_wrong_credentials(wifi_enterprise_dut):
    wifi_enterprise_dut.interfaces.wifi.join(ssid=EAP_SSID, passphrase=invalid_passphrase, uid=EAP_USERNAME,
                                             security=EAP_SECURITY, enc='tls',
                                             expected_status=SLStatus.SL_STATUS_SI91X_DEAUTHENTICATION)


@pytest.mark.skipif(not enterprise_ap_available(), reason="Enterprise AP not available")
@pytest.mark.start_state('wifi_dut', wifi='deinit')
def test_wifi_client_connect_enterprise_non_existing_network(wifi_enterprise_dut):
    wifi_enterprise_dut.interfaces.wifi.join(ssid=invalid_ssid, passphrase=EAP_PASSWORD, uid=EAP_USERNAME,
                                             security=EAP_SECURITY, enc='tls',
                                             expected_status=SLStatus.SL_STATUS_SI91X_NO_AP_FOUND)
