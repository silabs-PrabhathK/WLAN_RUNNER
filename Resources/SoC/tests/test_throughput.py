import pytest
from utf.interfaces.iperf.fixtures import iperf_server
from .interfaces.fixtures import tls_server
import time


# Test wifi init and deinit sequence
@pytest.mark.start_state('wifi_dut', wifi='networked')
def test_wifi_throughput(wifi_dut, iperf_server):
    address = iperf_server.interfaces.network.get_ip_address()
    dut_address = wifi_dut.interfaces.wifi.get_ip_address()
    iperf_server.interfaces.iperf.start_server()
    wifi_dut.interfaces.wifi.iperf(family=2, transfer_type=1, protocol=6, local_port=5001, local_ip=dut_address, remote_ip=address, remote_port=5001, size=0, ttl=30)
    iperf_server.interfaces.iperf.stop()


# Test wifi init and deinit sequence
@pytest.mark.start_state('wifi_dut', wifi='networked')
def test_wifi_tls_tx_throughput(wifi_dut, tls_server):
    address = tls_server.interfaces.network.get_ip_address()
    dut_address = wifi_dut.interfaces.wifi.get_ip_address()
    tls_server.interfaces.tls_server.start_server(type=1)
    time.sleep(1)
    wifi_dut.interfaces.wifi.iperf(family=2, transfer_type=1, protocol=6, local_port=5001, local_ip=dut_address, remote_ip=address, remote_port=443, size=0, ttl=30, throughput_type=5)
    tls_server.interfaces.tls_server.stop()
    

# Test wifi init and deinit sequence
@pytest.mark.start_state('wifi_dut', wifi='networked')
def test_wifi_tls_rx_throughput(wifi_dut, tls_server):
    address = tls_server.interfaces.network.get_ip_address()
    dut_address = wifi_dut.interfaces.wifi.get_ip_address()
    tls_server.interfaces.tls_server.start_server(type=0)
    wifi_dut.interfaces.wifi.iperf(family=2, transfer_type=1, protocol=6, local_port=5001, local_ip=dut_address, remote_ip=address, remote_port=443, size=0, ttl=30, throughput_type=6)
    tls_server.interfaces.tls_server.stop()