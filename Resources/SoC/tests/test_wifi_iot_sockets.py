import time

import pytest
from sl_status import SLStatus
from iot_errors import IOTStatus

LOCAL_IP = "192.168.0.218"
REMOTE_IP = "192.168.0.198"

LOCAL_PORT = 5000
REMOTE_PORT = 5200
PORT1 = 5001
PORT2 = 5002
PORT3 = 5003
PORT4 = 5004


# Test iotSocketCreate with valid parameters
def test_valid_iotSocketCreate(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="udp")
    for i in range(0, 4):
        wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketCreate with invalid parameter for address family,type,protocol (Tested manually)
# def test_iotSocketCreate_invalid_parameters(wifi_networked_dut):
#         #invalid address family
#         wifi_networked_dut.interfaces.wifi.get_ip_address()
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv7", type="stream", protocol="tcp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv7", type="dgram", protocol="udp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv7", type="stream", protocol="tcp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv7", type="dgram", protocol="udp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#
#         #invalid type
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="streamm", protocol="tcp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="streamm", protocol="udp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="streamm", protocol="tcp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="streamm", protocol="udp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#
#         #invalid protocol
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcpp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="tcpp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="tcpp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#         wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="tcpp",
#                                                            expected_status=IOTStatus.IOT_SOCKET_EINVAL)


# Test iotSocketCreate with invalid operation
def test_iotSocketCreate_invalid_operation(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="udp",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="tcp",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="udp",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="tcp",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)


# Test iotSocketCreate with invalid socket limit
def test_iotSocketCreate_invalid_Socket_limit(wifi_networked_dut):
    for i in range(0, 10):
        wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")

    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOMEM)

    for i in range(0, 10):
        wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketCreate without wifi_init
@pytest.mark.start_state("wifi_dut", wifi="deinit")
def test_iotSocketCreate_without_wifi_init(wifi_dut):
    wifi_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                             expected_status=IOTStatus.IOT_SOCKET_ERROR)


# Test iotSocketCreate without wifi_connect
def test_iotSocketCreate_without_wifi_connect(wifi_inited_dut):
    wifi_inited_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                                    expected_status=IOTStatus.IOT_SOCKET_ERROR)


# Test iotSocketCreate without get_ip_address
def test_iotSocketCreate_without_wifi_get_ip_address(wifi_associated_dut):
    wifi_associated_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp",
                                                        expected_status=IOTStatus.IOT_SOCKET_ERROR)


# Test iotSocketBind with valid parameters
def test_valid_iotSocketBind(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv6", type="dgram", protocol="udp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=1, ip=LOCAL_IP, ip_len=4, port=PORT2)
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=2, ip=LOCAL_IP, ip_len=16, port=PORT3)
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=3, ip=LOCAL_IP, ip_len=16, port=PORT4)

    for i in range(0, 4):
        wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=i)


# Test iotSocketBind with invalid socket
def test_iotSocketBind_invalid_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=2, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=IOTStatus.IOT_SOCKET_ESOCK)


# Test iotSocketBind with already binded socket
def test_invalid_iotSocketBind_already_binded_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid ip
# def test_iotSocketBind_invalid_ip(wifi_networked_dut):
#     wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
#     wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip="NULL", ip_len=4, port=PORT1,
#                                                      expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#     wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid ip length i.e 0
def test_iotSocketBind_invalid_ip_length(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=0, port=PORT1,
                                                     expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid ip length
def test_iotSocketBind_invalid_ip_length_IPV4_IPV6(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=10, port=PORT1,
                                                     expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with invalid port
def test_iotSocketBind_invalid_port(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=0,
                                                     expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketBind with already used port
def test_iotSocketBind_already_used_port(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1,
                                                     expected_status=IOTStatus.IOT_SOCKET_EADDRINUSE)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen with valid parameters
def test_valid_iotSocketListen(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen without socket bind
def test_invalid_iotSocketListen_without_bind(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1, expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen for invalid socket
@pytest.mark.start_state('wifi_networked_dut', wifi='associated')
def test_invalid_iotSocketListen_without_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=2, backlog=1, expected_status=IOTStatus.IOT_SOCKET_ESOCK)


# Test iotSocketListen for invalid backlog
def test_invalid_iotSocketListen_invalid_backlog(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=50,
                                                       expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen twice on same socket
def test_invalid_iotSocketListen_twice_on_same_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketListen on udp socket
def test_invalid_iotSocketListen_on_udp_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT2)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketAccept with valid parameters
def test_valid_iotSocketAccept(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=1)


# Test iotSocketAccept with invalid socket
def test_invalid_iotSocketAccept_invalid_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0, expected_status=IOTStatus.IOT_SOCKET_ESOCK)


# Test iotSocketAccept on udp socket
def test_invalid_iotSocketAccept_on_udp_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="dgram", protocol="udp")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, ip_len=4, port=PORT2)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1,
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0, expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with valid parameter
def test_valid_iotSocketConnect(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=PORT1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid socket
def test_invalid_iotSocketConnect_invalid_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=4, ip=REMOTE_IP, ip_len=4, port=PORT1,
                                                        expected_status=IOTStatus.IOT_SOCKET_ESOCK)


# Test iotSocketConnect with invalid ip
# def test_invalid_iotSocketConnect_invalid_ip(wifi_networked_dut):
#     wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
#     wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip="NULL", ip_len=4, port=PORT1,
#                                                         expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#     wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid ip length
def test_invalid_iotSocketConnect_invalid_ip_len(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=14, port=PORT1,
                                                        expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketConnect with invalid port
def test_invalid_iotSocketConnect_invalid_port(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, ip_len=4, port=0,
                                                        expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose with valid parameter
def test_valid_iotSocketClose(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose with invalid socket
def test_invalid_iotSocketClose_invalid_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=5, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketClose on same socket twice
def test_invalid_iotSocketClose_on_same_socket_twice(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(address_family="ipv4", type="stream", protocol="tcp")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0, expected_status=IOTStatus.IOT_SOCKET_ESOCK)


# Test iotSocketSetOpt API with valid parameters (currently only RECVTIMEOUT is valid)
def test_iot_socket_set_opt_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=0, opt_id="recvtimeout", opt_value=1000)
    wifi_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="recvtimeout")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSetOpt API with invalid socket id
def test_iot_socket_set_opt_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=10, opt_id="recvtimeout", opt_value=1000,
                                                       expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSetOpt API with invalid option id (currently fionbio is invalid)
def test_iot_socket_set_opt_with_invalid_option_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=0, opt_id="fionbio", opt_value=1000,
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetOpt API with valid parameters
def test_iot_socket_get_opt_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSetOpt(socket=0, opt_id="recvtimeout", opt_value=1000)
    wifi_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="recvtimeout")
    wifi_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="sockettype")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetOpt API with invalid socket id
def test_iot_socket_get_opt_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=10, opt_id="sockettype",
                                                       expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetOpt API with invalid option id (currently keepalivetimeout is invalid)
def test_iot_socket_get_opt_with_invalid_option_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketGetOpt(socket=0, opt_id="keepalivetimeout",
                                                       expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetHostByName API with valid parameters
def test_iot_socket_get_host_by_name_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv4", ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv6", ip_len=16)


# Test iotSocketGetHostByName API with invalid ip length
def test_iot_socket_get_host_by_name_with_invalid_ip_len(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv4", ip_len=2,
                                                              expected_status=IOTStatus.IOT_SOCKET_EINVAL)
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="www.google.com", address_family="ipv6", ip_len=4,
                                                              expected_status=IOTStatus.IOT_SOCKET_EINVAL)


# Test iotSocketGetHostByName API with invalid url
def test_iot_socket_get_host_by_name_with_invalid_url(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(url="test.url", address_family="ipv6", ip_len=4,
                                                              expected_status=IOTStatus.IOT_SOCKET_EHOSTNOTFOUND)
    wifi_networked_dut.interfaces.wifi.iotSocketGetHostByName(
        url="qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklxcvbnmdfghrtyuvbndfghjertyucvbndfghjrtyuivbnbdfgh.com",
        address_family="ipv4", ip_len=4, expected_status=IOTStatus.IOT_SOCKET_ENOTSUP)


# Test iotSocketGetSockName API after calling iotSocketBind with valid parameters
def test_iot_socket_get_sock_name_after_bind_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetSockName API after calling iotSocketBind with invalid socket id
def test_iot_socket_get_sock_name_after_bind_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=10, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetSockName API before calling iotSocketBind
def test_iot_socket_get_sock_name_before_bind(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketGetSockName(socket=0, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API after calling iotSocketConnect with valid parameters
def test_iot_socket_get_peer_name_after_connect_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API after calling iotSocketConnect with invalid socket id
def test_iot_socket_get_peer_name_after_connect_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=10, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketGetPeerName API before calling iotSocketConnect
def test_iot_socket_get_peer_name_before_connect(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketGetPeerName(socket=0, expected_status=IOTStatus.IOT_SOCKET_ENOTCONN)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend after calling iotSocketConnect with valid parameters
def test_iot_socket_send_after_connect_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketSend(socket=0, data="Hi_from_send_API")
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend after calling iotSocketConnect with invalid socket id
def test_iot_socket_send_after_connect_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketSend(socket=10, data="Hi_from_send_API",
                                                     expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend after calling iotSocketConnect with 0 data length (Tested manually by hardcoding data="" in API)
# def test_iot_socket_send_after_connect_with_invalid_data_len(wifi_networked_dut):
#     wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
#     wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
#     wifi_networked_dut.interfaces.wifi.iotSocketSend(socket=0, data="", expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#     wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSend before calling iotSocketConnect
def test_iot_socket_send_before_calling_connect(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSend(socket=0, data="Hi_from_send_API",
                                                     expected_status=IOTStatus.IOT_SOCKET_ENOTCONN)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with valid parameters
def test_iot_socket_send_to_after_connect_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with invalid socket id
def test_iot_socket_send_to_after_connect_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=10, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo after connect with no data or 0 data length (Tested manually by hardcoding data="" in API)
# def test_iot_socket_send_to_after_connect_with_invalid_data_len(wifi_networked_dut):
#     wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
#     wifi_networked_dut.interfaces.wifi.iotSocketConnect(socket=0, ip=REMOTE_IP, port=REMOTE_PORT, ip_len=4)
#     wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="", ip=REMOTE_IP, ip_len=4, port=REMOTE_PORT,
#                                                        expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#     wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo before calling iotSocketConnect
def test_iot_socket_send_to_before_connect(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT, expected_status=IOTStatus.IOT_SOCKET_ENOTCONN)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo over UDP with valid parameters
def test_iot_socket_send_to_over_udp_socket_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="Hi_from_udp_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo over UDP with invalid socket id
def test_iot_socket_send_to_over_udp_socket_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=10, data="Hi_from_udp_sendto_API", ip=REMOTE_IP, ip_len=4,
                                                       port=REMOTE_PORT, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketSendTo with udp socket no data or 0 data length (Tested manually by hardcoding data="" in API)
# def test_iot_socket_send_to_over_udp_socket_with_invalid_data_len(wifi_networked_dut):
#     wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
#     wifi_networked_dut.interfaces.wifi.iotSocketSendTo(socket=0, data="", ip=REMOTE_IP, ip_len=4, port=REMOTE_PORT,
#                                                        expected_status=IOTStatus.IOT_SOCKET_EINVAL)
#     wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceive after iotSocketAccept with valid parameters
def test_iot_socket_receive_after_accept_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketReceive(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceive after iotSocketAccept with invalid socket id
def test_iot_socket_receive_after_accept_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketReceive(socket=10, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceive before iotSocketAccept
def test_iot_socket_receive_before_accept(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketReceive(socket=0, expected_status=IOTStatus.IOT_SOCKET_ENOTCONN)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp after iotSocketAccept with valid parameters
def test_iot_socket_receive_from_after_accept_with_valid_parameters(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp after iotSocketAccept with invalid socket id
def test_iot_socket_receive_from_after_accept_with_invalid_socket_id(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketAccept(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=10, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=1)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom over tcp before iotSocketAccept
def test_iot_socket_receive_from_before_accept(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="stream", protocol="tcp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketListen(socket=0, backlog=1)
    wifi_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=0, expected_status=IOTStatus.IOT_SOCKET_ENOTCONN)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom after creating udp socket with valid parameters
def test_iot_socket_receive_from_with_valid_parameters_over_udp_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=0)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)


# Test iotSocketReceiveFrom after creating udp socket with invalid socket id
def test_iot_socket_receive_from_with_invalid_socket_id_over_udp_socket(wifi_networked_dut):
    wifi_networked_dut.interfaces.wifi.iotSocketCreate(type="dgram", protocol="udp", address_family="ipv4")
    wifi_networked_dut.interfaces.wifi.iotSocketBind(socket=0, ip=LOCAL_IP, port=LOCAL_PORT, ip_len=4)
    wifi_networked_dut.interfaces.wifi.iotSocketReceiveFrom(socket=10, expected_status=IOTStatus.IOT_SOCKET_ESOCK)
    wifi_networked_dut.interfaces.wifi.iotSocketClose(socket=0)
