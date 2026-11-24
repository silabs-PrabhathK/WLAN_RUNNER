"""Wi-Fi sample-app CLI wrappers (issue_command only).

Maps sample-app automation to the wireless_test console dialect
(wifi_init, wifi_scan, wifi_connect, start_dhcp, …) as defined in
examples/snippets/wireless_test (readme.md + console_command_database.c).

UART dialect (wireless_test / Docklight-style, without Docklight timestamps):
  TX:  <command>\\n
  RX:  <echo>\\r\\n
       [<sync payload lines>]
       0x00000: (<N>ms) Success\\r\\n
       > [Fxxxx<$ <async_id> <async payload>\\n ... $>]

No test-agent thread path — every handler uses issue_command(), and async
frames (Fxxxx<$ … $>) are collected via an RX observer when needed.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections import namedtuple
from typing import List, Optional, Tuple, Union
import re
import threading
import time

from utf.interfaces.wifi import WiFiInterface, WiFiScanResult
from utf.interfaces.network import NetworkInterface
from utf.interfaces.cli import CLITransport, CLITransportException
from utf.utils.defaults import defaults
from utf.utils.commander import reset_device

from utf_wiseconnect_3.tests.sl_status import SLStatus
from utf_wiseconnect_3.tests.interfaces import AsyncIdentifiers


def create_interface(
    config, cli_transport, gpio_transport=None, reset="soft", device=None
) -> WiFiInterface:
    return WifiSampleAppCLI(config, cli_transport, gpio_transport, reset, device)


class _AsyncFrameCollector:
    """Collect one wireless_test async frame: Fxxxx<$ <id> … $>."""

    # F0049<$ 10000000 1 scan results:\n...
    _START_RE = re.compile(
        r"F[0-9a-fA-F]{4}<\$\s+([0-9a-fA-F]{8})\s+(.*)",
        re.DOTALL,
    )

    def __init__(self, async_id: str):
        self.async_id = async_id.lower()
        self._buf = ""
        self._payload = ""
        self._started = False
        self._done = threading.Event()
        self._lock = threading.Lock()

    def on_rx(self, timestamp: int, record: bytes):
        text = record.decode(errors="ignore")
        with self._lock:
            self._buf += text
            if not self._started:
                match = self._START_RE.search(self._buf)
                if not match:
                    return
                if match.group(1).lower() != self.async_id:
                    # Different async event — drop prefix and keep looking.
                    self._buf = self._buf[match.end() :]
                    return
                self._started = True
                rest = match.group(2)
                if "$>" in rest:
                    self._payload = rest.split("$>", 1)[0]
                    self._done.set()
                else:
                    self._payload = rest
                return
            if "$>" in text:
                self._payload += text.split("$>", 1)[0]
                self._done.set()
            else:
                self._payload += text

    def wait(self, timeout_sec: float) -> bool:
        return self._done.wait(timeout_sec)

    @property
    def payload(self) -> str:
        with self._lock:
            return self._payload


class WifiSampleAppCLI(WiFiInterface, NetworkInterface):
    """Minimal Wi-Fi CLI for sample-app automation (no thread helpers)."""

    ScanResult = namedtuple(
        "ScanResult", "rf_channel security_mode rssi network_type ssid bssid"
    )
    mac_address_expression = re.compile(
        r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}"
    )
    # Sync status line: 0x00000: (1533ms) Success  (duration optional)
    _STATUS_RE = re.compile(
        r".*\n0x([0-9a-fA-F]+):\s*(?:\(([^)]*)\))?\s*([^\r\n]*)\r?\n",
        flags=re.DOTALL | re.ASCII,
    )

    def __init__(
        self,
        config: dict,
        cli_transport: Union[str, CLITransport],
        gpio_transport: Union[str, CLITransport] = None,
        reset: str = None,
        device=None,
    ):
        super().__init__(config)
        if isinstance(cli_transport, str):
            self.bus: CLITransport = device.create_interface(cli_transport)
        else:
            self.bus = cli_transport
        self.bus.register_rx_data_observer(self.on_incoming_rx_data, override=False)
        self._lock = threading.RLock()
        self.inited = False
        self.associated = False
        self.networked = False
        self.ap_beaconing = False
        self.power_save_mode = "high_performance"
        self.wifi_cli_mode = None
        self.ip = None
        self.device_commander_options = config.get("commander_options", None)
        if gpio_transport and device is not None:
            self.gpio_bus = device.create_interface(gpio_transport)
        else:
            self.gpio_bus = None

    def on_incoming_rx_data(self, timestamp: int, record: bytes):
        self.logger.debug(f"Got data: {record.decode(errors='ignore')}")

    def _commander_reset(self):
        """Hard-reset the DUT via Simplicity Commander (same as SLWifiCLI)."""
        self.logger.warning("Reset the DUT through commander reset")
        reset_device(self.device_commander_options)
        time.sleep(5)

    def release_resources(self):
        """Close UART/GPIO CLI transports."""
        self.bus.release_resources()
        if self.gpio_bus is not None:
            self.gpio_bus.release_resources()

    def reset(self):
        """
        Reset DUT state and reboot via commander.

        Used by sl_collections.exception_handling() and harness teardown.
        """
        self.inited = False
        self.associated = False
        self.networked = False
        self.ap_beaconing = False
        self.power_save_mode = "high_performance"
        self.wifi_cli_mode = None
        self.ip = None
        self._commander_reset()

    @contextmanager
    def _subscribe_to_rx(self, callback):
        identifier = None
        try:
            identifier = self.bus.register_rx_data_observer(callback, override=False)
            yield identifier
        finally:
            if identifier is not None:
                self.bus.un_register_rx_data_observer(identifier)

    def issue_command(
        self, line: str, timeout: int = 10, retries: int = 0, ignore_response=0
    ) -> Tuple[SLStatus, bytes]:
        """
        Send a CLI command and wait for the sync status line.

        Matches wireless_test RX:
          <echo>
          [<payload>]
          0x00000: (<N>ms) Success
          >
        """
        retries += 1
        while True:
            try:
                with self._lock:
                    result = self.bus.write_line_and_expect(
                        line, self._STATUS_RE, timeout
                    )
                    if ignore_response:
                        return SLStatus.SL_STATUS_OK, b""
                    if result is None:
                        return SLStatus.SL_STATUS_TIMEOUT, b""
                    text = result.decode(errors="ignore")
                    result_match = self._STATUS_RE.search(text)
                    if result_match:
                        status = SLStatus(int(result_match.group(1), 16))
                        return status, result
                    return -1, result
            except CLITransportException as e:
                self.logger.warning(e.actual_response)
                raise e

    def issue_command_with_async(
        self,
        line: str,
        async_id: str,
        timeout: int = 10,
        async_timeout: int = 60,
        retries: int = 0,
    ) -> Tuple[SLStatus, bytes]:
        """
        Issue a sync CLI command, then wait for an async frame:

          Fxxxx<$ <async_id> <payload>
          $>
        """
        collector = _AsyncFrameCollector(async_id)
        with self._subscribe_to_rx(collector.on_rx):
            status, sync_data = self.issue_command(
                line, timeout=timeout, retries=retries
            )
            if status == SLStatus.SL_STATUS_OK:
                if not collector.wait(async_timeout):
                    self.logger.warning(
                        f"Async frame {async_id} not received within "
                        f"{async_timeout}s; sync data only"
                    )
                    return status, sync_data
                async_bytes = collector.payload.encode("utf-8", errors="replace")
                return status, sync_data + b"\n" + async_bytes
            return status, sync_data

    def get_command_data(self, response: bytes) -> Optional[bytes]:
        """
        Extract sync payload between command echo and status line.

        Example (start_dhcp -i ipv4 -m dhcp, current wireless_test):
          start_dhcp -i ipv4 -m dhcp\\r\\n
          IP Address: 192.168.50.164 Gateway: 192.168.50.1 Netmask: 255.255.255.0\\r\\n
          0x00000: (4128ms) Success\\r\\n
        """
        if not response:
            return None
        text = response.decode(errors="ignore")
        status_match = re.search(
            r"0x[0-9a-fA-F]+:\s*\([^)]*\)\s*[^\r\n]*", text
        ) or re.search(r"0x[0-9a-fA-F]+:", text)
        if not status_match:
            return None
        payload = text[: status_match.start()]
        # Drop echoed command (first line).
        parts = re.split(r"\r?\n", payload, maxsplit=1)
        if len(parts) > 1:
            payload = parts[1]
        else:
            payload = ""
        payload = payload.strip("\r\n ")
        return payload.encode("utf-8", errors="replace") if payload else None

    def verify_status(self, status, expected_status, data=None):
        if isinstance(expected_status, list):
            assert status in expected_status, (
                f"expected status should be one of ->{expected_status}, "
                f"but received "
                f"{SLStatus(status).name if status in list(SLStatus) else status}"
            )
            return
        if type(expected_status) == SLStatus:
            if (
                expected_status is not None
                and expected_status != SLStatus.SL_STATUS_IGNORE_RESULT
            ):
                assert status == expected_status, (
                    f"{SLStatus(status).name if status in list(SLStatus) else status} "
                    f"!= {SLStatus(expected_status).name}, status:{hex(status)}"
                )

    # Table row from current wireless_test (SSID not comma-separated):
    #   1000_ZEPHYR_1_ASUS          2,     1,   cc:28:aa:67:38:78,   10,  -23
    _SCAN_TABLE_ROW_RE = re.compile(
        rb"^(.+?)\s+(\d+)\s*,\s*(\d+)\s*,\s*"
        rb"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s*,\s*"
        rb"(\d+)\s*,\s*(-?\d+)\s*$"
    )

    @classmethod
    def _parse_scan_csv_lines(cls, data: bytes) -> List[WiFiScanResult]:
        """
        Parse wireless_test scan rows from sync or async payload.

        Current console (Docklight / wireless_test.txt):
          1 scan results:
             SSID                 SECURITY NETWORK       BSSID      CHANNEL RSSI
          1000_ZEPHYR_1_ASUS          2,     1,   cc:28:aa:67:38:78,   10,  -23
          End

        Legacy CSV (ssid as first comma field):
          1000_ZEPHYR_1,2,1,ca:e9:f3:94:e6:4b,11,-47
        """
        result = []
        for raw in data.splitlines():
            line = raw.strip()
            if not line or b"," not in line:
                continue
            lower = line.lower()
            if b"scan results" in lower or lower.startswith(b"ssid"):
                continue
            if lower in (b"end", b"scanning..."):
                continue

            table_match = cls._SCAN_TABLE_ROW_RE.match(line)
            if table_match:
                try:
                    ssid = table_match.group(1).strip()
                    security_mode = int(table_match.group(2))
                    network_type = int(table_match.group(3))
                    bssid = table_match.group(4).decode("ascii", errors="ignore")
                    channel = int(table_match.group(5))
                    rssi = int(table_match.group(6))
                except (ValueError, UnicodeError):
                    continue
                sr = cls.ScanResult(
                    channel, security_mode, rssi, network_type, ssid, bssid
                )
                result.append(WiFiScanResult(**sr._asdict()))
                continue

            tokens = line.split(b",")
            if len(tokens) != 6:
                continue
            try:
                ssid = tokens[0].strip()
                security_mode = int(tokens[1].strip())
                network_type = int(tokens[2].strip())
                bssid = tokens[3].strip().decode("ascii", errors="ignore")
                channel = int(tokens[4].strip())
                rssi = int(tokens[5].strip())
            except (ValueError, UnicodeError):
                continue
            sr = cls.ScanResult(
                channel, security_mode, rssi, network_type, ssid, bssid
            )
            result.append(WiFiScanResult(**sr._asdict()))
        return result

    # ------------------------------------------------------------------
    # Commands → wireless_test wifi_ / start_dhcp console dialect
    # ------------------------------------------------------------------

    def init(
        self,
        mode: str = None,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_init [-i <mode>]"""
        self.wifi_cli_mode = mode
        line = f'wifi_init{f" -i {mode}" if mode is not None else ""}'
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        if status == SLStatus.SL_STATUS_OK:
            self.inited = True
        self.verify_status(status, expected_status)
        return status

    def scan(
        self,
        ssid: str = None,
        interface: str = None,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 60,
        async_timeout: int = 60,
    ) -> List[WiFiScanResult]:
        """
        wifi_scan [-s <ssid>] [-i <interface>]

        Current wireless_test prints scan rows in the sync response (before
        ``0x00000: … Success`` / ``End``). Older builds may still deliver rows
        in async ``Fxxxx<$ 10000000 … $>`` — fall back to that if sync has none.
        """
        line = (
            f"wifi_scan"
            f'{f" -s {ssid}" if ssid else ""}'
            f'{f" -i {interface}" if interface else ""}'
        )
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.logger.info(f"Scan Command Response {data!r}")
        result = self._parse_scan_csv_lines(data)
        if not result and status == SLStatus.SL_STATUS_OK:
            self.logger.info(
                "No sync scan rows; waiting for async SCAN_RESULTS frame"
            )
            collector = _AsyncFrameCollector(AsyncIdentifiers.SCAN_RESULTS)
            with self._subscribe_to_rx(collector.on_rx):
                if collector.wait(async_timeout):
                    async_bytes = collector.payload.encode(
                        "utf-8", errors="replace"
                    )
                    data = data + b"\n" + async_bytes
                    result = self._parse_scan_csv_lines(data)
                else:
                    self.logger.warning(
                        f"Async SCAN_RESULTS not received within {async_timeout}s"
                    )
        self.logger.info(f"Scan Results: {result}")
        return result

    @defaults("wifi")
    def join(
        self,
        ssid: str,
        passphrase: str,
        security: str = "wpa2",
        interface: str = "client",
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 30,
        async_timeout: int = 90,
        retries: int = 3,
    ):
        """
        wifi_connect <ssid> -p <passphrase> -s <security> [-i <interface>]

        Current wireless_test prints join progress sync (Credentials set /
        Connecting / Join Event) then ``0x00000: … Success``. Retries on
        transient failures. Async JOIN_EVENT is optional fallback only.
        """
        _ = async_timeout  # kept for API compatibility with older callers
        line = (
            f"wifi_connect {ssid} -p {passphrase} -s {security}"
            f"{f' -i {interface}' if interface else ''}"
        )
        status, data = SLStatus.SL_STATUS_FAIL, b""
        for attempt in range(1, retries + 1):
            self.logger.info(f"CLI >>> {line} (attempt {attempt}/{retries})")
            status, data = self.issue_command(line, timeout=timeout)
            if status == SLStatus.SL_STATUS_OK:
                break
            self.logger.warning(
                f"Join attempt {attempt} failed: "
                f"status={hex(status) if isinstance(status, int) else status}"
            )
            time.sleep(1)
        if status == SLStatus.SL_STATUS_OK:
            self.associated = True
        self.verify_status(status, expected_status)
        return status, data

    def deinit(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        """wifi_deinit"""
        line = "wifi_deinit"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.inited = False
        self.associated = False
        self.networked = False
        self.verify_status(status, expected_status)
        return status

    @defaults("wifi")
    def leave(
        self,
        interface: str = "client",
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 5,
    ):
        """wifi_disconnect [-i <interface>]"""
        line = f"wifi_disconnect -i {interface}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.associated = False
        self.networked = False
        self.verify_status(status, expected_status)
        return status

    def start_ap(
        self,
        ssid: str = None,
        security: str = "wpa2",
        encryption: str = "ccmp",
        channel: int = None,
        max_clients: int = 4,
        beacon_interval: int = 100,
        psk: str = None,
        dtim_beacon_count: int = None,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 30,
    ):
        """
        wifi_start_ap (wireless_test SoftAP PSK is firmware SOFT_AP_PSK).

        Example:
          wifi_start_ap -a SILABS_AP -b wpa2 -c ccmp -d 9 -l 4 -n 100

        The CLI does not accept a passphrase argument; the sample uses
        MY_AP_PASSPHRASE from wifi_commands.c. Third-party STAs must use
        the same PSK when joining.
        """
        if security is not None:
            security = security.lower()
        # psk is kept for API compatibility; wireless_test uses built-in SOFT_AP_PSK.
        if psk and psk != "MY_AP_PASSPHRASE":
            self.logger.warning(
                "wifi_start_ap ignores psk on CLI; firmware uses MY_AP_PASSPHRASE"
            )
        _ = psk
        line = (
            f"wifi_start_ap"
            f"{f' -a {ssid}' if ssid else ''}"
            f"{f' -b {security}' if security else ''}"
            f"{f' -c {encryption}' if encryption else ''}"
            f"{f' -d {channel}' if channel is not None else ''}"
            f"{f' -k {dtim_beacon_count}' if dtim_beacon_count is not None else ''}"
            f"{f' -l {max_clients}' if max_clients is not None else ''}"
            f"{f' -n {beacon_interval}' if beacon_interval is not None else ''}"
        )
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.ap_beaconing = True
        return status, data

    def stop_ap(self):
        """SoftAP teardown — wireless_test has no stop_ap CLI; commander reset."""
        self.logger.info("stop_ap: resetting DUT (no dedicated stop_ap CLI)")
        self.ap_beaconing = False
        self.reset()

    def get_client_info(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        """wifi_get_client_info"""
        line = "wifi_get_client_info"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def get_fw_version(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        """wifi_get_fw_version"""
        line = "wifi_get_fw_version"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        payload = self.get_command_data(data)
        if payload is None:
            fw_match = re.search(rb"Firmware version is:\s*(.+?)\s*(?:[\r\n]|0x)", data)
            if fw_match:
                return fw_match.group(1).decode().strip()
            raise RuntimeError(f"Could not parse firmware version from: {data!r}")
        text = payload.replace(b"\r\n", b"").replace(b"\r", b"").decode()
        if "Firmware version is:" in text:
            return text.split("Firmware version is:")[1].strip()
        return text.strip()

    def get_mac_address(
        self,
        interface: int = 1,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_get_mac_address [-i <interface>]"""
        line = f"wifi_get_mac_address -i {interface}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        text = data.decode(errors="ignore")
        mac_match = self.mac_address_expression.search(text)
        if mac_match:
            return mac_match.group(0)
        payload = self.get_command_data(data)
        if payload:
            return payload.decode(errors="ignore").strip()
        return text.strip()

    def set_performance_profile(
        self,
        mode: str = "high_performance",
        dtim_aligned_type: int = 0,
        num_of_dtim_skip: int = 0,
        listen_interval: int = 0,
        monitor_interval: int = 0,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 5,
    ):
        """wifi_set_performance_profile <mode> (extra args kept for API compatibility)."""
        if mode == "standby_power_save":
            mode = "deep_sleep_without_ram_retention"
        if mode == "standby_power_save_with_ram_retention":
            mode = "deep_sleep_with_ram_retention"
        _ = (dtim_aligned_type, num_of_dtim_skip, listen_interval, monitor_interval)
        line = f"wifi_set_performance_profile {mode}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.power_save_mode = mode
        self.verify_status(status, expected_status)
        return status

    def get_statistics(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        """wifi_get_statistics"""
        line = "wifi_get_statistics"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def get_performance_profile(
        self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10
    ):
        """wifi_get_performance_profile"""
        line = "wifi_get_performance_profile"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status != SLStatus.SL_STATUS_OK:
            return None
        match = re.search(r"Performance Mode: (.*)", data.decode(errors="ignore"))
        return match.group(1).lower() if match else None

    def dns_get(
        self,
        domain_name: str = "www.google.com",
        query_timeout: int = 20,
        ip_version: str = "ipv4",
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """sl_net_dns_resolve_hostname <host> [-t <timeout>] [-i <ip_type>]"""
        line = (
            f"sl_net_dns_resolve_hostname {domain_name}"
            f" -t {query_timeout} -i {ip_version}"
        )
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        result = self.get_command_data(data)
        return result.strip() if result else None

    def iotSocketCreate(
        self,
        stream_type: str,
        protocol: str,
        address_family: str = "ipv4",
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_iot_socket_create <type> <proto> [-j <family>]"""
        line = f"wifi_iot_socket_create {stream_type} {protocol} -j {address_family}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        payload = self.get_command_data(data) or data
        socket_id = payload.decode(errors="ignore").replace("\n", "").strip()
        return int(socket_id)

    def iotSocketConnect(
        self,
        socket: int,
        server_ip: str,
        port: int,
        ip_len: int = 4,
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_iot_socket_connect <sock> <ip> <port> [-l <ip_len>]"""
        line = f"wifi_iot_socket_connect {socket} {server_ip} {port} -l {ip_len}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        return data

    def iotSocketBind(
        self,
        socket: int,
        client_ip: str,
        port: int,
        ip_len: int = 4,
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_iot_socket_bind <sock> <ip> <port> [-l <ip_len>]"""
        line = f"wifi_iot_socket_bind {socket} {client_ip} {port} -l {ip_len}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        return status

    def iotSocketReceiveFrom(
        self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
    ):
        """wifi_iot_socket_receive_from <sock>"""
        line = f"wifi_iot_socket_receive_from {socket}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        return data

    def iotSocketListen(
        self,
        socket: int,
        backlog: int = 1,
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_iot_socket_listen <sock> <backlog>"""
        line = f"wifi_iot_socket_listen {socket} {backlog}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        return status

    def iotSocketAccept(
        self,
        socket: int,
        port: int = 0,
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 5,
    ):
        """wifi_iot_socket_accept <sock> (port kept for API compatibility)."""
        _ = port
        line = f"wifi_iot_socket_accept {socket}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        payload = self.get_command_data(data) or data
        return payload.decode(errors="ignore").strip()

    def iotSocketSend(
        self,
        socket: int,
        data: str,
        expected_status=SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """wifi_iot_socket_send <sock> <data>"""
        line = f"wifi_iot_socket_send {socket} {data}"
        self.logger.info(f"CLI >>> {line}")
        status, response = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, response)
        return status

    def start_ip(
        self,
        static_ip: str = None,
        ip_version: str = "ipv4",
        static_subnet: str = None,
        static_gateway: str = None,
        vid: int = None,
        static_ipv6_address: str = None,
        ipv6_gw_address: str = None,
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 30,
    ):
        """
        Acquire IP via start_dhcp (wireless_test).

        DHCP (default), current wireless_test:
          TX: start_dhcp -i ipv4 -m dhcp
          RX: IP Address: <ip> Gateway: <gw> Netmask: <netmask>
              0x00000: (<N>ms) Success

        Legacy CSV also accepted: <ip>, <netmask>, <gateway>

        Static IPv4:
          start_dhcp -i ipv4 -m static -a <ip> -g <gw> -n <netmask>

        In wireless_test AP-only mode, start_dhcp uses the client VAP in the
        sample app and returns 0x10021 — use wifi_start_ap without a prior
        start_dhcp for SoftAP; ping the DUT using the STA default gateway
        after the client receives DHCP.
        """
        _ = vid  # not used by wireless_test start_dhcp
        if getattr(self, "wifi_cli_mode", None) == "ap" and static_ip:
            self.logger.warning(
                "Skipping start_dhcp static in AP-only mode (sample uses "
                "client VAP; would return 0x10021). Start SoftAP with "
                "wifi_start_ap and use client gateway for ping."
            )
            return None
        if not [x for x in (static_ip, static_subnet, static_gateway) if x is None]:
            line = (
                f"start_dhcp -i {ip_version} -m static"
                f" -a {static_ip} -g {static_gateway} -n {static_subnet}"
            )
        elif not [x for x in (static_ipv6_address, ipv6_gw_address) if x is None]:
            line = (
                f"start_dhcp -i {ip_version} -m static"
                f" -a {static_ipv6_address} -g {ipv6_gw_address}"
            )
        else:
            line = f"start_dhcp -i {ip_version} -m dhcp"

        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status != SLStatus.SL_STATUS_OK:
            return None

        self.networked = True
        ip_info = self.get_command_data(data) or data
        if ip_version == "ipv4":
            labeled = re.search(
                rb"IP Address:\s*(\d{1,3}(?:\.\d{1,3}){3}).*?"
                rb"Gateway:\s*(\d{1,3}(?:\.\d{1,3}){3}).*?"
                rb"Netmask:\s*(\d{1,3}(?:\.\d{1,3}){3})",
                ip_info,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if labeled:
                ip, gateway, netmask = (
                    labeled.group(1),
                    labeled.group(2),
                    labeled.group(3),
                )
            else:
                matches = re.findall(
                    rb"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info
                )
                assert len(matches) == 3, (
                    "Error parsing IP / gateway / netmask from "
                    f"{ip_info!r}"
                )
                # Legacy CSV order: ip, netmask, gateway
                ip, netmask, gateway = [m.strip() for m in matches]
            self.ip = self.IPConfig(ip=ip, netmask=netmask, gateway=gateway)
            self.logger.info(f"Configured IP: {self.ip}")
            return self.ip

        parts = [p.strip().decode() for p in ip_info.split(b",")]
        assert len(parts) >= 3, f"Error parsing IPv6 addresses from {ip_info!r}"
        return parts[0], parts[1], parts[2]

    def get_ip_address(self, network_interface=None) -> str:
        assert self.ip is not None, "IP not configured; call start_ip() first"
        ip = self.ip.ip
        return ip.decode() if isinstance(ip, (bytes, bytearray)) else str(ip)

    def get_device_ip(self, device_ip) -> str:
        """Return DUT IPv4 string from start_ip() IPConfig (same as SLWifiCLI)."""
        self.logger.debug(f"device_ip.ip from dut {device_ip.ip}")
        ip = device_ip.ip
        return ip.decode() if isinstance(ip, (bytes, bytearray)) else str(ip)

    def dhcp_start(
        self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 15
    ):
        """
        Prefer start_ip() / start_dhcp -i ipv4 -m dhcp on wireless_test.

        Kept for API compatibility; delegates to start_ip and returns the IP string.
        """
        self.logger.info("dhcp_start: using start_dhcp -i ipv4 -m dhcp")
        ip_cfg = self.start_ip(expected_status=expected_status, timeout=timeout)
        if ip_cfg is None:
            return None
        return self.get_device_ip(ip_cfg)

    def set_wifi_region(
        self,
        region_code: str = "us",
        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
        timeout: int = 10,
    ):
        """set_region_configuration <region_code>"""
        line = f"set_region_configuration {region_code}"
        self.logger.info(f"CLI >>> {line}")
        status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        return status
