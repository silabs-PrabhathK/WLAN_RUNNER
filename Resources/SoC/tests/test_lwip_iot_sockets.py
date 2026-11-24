import time

import pytest
from sl_status import SLStatus
from lwip_errors import LwipIOTErrorStatus

LOCAL_IP = " 192.168.0.100"
REMOTE_IP = "192.168.0.101"

LOCAL_PORT = 5000
REMOTE_PORT = 5200
PORT1 = 5001
PORT2 = 5002
PORT3 = 5003
PORT4 = 5004


# LWIP Fixtures
@pytest.fixture()
def lwip_inited_dut(wifi_dut):
    if not wifi_dut.interfaces.wifi.inited:
        wifi_dut.interfaces.wifi.sl_net_init(mode='client')
    yield wifi_dut


@pytest.fixture()
def lwip_networked_dut(lwip_inited_dut):
    if not lwip_inited_dut.interfaces.wifi.networked:
        lwip_inited_dut.interfaces.wifi.sl_net_up(mode="client", profile_id=0)
    yield lwip_inited_dut


# Test iotSocketCreate with valid parameters
def test_lwip_valid_iotSocketCreate(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="udp")
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketCreate with invalid parameter for address family,type,protocol (Tested manually)
def test_lwip_iotSocketCreate_invalid_parameters(lwip_networked_dut):
    # invalid address family
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=3, type=1, protocol=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=3, type=2, protocol=2,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=3, type=1, protocol=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=3, type=2, protocol=2,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)

    # invalid type
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=1, type=3, protocol=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=1, type=3, protocol=2,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=2, type=3, protocol=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=2, type=3, protocol=2,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)

    # invalid protocol
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=1, type=1, protocol=3,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=1, type=2, protocol=3,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=2, type=1, protocol=3,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family=2, type=2, protocol=3,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)


# Test iotSocketCreate with invalid operation
def test_lwip_iotSocketCreate_invalid_operation(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="udp",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="tcp",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="udp",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="tcp",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)


# Test iotSocketCreate with invalid socket limit
def test_lwip_iotSocketCreate_invalid_Socket_limit(lwip_networked_dut):
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")

    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ERROR)
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketCreate without wifi_init
@pytest.mark.start_state("wifi_dut", wifi="deinit")
def test_lwip_iotSocketCreate_without_wifi_init(wifi_dut):
    wifi_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                             expected_status=LwipIOTErrorStatus.IOT_SOCKET_ERROR)


# Test iotSocketCreate without wifi_connect
def test_lwip_iotSocketCreate_without_wifi_connect(lwip_inited_dut):
    lwip_inited_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                                    expected_status=LwipIOTErrorStatus.IOT_SOCKET_ERROR)


# Test iotSocketBind with valid parameters
def test_lwip_valid_iotSocketBind(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="udp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=1, ip=LOCAL_IP, ip_len=4, port=PORT2)
    # lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=2, ip=LOCAL_IP, ip_len=16, port=PORT3)
    # lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=3, ip=LOCAL_IP, ip_len=16, port=PORT4)

    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketBind with invalid socket
def test_lwip_iotSocketBind_invalid_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=2, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)


# Test iotSocketBind with already binded socket
def test_lwip_invalid_iotSocketBind_already_binded_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid ip
# def test_lwip_iotSocketBind_invalid_ip(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
#     lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip="NULL", ip_len=4, port=PORT1,
#                                                      expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
#     lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)

# Test iotSocketBind with invalid ip length i.e 0
def test_lwip_iotSocketBind_invalid_ip_length(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=0, port=PORT1,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid ip length
def test_lwip_iotSocketBind_invalid_ip_length_IPV4_IPV6(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=10, port=PORT1,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid port
def test_lwip_iotSocketBind_invalid_port(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=0,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with already used port
def test_lwip_iotSocketBind_already_used_port(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_EADDRINUSE)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen with valid parameters
def test_lwip_valid_iotSocketListen(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen without socket bind
def test_lwip_invalid_iotSocketListen_without_bind(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen for invalid socket
def test_lwip_invalid_iotSocketListen_without_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=2, backlog=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)


# Test iotSocketListen for invalid backlog
def test_lwip_invalid_iotSocketListen_invalid_backlog(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=50,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen twice on same socket
def test_lwip_invalid_iotSocketListen_twice_on_same_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen on udp socket
def test_lwip_invalid_iotSocketListen_on_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT2)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTSUP)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketAccept with valid parameters
def test_lwip_valid_iotSocketAccept(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)


# Test iotSocketAccept with invalid socket
def test_lwip_invalid_iotSocketAccept_invalid_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)


# Test iotSocketAccept on udp socket
def test_lwip_invalid_iotSocketAccept_on_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT2)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTSUP)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTSUP)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketAccept and connection terminated from peer
def test_lwip_iotSocketAccept_when_connectoin_terminated_from_peer(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0, timeout=15)
    lwip_networked_dut.interfaces.wifi.iotSocketSend(socket=1, data="Hi_from_send_API")
    # Terminate remote
    time.sleep(5)
    lwip_networked_dut.interfaces.wifi.iotSocketSend(socket=1, data="Hi_from_send_API")


# Test iotSocketConnect with valid parameter
def test_lwip_valid_iotSocketConnect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


def test_lwip_call_iotSocketConnect_on_already_connected_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=PORT1)
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=PORT1,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EISCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid socket
def test_lwip_invalid_iotSocketConnect_invalid_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=PORT1,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)


# Test iotSocketConnect with invalid ip
# def test_lwip_invalid_iotSocketConnect_invalid_ip(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
#     lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip="NULL", ip_len=4, port=PORT1,
#                                                         expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
#     lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid ip length
def test_lwip_invalid_iotSocketConnect_invalid_ip_len(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=14, port=PORT1,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


def test_lwip_non_existing_ip_iotSocketConnect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip="192.168.7.121", ip_len=14, port=PORT1,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid port
def test_lwip_invalid_iotSocketConnect_invalid_port(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=0,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose with valid parameter
def test_lwip_valid_iotSocketClose(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose with invalid socket
def test_lwip_invalid_iotSocketClose_invalid_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=5, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose on same socket twice
def test_lwip_invalid_iotSocketClose_on_same_socket_twice(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)


def test_lwip_iot_socket_set_opt_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=0, opt_id="keepalivetimeout", opt_value=1000)
    lwip_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="keepalivetimeout")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSetOpt API with invalid socket id
def test_lwip_iot_socket_set_opt_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=10, opt_id="keepalivetimeout", opt_value=1000,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetOpt API with valid parameters
def test_lwip_iot_socket_get_opt_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=0, opt_id="keepalivetimeout", opt_value=1000)
    lwip_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="keepalivetimeout")
    lwip_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="sockettype")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetOpt API with invalid socket id
def test_lwip_iot_socket_get_opt_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=10, opt_id="keepalivetimeout",
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetHostByName API with valid parameters
def test_lwip_iot_socket_get_host_by_name_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv4", ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv6", ip_len=16)


# Test iotSocketGetHostByName API with invalid ip length
def test_lwip_iot_socket_get_host_by_name_with_invalid_ip_len(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv4", ip_len=2,
                                                              expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv6", ip_len=4,
                                                              expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)


# Test iotSocketGetHostByName API with invalid url
def test_lwip_iot_socket_get_host_by_name_with_invalid_url(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="test.url", address_family="ipv6", ip_len=4,
                                                              expected_status=LwipIOTErrorStatus.IOT_SOCKET_EHOSTNOTFOUND)
    lwip_networked_dut.interfaces.wifi.iotSocketGetHostByName(
        url="qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklxcvbnmdfghrtyuvbndfghjertyucvbndfghjrtyuivbnbdfgh.com",
        address_family="ipv4", ip_len=4, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTSUP)


# Test iotSocketGetSockName API after calling iotSocketBind with valid parameters
def test_lwip_iot_socket_get_sock_name_after_bind_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetSockName API after calling iotSocketBind with invalid socket id
def test_lwip_iot_socket_get_sock_name_after_bind_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=10,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetSockName API before calling iotSocketBind
def test_lwip_iot_socket_get_sock_name_before_bind(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=0,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API after calling iotSocketConnect with valid parameters
def test_lwip_iot_socket_get_peer_name_after_connect_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API after calling iotSocketConnect with invalid socket id
def test_lwip_iot_socket_get_peer_name_after_connect_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=2,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API before calling iotSocketConnect
def test_lwip_iot_socket_get_peer_name_before_connect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=0,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend after calling iotSocketConnect with valid parameters
def test_lwip_iot_socket_send_after_connect_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    time.sleep(10)
    lwip_networked_dut.interfaces.wifi.iotSocketSend(socket=0, data="Hi_from_send_API")
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend after calling iotSocketConnect with invalid socket id
def test_lwip_iot_socket_send_after_connect_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketSend(socket=10, data="Hi_from_send_API",
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend before calling iotSocketConnect
def test_lwip_iot_socket_send_before_calling_connect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSend(socket=0, data="Hi_from_send_API",
                                                     expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with valid parameters
def test_lwip_iot_socket_send_to_after_connect_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with invalid socket id
def test_lwip_iot_socket_send_to_after_connect_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=10, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with no data or 0 data length (Tested manually by hardcoding data="" in API)
# def test_lwip_iot_socket_send_to_after_connect_with_invalid_data_len(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
#     lwip_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
#     lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="", ip=REMOTE_IP, ip_len=4, port=REMOTE_PORT,
#                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
#     lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)

# Test iotSocketSendTo before calling iotSocketConnect
def test_lwip_iot_socket_send_to_before_connect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo over UDP with valid parameters
def test_lwip_iot_socket_send_to_over_udp_socket_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_udp_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo over UDP with invalid socket id
def test_lwip_iot_socket_send_to_over_udp_socket_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=10, data="Hi_from_udp_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT,
                                                       expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo with udp socket no data or 0 data length (Tested manually by hardcoding data="" in API)
# def test_lwip_iot_socket_send_to_over_udp_socket_with_invalid_data_len(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
#     lwip_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="", ip=REMOTE_IP, ip_len=4, port=REMOTE_PORT,
#                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_EINVAL)
#     lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)

# Test iotSocketReceive after iotSocketAccept with valid parameters
def test_lwip_iot_socket_receive_after_accept_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketReceive(socket=1, expected_status=LwipIOTErrorStatus.IOT_SOCKET_EAGAIN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceive after iotSocketAccept with invalid socket id
def test_lwip_iot_socket_receive_after_accept_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketReceive(socket=10, expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceive before iotSocketAccept
def test_lwip_iot_socket_receive_before_accept(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketReceive(socket=0,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


def test_lwip_iot_socket_receive_if_remote_doesnt_send_any_data(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketReceive(socket=1, expected_status=LwipIOTErrorStatus.IOT_SOCKET_EAGAIN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


def test_lwip_iot_socket_receive_after_connection_terminated_locally(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketReceive(socket=1,
                                                        expected_status=LwipIOTErrorStatus.IOT_SOCKET_ECONNABORTED)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp after iotSocketAccept with valid parameters
def test_lwip_iot_socket_receive_from_after_accept_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp after iotSocketAccept with invalid socket id
def test_lwip_iot_socket_receive_from_after_accept_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    lwip_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=10,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp before iotSocketAccept
def test_lwip_iot_socket_receive_from_before_accept(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=0,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ENOTCONN)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom after creating udp socket with valid parameters
def test_lwip_iot_socket_receive_from_with_valid_parameters_over_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=0, timeout=15)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom after creating udp socket with invalid socket id
def test_lwip_iot_socket_receive_from_with_invalid_socket_id_over_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    lwip_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    lwip_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=10,
                                                            expected_status=LwipIOTErrorStatus.IOT_SOCKET_ESOCK)
    lwip_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
