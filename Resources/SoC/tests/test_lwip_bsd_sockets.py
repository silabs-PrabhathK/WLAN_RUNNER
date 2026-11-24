import time

import pytest
import string
import random
from sl_status import SLStatus
from iot_errors import IOTStatus
from lwip_errors import LwipBSDErrnoStatus

IP_ADDR: str = "192.168.0.100"
DST_IP_ADDR = "192.168.0.101"
random_invalid_socket_id = random.randint(20, 30)


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


def test_lwip_tcp_and_udp_socket_with_valid_input(lwip_networked_dut):
    domain, types, proto = ["AF_INET", "AF_INET6"], ["SOCK_STREAM", "SOCK_DGRAM"], ["IPPROTO_TCP", "IPPROTO_UDP"]
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.socket(domain=domain[i % 2], type=types[1 if (i % 3) else 0],
                                                  protocol=proto[1 if i % 3 else 0], timeout=15)
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}', timeout=15)


# def test_lwip_tcp_and_udp_socket_with_invalid_input(lwip_networked_dut):
#     # invalid arguments
#     for i in range(0, 3):
#         lwip_networked_dut.interfaces.wifi.socket(domain=(22 if (i == 0) else 2), type=(23 if (i == 1) else 2),
#                                         protocol=(24 if (i == 2) else 6), expected_status=LwipBSDErrnoStatus.EINVAL,
#                                         timeout=15)
#     # TCP -DGRAM and UDP-STREAM
#     for i in range(0, 2):
#         lwip_networked_dut.interfaces.wifi.socket(domain=2, type=(2 if (i == 0) else 1),
#                                                   protocol=(6 if (i == 0) else 17),
#                                                   expected_status=LwipBSDErrnoStatus.EPROTOTYPE, timeout=15)


# @pytest.mark.start_state('wifi_dut', wifi='deinit')
# def test_lwip_socket_without_prerequisites(wifi_dut):
#     for i in range(0, 3):
#         if i == 0:
#             wifi_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP",
#                                             expected_status=LwipBSDErrnoStatus.SI91X_BSD_UNDEFINED_ERROR, timeout=20)
#         elif i == 1:
#             wifi_dut.interfaces.wifi.init('client')
#             wifi_dut.interfaces.wifi.socket(domain="AF_INET6", type="SOCK_STREAM", protocol="IPPROTO_TCP",
#                                             expected_status=LwipBSDErrnoStatus.SI91X_BSD_UNDEFINED_ERROR, timeout=15)
#             wifi_dut.interfaces.wifi.deinit()
#         elif i == 2:
#             wifi_dut.interfaces.wifi.init('client')
#             wifi_dut.interfaces.wifi.join()
#             wifi_dut.interfaces.wifi.socket(domain="AF_INET6", type="SOCK_STREAM", protocol="IPPROTO_TCP",
#                                             expected_status=LwipBSDErrnoStatus.SI91X_BSD_UNDEFINED_ERROR, timeout=15)
#             wifi_dut.interfaces.wifi.deinit()


def test_lwip_create_more_sockets_than_limit(lwip_networked_dut):
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP",
                                                  timeout=15)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP",
                                              expected_status=LwipBSDErrnoStatus.ENOBUFS, timeout=15)
    for i in range(0, 4):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}', timeout=15)


def test_lwip_bind_with_valid_parameters(lwip_networked_dut):
    types, proto = ["SOCK_STREAM", "SOCK_DGRAM"], ["IPPROTO_TCP", "IPPROTO_UDP"]
    for i in range(0, 2):
        lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type=types[i], protocol=proto[i], timeout=15)
        lwip_networked_dut.interfaces.wifi.bind(socket_fd=i, ip_addr=IP_ADDR, ip_len=16, port=5656 + i, timeout=15)
    for i in range(0, 2):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}', timeout=15)


def test_lwip_bind_with_invalid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=0, port=5656,
                                            expected_status=LwipBSDErrnoStatus.EBADF, timeout=15)


def test_lwip_bind_on_tcp_client_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656,
                                            expected_status=LwipBSDErrnoStatus.EBADF, timeout=15)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bind_with_invalid_values(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP", timeout=15)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656, timeout=15)
    # call bind twice on same socket id
    # lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656,
    #                                         expected_status=LwipBSDErrnoStatus.EBADF, timeout=15)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP", timeout=15)
    # call bind on already used port
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=1, ip_addr=IP_ADDR, ip_len=16, port=5656,
                                            expected_status=LwipBSDErrnoStatus.EADDRINUSE, timeout=15)
    # send IPV4 to bind if socket is created with IPV6 and vice-versa
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET6", type="SOCK_STREAM", protocol="IPPROTO_TCP", timeout=15)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=2, ip_addr=IP_ADDR, ip_len=16, port=5657,
                                            expected_status=LwipBSDErrnoStatus.EINVAL, timeout=15)
    for i in range(0, 3):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}', timeout=15)


def test_lwip_listen_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP", timeout=15)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656, timeout=15)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1, timeout=15)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0, timeout=15)


def test_lwip_listen_with_invalid_parameters(lwip_networked_dut):
    # call listen without socket
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1, expected_status=LwipBSDErrnoStatus.EBADF,
                                              timeout=15)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP", timeout=15)
    # call listen without bind
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1, timeout=15)
    # call listen twice
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1, timeout=15)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP", timeout=15)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=1, ip_addr=IP_ADDR, ip_len=16, port=5656, timeout=15)
    # call listen on UDP socket
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=1, backlog=1, expected_status=LwipBSDErrnoStatus.EOPNOTSUPP,
                                              timeout=15)
    # Try backlog value as MAX(256)
    # lwip_networked_dut.interfaces.wifi.socket(domain='2', type='1', protocol='6')
    # lwip_networked_dut.interfaces.wifi.bind(socket_fd='0', ip_addr=IP_ADDR, ip_len='4', port='5656')
    # lwip_networked_dut.interfaces.wifi.listen(socket_fd='0', backlog='256')
    for i in range(0, 2):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}', timeout=15)


def test_lwip_listen_on_tcp_client_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1, expected_status=LwipBSDErrnoStatus.EBADF,
                                              timeout=15)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_accept_with_valid_arguments(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_accept_with_invalid_arguments(lwip_networked_dut):
    # call accept with invalid socket fd
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=1, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    # call accept without calling listen
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0, expected_status=LwipBSDErrnoStatus.EINVAL)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    # call listen and accept for new peer
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=1, ip_addr=IP_ADDR, ip_len=16, port=5657)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=1, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=1)
    # call accept on udp socket
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=3, ip_addr=IP_ADDR, ip_len=16, port=5658)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=3, backlog=1, expected_status=LwipBSDErrnoStatus.EOPNOTSUPP)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=3, expected_status=LwipBSDErrnoStatus.EOPNOTSUPP)
    for i in range(0, 3):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{2 - i}')


def test_lwip_accept_on_tcp_client_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0, expected_status=LwipBSDErrnoStatus.EINVAL)


def test_lwip_socket_getsockname_with_valid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketGetSockName(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_socket_getsockname_with_invalid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    # call getsockname after scocket
    lwip_networked_dut.interfaces.wifi.bsdSocketGetSockName(socket_fd=0, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    # test with invalid socket_fd
    lwip_networked_dut.interfaces.wifi.bsdSocketGetSockName(socket_fd=1, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_socket_getpeername_with_valid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketGetPeerName(socket_fd=1)
    for i in range(0, 2):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=f'{i}')


def test_lwip_socket_getpeername_with_invalid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=16, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    # Call getPeername on unconnected TCP/UDP socket.
    lwip_networked_dut.interfaces.wifi.bsdSocketGetPeerName(socket_fd=0, expected_status=LwipBSDErrnoStatus.ENOTCONN)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    # call bsdSocketGerPeerName on non invalid socket
    lwip_networked_dut.interfaces.wifi.bsdSocketGetPeerName(socket_fd=2, expected_status=LwipBSDErrnoStatus.EBADF)
    time.sleep(5)
    # Terminate remote
    lwip_networked_dut.interfaces.wifi.bsdSocketGetPeerName(socket_fd=1,
                                                            expected_status=LwipBSDErrnoStatus.ECONNABORTED)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_socket_getsockopt_with_valid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdGetSocketOpt(socket_fd=0, option_name='SO_KEEPALIVE')
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_socket_getsockopt_with_invalid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.bsdGetSocketOpt(socket_fd=0, option_name='SO_RCVTIMEO',
                                                       expected_status=LwipBSDErrnoStatus.EBADF)


def test_lwip_socket_getsockopt_with_invalid_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdGetSocketOpt(socket_fd=1, option_name='SO_RCVTIMEO',
                                                       expected_status=LwipBSDErrnoStatus.EBADF)


def test_lwip_socket_setsockopt_with_valid_input(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdGetSocketOpt(socket_fd=0, option_name='SO_KEEPALIVE')
    lwip_networked_dut.interfaces.wifi.bsdSetSocketOpt(socket_fd=0, option_name='SO_KEEPALIVE', option_val='10')
    lwip_networked_dut.interfaces.wifi.bsdGetSocketOpt(socket_fd=0, option_name='SO_KEEPALIVE')
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_socket_setsockopt_with_invalid_input(lwip_networked_dut):
    # test set_sock_opt with invalid socket fd
    lwip_networked_dut.interfaces.wifi.bsdSetSocketOpt(socket_fd=0, option_name='SO_KEEPALIVE', option_val='10',
                                                       expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    # test with invalid option name
    lwip_networked_dut.interfaces.wifi.bsdSetSocketOpt(socket_fd=0, option_name='SO_RCVTIMEO', option_val='10',
                                                       expected_status=LwipBSDErrnoStatus.ENOPROTOOPT)


# def test_lwip_socket_getHostByName(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.bsdGetHostByName(url='google.com')


# def test_lwip_socket_getHostByName_with_invalid_values(lwip_networked_dut):
#     lwip_networked_dut.interfaces.wifi.bsdGetHostByName(url='dfjlgsgfdl.com',
#                                                         expected_status=LwipBSDErrnoStatus.HOST_NOT_FOUND)
#     lwip_networked_dut.interfaces.wifi.bsdGetHostByName(
#         url='qwertyuiopasdfghjklzxcvbnmqwertyuiopasdfghjklxcvbnmdfghrtyuvbndfghjertyucvbndfghjrtyuivbnbdfgh.com',
#         expected_status=LwipBSDErrnoStatus.TRY_AGAIN)


def test_lwip_socket_select_with_valid_inputs(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketSelect(numberOfFds=2, time=10)
    for i in range(1, -1, -1):
        lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=i)


def test_lwip_socket_select_with_invalid_iputs(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    # negative time value
    lwip_networked_dut.interfaces.wifi.bsdSocketSelect(numberOfFds=1, time=-15,
                                                       expected_status=LwipBSDErrnoStatus.EINVAL)
    # invalid no of fds
    lwip_networked_dut.interfaces.wifi.bsdSocketSelect(numberOfFds=20, time=5,
                                                       expected_status=LwipBSDErrnoStatus.EINVAL)
    # invalid fd
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)
    # lwip_networked_dut.interfaces.wifi.bsdSocketSelect(numberOfFds=1, time=9, expected_status=LwipBSDErrnoStatus.EBADF)


# Test bsdSocketReceive after bsdSocketAccept with valid parameters
def test_lwip_bsd_socket_receive_after_accept_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceive(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceive after bsdSocketAccept with invalid socket id
def test_lwip_bsd_socket_receive_after_accept_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceive(socket_fd=10, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceive before bsdSocketAccept
def test_lwip_bsd_socket_receive_before_accept(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceive(socket_fd=0, expected_status=LwipBSDErrnoStatus.ENOTCONN)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceiveFrom over tcp after bsdSocketAccept with valid parameters
def test_lwip_bsd_socket_receive_from_after_accept_with_valid_parameters(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceiveFrom over tcp after bsdSocketAccept with invalid socket id
def test_lwip_bsd_socket_receive_from_after_accept_with_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketAccept(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=10, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=1)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceiveFrom over tcp before bsdSocketAccept
def test_lwip_bsd_socket_receive_from_before_accept(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.listen(socket_fd=0, backlog=1)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=0, expected_status=LwipBSDErrnoStatus.ENOTCONN)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceiveFrom after creating udp socket with valid parameters
def test_lwip_bsd_socket_receive_from_with_valid_parameters_over_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Test bsdSocketReceiveFrom after creating udp socket with invalid socket id
def test_lwip_bsd_socket_receive_from_after_invalid_socket_id_over_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=10, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


# Tests for close
# Call to close with valid parameter
# Call to close with invalid parameter Invalid socket
# Call to close twice
def test_lwip_bsd_socket_close(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_close_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=random_invalid_socket_id,
                                                    expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_close_twice(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0, expected_status=LwipBSDErrnoStatus.EBADF)


# Tests for connect
# Call to connect with valid parameter
# Call to connect with invalid parameter invalid socket
# Call to connect and socket is connected already
# Call to connect and connection establishment timeout without establishing connection
# Call to connect on UDP socket after sendto
# Call to connect on UDP socket after recvfrom

def test_lwip_bsd_socket_connect_with_valid_params(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_connect_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=random_invalid_socket_id, ip_addr=DST_IP_ADDR,
                                                        ip_len=4,
                                                        port=5656, expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_connect_on_connected_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656,
                                                        expected_status=LwipBSDErrnoStatus.EISCONN, timeout=20)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_connect_twice_on_disconnected_server(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5657,
                                                        expected_status=LwipBSDErrnoStatus.SI91X_BSD_UNDEFINED_ERROR)
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5657,
                                                        expected_status=LwipBSDErrnoStatus.SI91X_BSD_UNDEFINED_ERROR)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_connect_udp_socket_after_sendto(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bsdSocketSendTo(socket_fd=0, data="Thisisfromclient", ip_addr=IP_ADDR, ip_len=4,
                                                       port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_connect_udp_socket_after_recvfrom(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_call_connect_on_udp_after_receivefrom(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bind(socket_fd=0, ip_addr=IP_ADDR, ip_len=4, port=5656)
    time.sleep(5)
    lwip_networked_dut.interfaces.wifi.bsdSocketReceiveFrom(socket_fd=0)
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)


# Write tests for send and sendTo
# Call to send with valid parameter
# Call to send with invalid parameter invalid socket
# Call sendto with destination address on TCP socket
# Call sendto with destination address on UDP socket and call sendto after socker() API with destination address
# Call to send without connect

def test_lwip_bsd_socket_send(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketSend(socket_fd=0, data="Thisisfromclient")
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_send_invalid_socket_id(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketSend(socket_fd=random_invalid_socket_id, data="Thisisfromclient",
                                                     expected_status=LwipBSDErrnoStatus.EBADF)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_sendto_on_tcp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketConnect(socket_fd=0, ip_addr=DST_IP_ADDR, ip_len=4, port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSocketSendTo(socket_fd=0, data="Thisisfromclient", ip_addr=IP_ADDR, ip_len=4,
                                                       port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_sendto_on_udp_socket(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_DGRAM", protocol="IPPROTO_UDP")
    lwip_networked_dut.interfaces.wifi.bsdSocketSendTo(socket_fd=0, data="ThisisUDP", ip_addr=DST_IP_ADDR, ip_len=4,
                                                       port=5656)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)


def test_lwip_bsd_socket_send_without_socket_connect(lwip_networked_dut):
    lwip_networked_dut.interfaces.wifi.socket(domain="AF_INET", type="SOCK_STREAM", protocol="IPPROTO_TCP")
    lwip_networked_dut.interfaces.wifi.bsdSocketSend(socket_fd=0, data="ThisisTCP",
                                                     expected_status=LwipBSDErrnoStatus.ENOTCONN)
    lwip_networked_dut.interfaces.wifi.bsdSockClose(socket_fd=0)
