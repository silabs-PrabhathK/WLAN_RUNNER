import pytest
import threading
import time
import socket
from sl_status import SLStatus
from utf.interfaces.socket.fixtures import socket_server

socket_transfer_data = 'x' * 32


class ThreadWithReturnValue(threading.Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, Verbose=None):
        threading.Thread.__init__(self, group, target, name, args, kwargs)
        self._return = None

    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args,
                                        **self._kwargs)

    def join(self, *args):
        threading.Thread.join(self, *args)
        return self._return


def socket_transfer(dut_socket, server_socket, direction, duration=10):
    end_time = time.time() + duration
    while time.time() < end_time:
        if direction == "dut_tx":
            socket.send("1234567890")
        else:
            server_socket.send("1234567890")


def create_socket_connections(dut_wifi, socket_server, socket_count, port, direction="dut_to_server"):
    server_ip = socket_server.interfaces.network.get_ip_address()
    dut_ip = dut_wifi.get_ip_address()
    server_sockets = []
    dut_sockets = []
    dut_listen_sockets = []
    for i in range(socket_count):
        if direction == "dut_to_server":
            # Create accept socket on server
            new_server = socket_server.interfaces.socket.start_server(port=port + i)
            # Create connecting socket on DUT and connect
            new_dut_socket = dut_wifi.socket(domain="AF_INET", stream_type="SOCK_STREAM", protocol="IPPROTO_TCP")
            dut_wifi.bsdSocketConnect(new_dut_socket, server_ip, 4, port+i)
            # Save new sockets
            dut_sockets.append(new_dut_socket)
            server_sockets.append(new_server.accept_socket)
        else:
            # Create accept socket on DUT
            dut_listen_socket = dut_wifi.socket(domain="AF_INET", stream_type="SOCK_STREAM", protocol="IPPROTO_TCP")
            dut_wifi.bind(dut_listen_socket, dut_ip, 4, port+i)
            dut_wifi.listen(dut_listen_socket, backlog=1, asynch=0)
            dut_thread = ThreadWithReturnValue(target=dut_wifi.bsdSocketAccept, args=(dut_listen_socket, None))
            dut_thread.start()
            # Create connecting socket on server and connect
            server_socket = socket_server.interfaces.socket.create_socket(type=socket.SocketKind.SOCK_STREAM)
            server_socket.connect((dut_ip, port+i))
            accept_socket = dut_thread.join()

            # Save new sockets
            accept_socket = accept_socket.splitlines()[1].decode()
            dut_sockets.append(accept_socket)
            dut_listen_sockets.append(dut_listen_socket)
            server_sockets.append(server_socket)

    return server_sockets, dut_sockets, dut_listen_sockets

# Test multiple sockets with multiple threads
@pytest.mark.parametrize("socket_count", [5])
@pytest.mark.parametrize("powersave", [ None, "power_save",  "power_save_low_latency"])
@pytest.mark.parametrize("transfer_direction", ["dut_tx", "dut_rx"])
@pytest.mark.skip()
def test_multiple_socket_multiple_threads(wifi_networked_dut, socket_server, socket_count, powersave, transfer_direction):
    dut_wifi = wifi_networked_dut.interfaces.wifi
    dut_sockets = []
    server_sockets = []
    
    if powersave:
        dut_wifi.set_performance_profile(powersave)
    
    for i in range(socket_count):
        dut_wifi.socket(domain="AF_INET", stream_type="stream", protocol="tcp")

    for i in dut_sockets:
        f"t {i} bsd_socket.send {i} {socket_transfer_data}"

# Test multiple sockets on single thread
@pytest.mark.parametrize("socket_count", [5])
@pytest.mark.parametrize("powersave", [ None, "power_save"])
@pytest.mark.parametrize("transfer_direction", ["dut_tx", "dut_rx"])
@pytest.mark.parametrize("connection_direction", ["dut_to_server", "server_to_dut"])
def test_multiple_sockets(wifi_networked_dut, socket_server, socket_count, powersave, transfer_direction, connection_direction):
    dut_wifi = wifi_networked_dut.interfaces.wifi
    port = 5001
    
    if powersave:
        dut_wifi.set_performance_profile(powersave)

    server_sockets, dut_sockets, dut_server_socket = create_socket_connections(dut_wifi, socket_server, socket_count, port, connection_direction)
        
    end_time = time.time() + 10
    while time.time() < end_time:
        for i in range(socket_count):
            if transfer_direction == "dut_tx":
                dut_wifi.bsdSocketSend(dut_sockets[i], socket_transfer_data)
            else:
                server_sockets[i].send(socket_transfer_data.encode())
                dut_wifi.bsdSocketReceive(dut_sockets[i])
    
    for i in dut_sockets:
        dut_wifi.bsdSockClose(i)
    for i in dut_server_socket:
        dut_wifi.bsdSockClose(i)
       
    socket_server.interfaces.socket.cleanup()
        
    if powersave:
        dut_wifi.set_performance_profile()


def test_multiple_iperf(wifi_networked_dut, socket_server):
    dut_wifi = wifi_networked_dut.interfaces.wifi
    socket_server_ip = socket_server.interfaces.network.get_ip_address()
    dut_ip = wifi_networked_dut.interfaces.wifi.get_ip_address()
    dut_wifi.issue_command(f"thread 0 1536 128")
    dut_wifi.issue_command(f"thread 1 1536 128")

    socket_server.interfaces.socket.start_server(port=5001, socket.SOCK_DGRAM)
    socket_server.interfaces.socket.start_server(port=5002, socket.SOCK_DGRAM)

    def iperf(dut, family='2', transfer_type='1', protocol='6', local_port='5001', local_ip=None, remote_ip='',
              remote_port=5001, size=1000, ttl=30, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40,
              throughput_type: int = 1, qos: int = 0, async_socket=0, thread=0):
        line = f"t {thread} iperf {family} {transfer_type} {protocol} {local_port} {local_ip} {remote_ip} {remote_port} {size} {ttl} {throughput_type} {qos} {async_socket}"
        print(line)
        status, data = dut.issue_command(line=line, timeout=timeout)
        expected_status = [SLStatus.SL_STATUS_OK, SLStatus.SL_STATUS_SI91X_SOCKET_TX_OR_RX_FAIL,
                           SLStatus.SL_STATUS_SI91X_TCP_SERVER_SOCKET_CLOSE_FAIL]
        dut.verify_status(status, expected_status)
        dut.logger.info(data.decode())


    iperf(dut_wifi, transfer_type=2, protocol=17, local_port=5001, local_ip=dut_ip, remote_ip=socket_server_ip, remote_port=5001, throughput_type=2, thread=0)
    iperf(dut_wifi, transfer_type=2, protocol=17, local_port=5002, local_ip=dut_ip, remote_ip=socket_server_ip, remote_port=5002, throughput_type=2, thread=1)

    socket_server.cleanup()