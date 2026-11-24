"""SiWx917 SDK3 raw AT Wi-Fi interface for UTF automation."""

import json
import re
import threading
import time
from enum import IntEnum
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from utf.interfaces.cli import CLITransport, CLITransportException
from utf.interfaces.wifi import SecurityMode, WiFiInterface, WiFiScanResult, WlanError
from utf.utils.defaults import defaults
from utf_wiseconnect_3.tests.devices.si91x import Si91xBSDSocketParams, Si91xOperatingMode
from utf_wiseconnect_3.tests.sl_status import SLStatus


_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_STATUS_RE = re.compile(
    r"^[\x00-\x1f\s]*(OK|ERROR|READY)\b(?:\s*[:=,]?\s*(.*))?$",
    re.IGNORECASE,
)

# A response is complete once the firmware emits its status token, so reads must
# accumulate every preceding line (banners, payloads) instead of stopping at the
# first newline.
_RESPONSE_END_RE = re.compile(
    r"^[\x00-\x1f\s]*(?:OK|ERROR|READY)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
# at+send answers either with a status token or with the '>' payload prompt.
_SEND_PROMPT_RE = re.compile(
    r"^[ \t]*(?:(?:OK|ERROR|READY)\b.*|>[ \t]*)$", re.IGNORECASE | re.MULTILINE
)
_PROMPT_RE = re.compile(r"^>[ \t]*$")

# at+wifi-scan-rslts requires a result count; the firmware returns fewer if it
# found fewer.
_MAX_SCAN_RESULTS = 20

# Only an extended scan stores results for at+wifi-scan-rslts; every other scan
# type reports them once via this asynchronous event.
_SCAN_EVENT_PREFIX = "at+WIFI_SCAN_RESULTS"

# Base of the SL_STATUS_SI91X error space used by the firmware.
_SI91X_STATUS_BASE = 0x10000

# sl_wifi_dtim_aligned_type_t values accepted by at+wifi-perf-prof.
_ALIGN_WITH_BEACON = 0
_ALIGN_WITH_DTIM_BEACON = 1

# at+wifi-net-info? answers with positional, space-separated values instead of
# key/value pairs, and quotes the SSID.
_NET_INFO_FIELDS = (
    "state",
    "channel",
    "ssid",
    "mac_address",
    "security_mode",
    "psk",
    "ipv4_address",
    "ipv6_address",
)
_NET_INFO_STATE_RE = re.compile(r"[A-Z][A-Z_]+")
_NET_INFO_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')


class SlNetInterfaceType(IntEnum):
    """SL Net interface identifiers used by the SiWx917 AT firmware.

    Values mirror sl_net_interface_t in sl_net_constants.h, which is not in
    plain numerical order.
    """

    SL_NET_WIFI_CLIENT_1_INTERFACE = 1 << 3
    SL_NET_WIFI_CLIENT_2_INTERFACE = (1 << 3) + 1
    SL_NET_WIFI_CLIENT_INTERFACE = SL_NET_WIFI_CLIENT_1_INTERFACE
    SL_NET_WIFI_AP_1_INTERFACE = 2 << 3
    SL_NET_WIFI_AP_2_INTERFACE = (2 << 3) + 1
    SL_NET_WIFI_AP_INTERFACE = SL_NET_WIFI_AP_1_INTERFACE
    WIFI_CLIENT = SL_NET_WIFI_CLIENT_1_INTERFACE


class SlWifiInterfaceType(IntEnum):
    """Wi-Fi interface identifiers used by the at+wifi-* commands.

    Values mirror sl_wifi_interface_t, which is a different enum from the
    sl_net_interface_t values the at+net-* commands expect.
    """

    SL_WIFI_CLIENT_INTERFACE = 1 << 0
    SL_WIFI_AP_INTERFACE = 1 << 1
    SL_WIFI_2_4GHZ_INTERFACE = 1 << 2
    SL_WIFI_5GHZ_INTERFACE = 1 << 3
    SL_WIFI_CLIENT_2_4GHZ_INTERFACE = (1 << 0) | (1 << 2)
    SL_WIFI_AP_2_4GHZ_INTERFACE = (1 << 1) | (1 << 2)


class SlWifiSecurity(IntEnum):
    """Wi-Fi security types (sl_wifi_security_t) as sent to the firmware."""

    OPEN = 0
    WPA = 1
    WPA2 = 2
    WEP = 3
    WPA_ENTERPRISE = 4
    WPA2_ENTERPRISE = 5
    WPA_WPA2_MIXED = 6
    WPA3 = 7
    WPA3_TRANSITION = 8
    WPA3_ENTERPRISE = 9
    WPA3_TRANSITION_ENTERPRISE = 10


class SlIpManagement(IntEnum):
    """IP allocation modes (sl_ip_management_t)."""

    STATIC = 1
    DHCP = 2


class SlWifiRegionCode(IntEnum):
    """Wi-Fi region codes accepted by ``at+region-code``."""

    DEFAULT = 0
    US = 1
    EUROPE = 2
    JAPAN = 3
    WORLDWIDE = 4
    KOREA = 5
    CHINA = 7


class SlWifiPerformanceProfile(IntEnum):
    """Performance profiles (sl_wifi_system_performance_profile_t)."""

    HIGH_PERFORMANCE = 0
    ASSOCIATED_POWER_SAVE = 1
    ASSOCIATED_POWER_SAVE_LOW_LATENCY = 2
    DEEP_SLEEP_WITHOUT_RAM_RETENTION = 3
    DEEP_SLEEP_WITH_RAM_RETENTION = 4


class SlWifiScanType(IntEnum):
    """Wi-Fi scan types (sl_wifi_scan_type_t)."""

    ACTIVE = 0x00
    PASSIVE = 0x01
    EXTENDED = 0x02
    PROHIBITED_CHANNELS = 0x04
    ADV_SCAN = 0x08


class SlIpAddressType(IntEnum):
    """IP address types (sl_ip_address_type_t)."""

    IPV4 = 4
    IPV6 = 8


class SlNetProfileId(IntEnum):
    """SL Net profile identifiers used by the SiWx917 AT firmware."""

    SL_NET_PROFILE_ID_0 = 0
    DEFAULT = SL_NET_PROFILE_ID_0


class SlNetCredentialId(IntEnum):
    """SL Net credential identifiers.

    The firmware rejects credential ID 0, so the Wi-Fi client default is 1.
    """

    SL_NET_DEFAULT_WIFI_CLIENT_CREDENTIAL_ID = 1
    DEFAULT = SL_NET_DEFAULT_WIFI_CLIENT_CREDENTIAL_ID


class ATWiFiScanResult(WiFiScanResult):
    """Wi-Fi scan result supporting both UTF attributes and mapping access."""

    _KEY_ALIASES = {"rssi_val": "rssi"}

    def __getitem__(self, key: str) -> Any:
        return getattr(self, self._KEY_ALIASES.get(key, key))

    def get(self, key: str, default: Any = None) -> Any:
        """Return a result field using dictionary-compatible access."""
        try:
            return self[key]
        except AttributeError:
            return default

    def keys(self) -> Tuple[str, ...]:
        """Return fields exposed by this result."""
        return (
            "rf_channel",
            "security_mode",
            "rssi",
            "rssi_val",
            "network_type",
            "ssid",
            "bssid",
        )


def create_interface(
    config,
    cli_transport,
    gpio_transport=None,
    reset="soft",
    device=None,
) -> WiFiInterface:
    """Create the raw SiWx917 AT interface used by UTF harness loading."""
    return SLWifiATCLI(config, cli_transport, gpio_transport, reset, device)


class SLWifiATCLI(WiFiInterface):
    """Thread-safe UTF interface for the SiWx917 SDK3 line-oriented AT API."""

    IPConfig = WiFiInterface.IPConfig

    # The firmware answers nothing at all until it has booted, so readiness is
    # polled rather than waited on with a single long timeout.
    READY_POLL_TIMEOUT = 2
    BOOT_TIMEOUT = 30

    def __init__(
        self,
        config: dict,
        cli_transport: Union[str, CLITransport],
        gpio_transport: Union[str, CLITransport] = None,
        reset: str = "soft",
        device=None,
    ):
        super().__init__(config)
        self.config = config or {}
        self.device = device
        self.bus = (
            device.create_interface(cli_transport)
            if isinstance(cli_transport, str)
            else cli_transport
        )
        self.gpio_bus = (
            device.create_interface(gpio_transport)
            if gpio_transport and isinstance(gpio_transport, str)
            else gpio_transport
        )
        self.reset_method = reset
        self._lock = threading.RLock()
        self._statistics_lock = threading.Lock()
        self._statistics_events: List[str] = []
        self._scan_lock = threading.Lock()
        self._scan_events: List[str] = []
        self._scan_pending = False
        self.inited = False
        self.associated = False
        self.networked = False
        self.power_save_mode = "high_performance"
        self.power_save_enabled = False
        self.bt_power_save = False
        self.ip = None
        self.channel: int = 0
        self.sockets_info: Dict[str, List[int]] = {
            "sync_sockets": [],
            "async_sockets": [],
        }
        if hasattr(self.bus, "register_rx_data_observer"):
            self.bus.register_rx_data_observer(
                self._on_incoming_rx_data, override=False
            )

    @staticmethod
    def _value(value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        return value

    @classmethod
    def _csv(cls, values: Iterable[Any]) -> str:
        fields = [
            "" if value is None else str(cls._value(value)) for value in values
        ]
        # Omitted trailing arguments and empty ones mean the same thing to the
        # firmware, and omitting them keeps the commands readable in the logs.
        while fields and fields[-1] == "":
            fields.pop()
        return ",".join(fields)

    @classmethod
    def _number(cls, value: Any, default: int = 0) -> int:
        """Return an AT numeric argument, treating None and "" as the default."""
        value = cls._value(value)
        if value is None or value == "":
            return default
        return int(value)

    @staticmethod
    def _decode(response: Union[str, bytes, None]) -> str:
        if response is None:
            return ""
        if isinstance(response, bytes):
            return response.decode("utf-8", errors="replace")
        return str(response)

    @staticmethod
    def _firmware_error_code(code: int) -> int:
        """Strip the SL_STATUS_SI91X prefix the AT firmware adds to its errors.

        Firmware errors reach the host as ``0x10000 | <code>`` while the UTF
        error tables and WlanError constants are keyed by the bare code.
        """
        if _SI91X_STATUS_BASE <= code <= _SI91X_STATUS_BASE + 0xFFFF:
            return code - _SI91X_STATUS_BASE
        return code

    @staticmethod
    def _status_name(code: int) -> str:
        """Return the sl_status name the firmware reported, when it is known."""
        try:
            return SLStatus(code).name
        except ValueError:
            return "an unmapped sl_status"

    def _parse_response(
        self,
        command: str,
        response: Union[str, bytes, None],
        accepted: Tuple[str, ...],
    ) -> bytes:
        text = self._decode(response).replace("\x00", "").strip()
        if not text:
            raise RuntimeError(f"No response received for AT command '{command}'")

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        lines = [line for line in lines if line.lower() != command.lower()]
        lines = [line for line in lines if not _PROMPT_RE.match(line)]
        status_index = None
        status = None
        inline_payload = ""
        for index, line in enumerate(lines):
            match = _STATUS_RE.match(line)
            if match:
                status_index = index
                status = match.group(1).upper()
                inline_payload = (match.group(2) or "").strip()

        if status is None:
            raise RuntimeError(
                f"Unexpected response for AT command '{command}': {text!r}"
            )
        if status == "ERROR":
            error_text = inline_payload or "unspecified firmware error"
            code_match = re.search(r"(?i)(?:0x[0-9a-f]+|\b\d+\b)", error_text)
            if code_match:
                token = code_match.group(0)
                code = int(token, 16 if token.lower().startswith("0x") else 10)
                # WlanError renders every code through the SI91X table, where
                # the generic sl_status values the AT firmware also returns have
                # unrelated meanings, so name the raw status in the log first.
                self.logger.error(
                    "AT command '%s' failed with %s (0x%X)",
                    command,
                    self._status_name(code),
                    code,
                )
                raise WlanError(self._firmware_error_code(code), command)
            raise RuntimeError(f"AT command '{command}' failed: ERROR {error_text}")
        if status not in accepted:
            raise RuntimeError(
                f"AT command '{command}' returned {status}; expected {accepted}"
            )

        payload_lines = lines[:status_index] + lines[status_index + 1 :]
        if inline_payload:
            payload_lines.insert(0, inline_payload)
        return "\n".join(payload_lines).encode()

    def issue_command(
        self,
        line: str,
        timeout: float = 10,
        retries: int = 0,
        accepted: Tuple[str, ...] = ("OK",),
    ) -> bytes:
        """Issue one AT command and return its payload without the status token."""
        last_error = None
        for attempt in range(retries + 1):
            try:
                with self._lock:
                    response = self.bus.write_line_and_expect(
                        line, expected=_RESPONSE_END_RE, timeout=timeout
                    )
                return self._parse_response(line, response, accepted)
            except (CLITransportException, RuntimeError) as error:
                last_error = error
                if attempt < retries:
                    time.sleep(1)
        raise last_error

    def ready(self, timeout: float = 5) -> bool:
        """Query whether the AT firmware is ready."""
        self.issue_command("at+ready?", timeout=timeout)
        return True

    def wait_until_ready(
        self,
        timeout: float = BOOT_TIMEOUT,
        poll_timeout: float = READY_POLL_TIMEOUT,
    ) -> None:
        """Poll at+ready? until the firmware answers.

        The firmware stays silent while it is booting, so this is the only
        reliable way to know a reset has completed.
        """
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                self.issue_command("at+ready?", timeout=poll_timeout)
                return
            except (CLITransportException, RuntimeError) as error:
                last_error = error
        raise RuntimeError(
            f"AT firmware did not report ready within {timeout}s: {last_error}"
        )

    def set_echo(self, enabled: Union[bool, int], timeout: float = 5) -> None:
        """Enable or disable AT command echo."""
        self.issue_command(f"at+echo={int(bool(enabled))}", timeout=timeout)

    def set_operation_mode(self, mode: Any, timeout: float = 10) -> None:
        """Set the Wi-Fi operation mode."""
        self.issue_command(
            f"at+oper-mode={self._value(mode)}", timeout=timeout
        )

    def enable_ssl(self, enabled: Union[bool, int] = 1, timeout: float = 10) -> bytes:
        """Enable or disable the firmware SSL feature.

        The firmware only accepts this before at+net-init, because the SSL
        feature bitmap is latched when the interface initializes.
        """
        return self.issue_command(
            f"at+enable-ssl={int(bool(enabled))}", timeout=timeout
        )

    @defaults("wifi")
    def init(
        self,
        mode: Any = None,
        oper_mode: Any = None,
        region_code: Any = None,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 20,
        **_,
    ) -> bytes:
        """Initialize the configured SL Net interface."""
        self.wait_until_ready()
        oper_mode = (
            oper_mode
            if oper_mode is not None
            else mode
            if mode is not None
            else self.config.get("oper_mode", Si91xOperatingMode.WiFiClient)
        )
        self.set_operation_mode(oper_mode, timeout=timeout)
        region_code = region_code or self.config.get("region_code")
        if region_code:
            self.set_wifi_region(region_code)
        payload = self.issue_command(
            f"at+net-init={self._value(interface)}", timeout=timeout
        )
        self.inited = True
        return payload

    def get_init_state(self, timeout: float = 5) -> bytes:
        """Return the firmware network-initialization query payload."""
        return self.issue_command("at+net-init?", timeout=timeout)

    net_init = init

    def deinit(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
        **_,
    ) -> bytes:
        """Deinitialize the configured SL Net interface."""
        self.close_sockets()
        payload = self.issue_command(
            f"at+net-deinit={self._value(interface)}", timeout=timeout
        )
        self.inited = False
        self.associated = False
        self.networked = False
        self.ip = None
        return payload

    net_deinit = deinit

    def reset(self, timeout: float = 10) -> bytes:
        """Soft-reset the firmware and clear cached UTF state."""
        payload = b""
        try:
            payload = self.issue_command(
                "at+soft-reset", timeout=timeout, accepted=("OK", "READY")
            )
        except (CLITransportException, RuntimeError) as error:
            # The reset can start before the OK reaches the host, and a board
            # that just booted may drop the command entirely. Readiness polling
            # below decides whether the firmware is usable.
            self.logger.info(
                "No usable response to at+soft-reset (%s); polling readiness", error
            )
        self._clear_state()
        self.wait_until_ready()
        return payload

    soft_reset = reset

    def _clear_state(self) -> None:
        self.inited = False
        self.associated = False
        self.networked = False
        self.power_save_mode = "high_performance"
        self.power_save_enabled = False
        self.ip = None
        self.sockets_info = {"sync_sockets": [], "async_sockets": []}

    def version(self, timeout: float = 10) -> str:
        """Return the NWP firmware version."""
        return self.get_fw_version(timeout=timeout)

    def get_fw_version(self, timeout: float = 10, **_) -> str:
        """Return the NWP firmware version."""
        return self.issue_command("at+wifisys-fwver?", timeout=timeout).decode().strip()

    def is_interface_up(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 5,
    ) -> bytes:
        """Return the interface-up query payload."""
        return self.issue_command(
            f"at+wifi-is-ifup={self._wifi_interface(interface)}", timeout=timeout
        )

    def get_wireless_info(self, timeout: float = 10) -> Union[dict, str]:
        """Return parsed wireless information when the fields are recognized."""
        payload = self.issue_command("at+wifi-net-info?", timeout=timeout).decode()
        parsed = self._parse_wireless_info(payload)
        return parsed or payload.strip()

    sl_wifi_get_wireless_info = get_wireless_info

    def set_wifi_region(self, region_code: Any = "us", timeout: float = 10, **_) -> bytes:
        """Set the Wi-Fi regulatory region code."""
        raw_region = self._value(region_code)
        if isinstance(raw_region, str):
            key = raw_region.strip().lower()
            if key.isdigit():
                region = int(key)
            else:
                try:
                    region = int(self._REGION_VALUES[key])
                except KeyError as error:
                    raise ValueError(
                        f"Unsupported Wi-Fi region code {region_code!r}"
                    ) from error
        else:
            region = int(raw_region)
        payload = self.issue_command(f"at+region-code={region}", timeout=timeout)
        self.region_code = region
        return payload

    def get_mac_address(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
        **_,
    ) -> str:
        """Return the MAC address for an SL Net interface."""
        payload = self.issue_command(
            f"at+wifi-get-mac={self._wifi_interface(interface)}", timeout=timeout
        ).decode()
        match = _MAC_RE.search(payload)
        if not match:
            raise RuntimeError(f"Could not parse MAC address from {payload!r}")
        return match.group(0).replace("-", ":").lower()

    def set_mac_address(self, mac_address: str, timeout: float = 10) -> bytes:
        """Override the station MAC address.

        The firmware applies this only before at+net-init, so it has to run
        while the interface is still down.
        """
        if not _MAC_RE.search(str(mac_address)):
            raise ValueError(f"Not a MAC address: {mac_address!r}")
        return self.issue_command(
            f"at+mac-addr={mac_address}", timeout=timeout
        )

    def set_client_credentials(
        self,
        profile_id: Any,
        ssid: str,
        credential_id: Any = SlNetCredentialId.DEFAULT,
        security: Any = None,
        encryption: Any = None,
        timeout: float = 10,
    ) -> bytes:
        """Set SSID, credential, security and encryption on a client profile."""
        return self.issue_command(
            "at+net-sta-cred="
            + self._csv(
                (
                    profile_id,
                    self._quote(ssid),
                    credential_id,
                    None if security is None else self._security_value(security),
                    encryption,
                )
            ),
            timeout=timeout,
        )

    def set_client_channel(
        self,
        profile_id: Any,
        channel: Any,
        band: Any = None,
        bandwidth: Any = None,
        timeout: float = 10,
    ) -> bytes:
        """Set the preferred channel on a Wi-Fi client profile."""
        return self.issue_command(
            "at+net-sta-chan=" + self._csv((profile_id, channel, band, bandwidth)),
            timeout=timeout,
        )

    def set_client_bss(
        self,
        profile_id: Any,
        bssid: Optional[str] = None,
        bss_type: Any = 0,
        timeout: float = 10,
    ) -> bytes:
        """Set the BSSID to join on a Wi-Fi client profile.

        The firmware also switches the join to BSSID-based when this runs, so
        only send it when a BSSID is actually wanted.
        """
        return self.issue_command(
            "at+net-sta-bss=" + self._csv((profile_id, bssid or 0, bss_type)),
            timeout=timeout,
        )

    def set_client_options(
        self,
        profile_id: Any,
        options: Any = None,
        channel_bitmap_2g4: Any = None,
        channel_bitmap_5g: Any = None,
        priority: Any = None,
        timeout: float = 10,
    ) -> bytes:
        """Set Wi-Fi client profile option flags."""
        return self.issue_command(
            "at+net-sta-opt="
            + self._csv(
                (profile_id, options, channel_bitmap_2g4, channel_bitmap_5g, priority)
            ),
            timeout=timeout,
        )

    def set_client_ip(
        self,
        profile_id: Any,
        ip_mode: Any = SlIpManagement.DHCP,
        ip_type: Any = SlIpAddressType.IPV4,
        host_name: Optional[str] = None,
        static_ip: Optional[str] = None,
        ipv6_global_ip: Optional[str] = None,
        gateway: Optional[str] = None,
        netmask: Optional[str] = None,
        timeout: float = 10,
    ) -> bytes:
        """Set the IP allocation carried by a Wi-Fi client profile."""
        return self.issue_command(
            "at+net-sta-ip="
            + self._csv(
                (
                    profile_id,
                    ip_mode,
                    ip_type,
                    host_name,
                    static_ip or 0,
                    ipv6_global_ip,
                    gateway or 0,
                    netmask or 0,
                )
            ),
            timeout=timeout,
        )

    def set_dhcp_configuration(self, *values: Any, timeout: float = 10) -> bytes:
        """Set the DHCP client timers carried by at+net-dhcp-conf.

        The firmware takes the timer values positionally and does not name
        them, so they are forwarded in the order the caller supplies.
        """
        suffix = "=" + self._csv(values) if values else ""
        return self.issue_command("at+net-dhcp-conf" + suffix, timeout=timeout)

    net_dhcp_conf = set_dhcp_configuration

    def set_listen_interval(
        self,
        interval: Any,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
    ) -> bytes:
        """Set the station listen interval in milliseconds."""
        return self.issue_command(
            "at+wifi-listen-interval="
            + self._csv((self._wifi_interface(interface), interval)),
            timeout=timeout,
        )

    def get_listen_interval(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
    ) -> str:
        """Return the listen-interval query payload.

        Format is at+wifi-get-listen-interval=<interface>. Omitting the
        interface returns SL_STATUS_INVALID_PARAMETER (0x21). Pre-condition
        is net-init (see SiWx91x AT Commands Reference).
        """
        return self.issue_command(
            "at+wifi-get-listen-interval="
            + str(self._wifi_interface(interface)),
            timeout=timeout,
        ).decode().strip()

    @classmethod
    def _wifi_interface(cls, interface: Any) -> int:
        """Map an interface to sl_wifi_interface_t for the at+wifi-* commands."""
        value = cls._value(interface)
        if value == SlNetInterfaceType.SL_NET_WIFI_AP_INTERFACE:
            return int(SlWifiInterfaceType.SL_WIFI_AP_INTERFACE)
        if value in (
            SlNetInterfaceType.SL_NET_WIFI_CLIENT_1_INTERFACE,
            SlNetInterfaceType.SL_NET_WIFI_CLIENT_2_INTERFACE,
        ):
            return int(SlWifiInterfaceType.SL_WIFI_CLIENT_INTERFACE)
        return int(value)

    @staticmethod
    def _quote(value: Optional[str]) -> Optional[str]:
        """Quote a value so commas and spaces survive the firmware parser."""
        if value is None:
            return None
        text = str(value)
        return text if text.startswith('"') else f'"{text}"'

    _PERFORMANCE_PROFILES = {
        "high_performance": SlWifiPerformanceProfile.HIGH_PERFORMANCE,
        "power_save": SlWifiPerformanceProfile.ASSOCIATED_POWER_SAVE,
        "associated_power_save": SlWifiPerformanceProfile.ASSOCIATED_POWER_SAVE,
        "power_save_low_latency": (
            SlWifiPerformanceProfile.ASSOCIATED_POWER_SAVE_LOW_LATENCY
        ),
        "associated_power_save_low_latency": (
            SlWifiPerformanceProfile.ASSOCIATED_POWER_SAVE_LOW_LATENCY
        ),
        "standby_power_save": (
            SlWifiPerformanceProfile.DEEP_SLEEP_WITHOUT_RAM_RETENTION
        ),
        "deep_sleep_without_ram_retention": (
            SlWifiPerformanceProfile.DEEP_SLEEP_WITHOUT_RAM_RETENTION
        ),
        "standby_power_save_with_ram_retention": (
            SlWifiPerformanceProfile.DEEP_SLEEP_WITH_RAM_RETENTION
        ),
        "deep_sleep_with_ram_retention": (
            SlWifiPerformanceProfile.DEEP_SLEEP_WITH_RAM_RETENTION
        ),
    }

    _SECURITY_VALUES = {
        SecurityMode.Open: SlWifiSecurity.OPEN,
        SecurityMode.WEP: SlWifiSecurity.WEP,
        SecurityMode.WPA: SlWifiSecurity.WPA,
        SecurityMode.WPA2: SlWifiSecurity.WPA2,
        SecurityMode.WPAWPA2MixedMode: SlWifiSecurity.WPA_WPA2_MIXED,
        SecurityMode.WPAEnterprise: SlWifiSecurity.WPA_ENTERPRISE,
        SecurityMode.WPA2Enterprise: SlWifiSecurity.WPA2_ENTERPRISE,
        SecurityMode.WPAWPA2EnterpriseMixedMode: SlWifiSecurity.WPA2_ENTERPRISE,
        SecurityMode.WPA3: SlWifiSecurity.WPA3,
        SecurityMode.WPA2WPA3MixedMode: SlWifiSecurity.WPA3_TRANSITION,
        SecurityMode.WPA3Transition: SlWifiSecurity.WPA3_TRANSITION,
    }

    _REGION_VALUES = {
        "default": SlWifiRegionCode.DEFAULT,
        "us": SlWifiRegionCode.US,
        "usa": SlWifiRegionCode.US,
        "europe": SlWifiRegionCode.EUROPE,
        "eu": SlWifiRegionCode.EUROPE,
        "japan": SlWifiRegionCode.JAPAN,
        "jp": SlWifiRegionCode.JAPAN,
        "world": SlWifiRegionCode.WORLDWIDE,
        "worldwide": SlWifiRegionCode.WORLDWIDE,
        "rest_of_world": SlWifiRegionCode.WORLDWIDE,
        "korea": SlWifiRegionCode.KOREA,
        "kr": SlWifiRegionCode.KOREA,
        "china": SlWifiRegionCode.CHINA,
        "cn": SlWifiRegionCode.CHINA,
    }

    @classmethod
    def _security_value(cls, security: Any) -> int:
        """Convert a UTF security mode to its sl_wifi_security_t number."""
        if isinstance(security, int) and not isinstance(security, SecurityMode):
            return int(security)
        try:
            return int(cls._SECURITY_VALUES[SecurityMode.convert(security)])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Unsupported Wi-Fi security mode {security!r}")

    @classmethod
    def _is_open(cls, security: Any) -> bool:
        return cls._security_value(security) == SlWifiSecurity.OPEN

    @defaults("wifi")
    def join(
        self,
        ssid: str = "",
        passphrase: str = "",
        security: Any = SecurityMode.Open,
        channel: Any = 0,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        profile_id: Any = SlNetProfileId.DEFAULT,
        credential_id: Any = SlNetCredentialId.DEFAULT,
        bssid: Optional[str] = None,
        options: Any = None,
        timeout: float = 60,
        expected_negative_status=None,
        **_,
    ):
        """Configure an SL Net client profile and bring its interface up.

        Each at+net-sta-* command saves the profile, so no separate commit is
        needed; the PSK must exist before the profile references its ID.
        """
        if not self.inited:
            raise RuntimeError("Device has not been initialized")
        open_network = self._is_open(security)
        try:
            if not open_network:
                self.set_psk(credential_id, passphrase, timeout)
            self.set_client_credentials(
                profile_id,
                ssid,
                credential_id=0 if open_network else credential_id,
                security=security,
                timeout=timeout,
            )
            if channel:
                self.set_client_channel(profile_id, channel, timeout=timeout)
            if bssid:
                self.set_client_bss(profile_id, bssid, timeout=timeout)
            if options is not None:
                self.set_client_options(profile_id, options, timeout=timeout)
            self.set_client_ip(profile_id, timeout=timeout)
            payload = self.issue_command(
                "at+net-up=" + self._csv((interface, profile_id)), timeout=timeout
            )
        except WlanError as error:
            if expected_negative_status is not None:
                return error.error_code, b""
            raise
        self.associated = True
        self.channel = int(channel) if channel else 0
        if expected_negative_status is not None:
            return 0, payload
        return payload

    def join_ap(self, access_point, **kwargs) -> bytes:
        """Join using credentials supplied by a UTF access-point interface."""
        wifi = access_point.interfaces.wifi
        security = kwargs.pop(
            "security", getattr(wifi.security, "name", wifi.security)
        )
        return self.join(
            ssid=wifi.ssid,
            passphrase=wifi.passphrase or "",
            security=security,
            channel=wifi.channel or 0,
            **kwargs,
        )

    def leave(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
        **_,
    ) -> bytes:
        """Close sockets and disconnect the active SL Net profile."""
        self.close_sockets()
        try:
            payload = self.issue_command(
                f"at+net-down={self._value(interface)}", timeout=timeout
            )
        except WlanError as error:
            # A failed or already-completed net-up leaves the interface down,
            # and tearing it down again must not mask the original failure.
            # Firmware returns SL_STATUS_WIFI_INTERFACE_NOT_UP (0xB44) when
            # at+net-down runs after a failed at+net-up; that is also benign.
            already_down = (
                WlanError.COMMAND_GIVEN_IN_INCORRECT_STATE,
                int(SLStatus.SL_STATUS_WIFI_INTERFACE_NOT_UP),
            )
            if error.error_code not in already_down:
                raise
            self.logger.info("Interface %s was already down", self._value(interface))
            payload = b""
        self.associated = False
        self.networked = False
        self.ip = None
        self.channel = 0
        return payload

    disconnect = leave

    def configure_ip(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        profile_id: Any = SlNetProfileId.DEFAULT,
        static_ip: Optional[str] = None,
        static_subnet: Optional[str] = None,
        static_gateway: Optional[str] = None,
        ip_version: str = "ipv4",
        timeout: float = 60,
    ) -> "WiFiInterface.IPConfig":
        """Configure DHCP or static station addressing and return IP details.

        A profile only takes effect when at+net-up runs, so an address set on a
        live interface goes through at+net-conf-ip instead.
        """
        ip_type = (
            SlIpAddressType.IPV6
            if str(ip_version).lower() in ("6", "ipv6")
            else SlIpAddressType.IPV4
        )
        if static_ip is not None:
            if not static_subnet or not static_gateway:
                raise ValueError("Static IP requires subnet and gateway")
            if self.associated:
                self.issue_command(
                    "at+net-conf-ip="
                    + self._csv(
                        (
                            interface,
                            SlIpManagement.STATIC,
                            ip_type,
                            "",
                            static_ip,
                            static_gateway,
                            static_subnet,
                        )
                    ),
                    timeout=timeout,
                )
            else:
                self.set_client_ip(
                    profile_id,
                    ip_mode=SlIpManagement.STATIC,
                    ip_type=ip_type,
                    static_ip=static_ip,
                    gateway=static_gateway,
                    netmask=static_subnet,
                    timeout=timeout,
                )
        info = self.get_network_info(interface=interface, timeout=timeout)
        addresses = _IPV4_RE.findall(info)
        if len(addresses) < 1:
            raise RuntimeError(f"Could not parse an IPv4 address from {info!r}")
        ip = addresses[0]
        netmask = addresses[1] if len(addresses) > 1 else (static_subnet or "")
        gateway = addresses[2] if len(addresses) > 2 else (static_gateway or "")
        self.ip = self.IPConfig(ip=ip.encode(), netmask=netmask.encode(), gateway=gateway.encode())
        self.networked = True
        return self.ip

    def start_ip(self, **kwargs) -> "WiFiInterface.IPConfig":
        """Compatibility alias for configuring station IP."""
        kwargs.pop("vid", None)
        return self.configure_ip(**kwargs)

    def start_ip_in_static_mode(self, **kwargs) -> "WiFiInterface.IPConfig":
        """Compatibility alias for static station IP configuration."""
        return self.start_ip(**kwargs)

    def get_network_info(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
    ) -> str:
        """Return raw SL Net interface information."""
        return self.issue_command(
            f"at+net-info={self._value(interface)}", timeout=timeout
        ).decode()

    def get_ip_address(self, network_interface=None) -> str:
        """Return the cached IPv4 address."""
        if self.ip is None:
            info = self.get_network_info(
                interface=network_interface
                or SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE
            )
            matches = _IPV4_RE.findall(info)
            if not matches:
                raise RuntimeError(f"Could not parse an IPv4 address from {info!r}")
            return matches[0]
        return self.ip.ip.decode() if isinstance(self.ip.ip, bytes) else self.ip.ip

    def get_device_ip(self, device_ip) -> str:
        """Extract the IP address from a UTF IP configuration result."""
        value = getattr(device_ip, "ip", device_ip)
        return value.decode() if isinstance(value, bytes) else str(value)

    def scan(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        filter_ssid: Optional[str] = None,
        scan_type: Any = None,
        scan_flags: Any = None,
        periodic_scan_interval: Any = None,
        channel_bitmap_2g4: Any = None,
        channel_bitmap_5g: Any = None,
        enable_lp_mode: Any = None,
        timeout: float = 60,
        **kwargs,
    ) -> List[ATWiFiScanResult]:
        """Start a scan and retrieve all scan results reported by firmware."""
        if filter_ssid is None:
            filter_ssid = kwargs.pop("ssid", "") or ""
        if channel_bitmap_2g4 is None:
            channel_bitmap_2g4 = kwargs.pop(
                "scan_bitmap_2_4", kwargs.pop("channel", None)
            )
        if enable_lp_mode is None:
            enable_lp_mode = kwargs.pop("lp_mode", None)
        max_results = kwargs.pop("scan_count_extended", None)
        kwargs.pop("extended", None)
        scan_type = SlWifiScanType.ACTIVE if scan_type is None else scan_type
        values = (
            self._wifi_interface(interface),
            filter_ssid,
            scan_type,
            0 if scan_flags is None else scan_flags,
            0 if periodic_scan_interval is None else periodic_scan_interval,
            0 if channel_bitmap_2g4 is None else channel_bitmap_2g4,
            0 if channel_bitmap_5g is None else channel_bitmap_5g,
            0 if enable_lp_mode is None else enable_lp_mode,
        )
        with self._scan_lock:
            self._scan_events.clear()
            self._scan_pending = True
        try:
            self.issue_command(
                "at+wifi-start-scan=" + self._csv(values), timeout=timeout
            )
        except Exception:
            with self._scan_lock:
                self._scan_pending = False
            raise
        if self._value(scan_type) == SlWifiScanType.EXTENDED:
            return self.get_extended_scan_results(
                max_results=max_results, timeout=timeout
            )
        results = self.wait_for_scan_results(timeout=timeout)
        return results[:max_results] if max_results else results

    def wait_for_scan_results(
        self, timeout: float = 60, poll_interval: float = 0.2
    ) -> List[ATWiFiScanResult]:
        """Wait for the at+WIFI_SCAN_RESULTS event raised when a scan finishes.

        The firmware stays silent when a scan finds nothing, so an empty list is
        a valid outcome and callers decide whether it is a failure.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._scan_lock:
                event = self._scan_events.pop(0) if self._scan_events else None
            if event is not None:
                if event.startswith("ERROR"):
                    code_match = re.search(r"(?i)(?:0x[0-9a-f]+|\b\d+\b)", event)
                    if code_match:
                        token = code_match.group(0)
                        code = int(token, 16 if token.lower().startswith("0x") else 10)
                        mapped = self._firmware_error_code(code)
                        if mapped == WlanError.NO_AP_FOUND:
                            with self._scan_lock:
                                self._scan_pending = False
                            return []
                        raise WlanError(mapped, "at+wifi-start-scan")
                return self._parse_scan_results(event)
            time.sleep(poll_interval)
        with self._scan_lock:
            self._scan_pending = False
        self.logger.info("No scan results reported within %ss", timeout)
        return []

    def stop_scan(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
    ) -> bytes:
        """Stop a scan on the selected interface."""
        return self.issue_command(
            f"at+wifi-stop-scan={self._wifi_interface(interface)}", timeout=timeout
        )

    def advance_scan(
        self,
        trigger_rssi_level: Any,
        trigger_rssi_change: Any,
        active_channel_time: Any,
        passive_channel_time: Any,
        enable_instant_scan: Any,
        enable_multi_probe: Any,
        timeout: float = 10,
        **_,
    ) -> bytes:
        """Configure advanced scan thresholds and channel timings."""
        values = (
            trigger_rssi_level,
            trigger_rssi_change,
            active_channel_time,
            passive_channel_time,
            enable_instant_scan,
            enable_multi_probe,
        )
        return self.issue_command(
            "at+wifi-scan-advconf=" + self._csv(values), timeout=timeout
        )

    configure_advanced_scan = advance_scan

    def get_extended_scan_results(
        self,
        max_results: Optional[int] = None,
        channel_filter: Any = None,
        security_mode_filter: Any = None,
        rssi_filter: Any = None,
        network_type_filter: Any = None,
        timeout: float = 30,
    ) -> List[ATWiFiScanResult]:
        """Retrieve and defensively parse the firmware scan-result payload."""
        payload = self.issue_command(
            f"at+wifi-scan-rslts={max_results or _MAX_SCAN_RESULTS}", timeout=timeout
        ).decode()
        results = self._parse_scan_results(payload)
        if channel_filter is not None:
            results = [item for item in results if item.rf_channel == int(channel_filter)]
        if security_mode_filter is not None:
            results = [
                item
                for item in results
                if item.security_mode == int(self._value(security_mode_filter))
            ]
        if rssi_filter is not None:
            results = [item for item in results if item.rssi >= int(rssi_filter)]
        if network_type_filter is not None:
            results = [
                item
                for item in results
                if item.network_type == int(self._value(network_type_filter))
            ]
        return results[:max_results] if max_results is not None else results

    @classmethod
    def _parse_scan_results(cls, payload: str) -> List[ATWiFiScanResult]:
        records: List[Any] = []
        stripped = payload.strip()
        if not stripped:
            return []
        positional = cls._parse_positional_scan_results(stripped)
        if positional is not None:
            return positional
        try:
            decoded = json.loads(stripped)
            records = decoded if isinstance(decoded, list) else [decoded]
        except json.JSONDecodeError:
            records = [
                record.strip()
                for line in stripped.splitlines()
                for record in line.split(";")
                if record.strip()
            ]

        results = []
        for record in records:
            parsed = cls._parse_scan_record(record)
            if parsed is not None:
                results.append(parsed)
        return results

    @classmethod
    def _parse_positional_scan_results(
        cls, payload: str
    ) -> Optional[List[ATWiFiScanResult]]:
        """Parse the flat list both scan-result forms use.

        The firmware emits a result count followed by
        ``channel, security, rssi, network type, SSID, BSSID`` per Access Point,
        with reserved empty fields in between. Records are cut at each BSSID so
        an SSID containing a separator does not shift the remaining fields.
        """
        text = payload.strip()
        if text.startswith(_SCAN_EVENT_PREFIX):
            text = text.split("=", 1)[1] if "=" in text else ""
        tokens = [
            token.strip().strip('"')
            for token in re.split(r"[,\s]+", text)
            if token.strip()
        ]
        if not tokens or not tokens[0].isdigit():
            return None
        results = []
        pending: List[str] = []
        for token in tokens[1:]:
            pending.append(token)
            if not _MAC_RE.fullmatch(token):
                continue
            if len(pending) >= 6:
                try:
                    results.append(
                        ATWiFiScanResult(
                            rf_channel=int(pending[0]),
                            security_mode=int(pending[1]),
                            rssi=int(pending[2]),
                            network_type=int(pending[3]),
                            ssid=",".join(pending[4:-1]),
                            bssid=token.replace("-", ":"),
                        )
                    )
                except ValueError:
                    pass
            pending = []
        return results if results else None

    @classmethod
    def _parse_scan_record(cls, record: Any) -> Optional[ATWiFiScanResult]:
        if isinstance(record, dict):
            fields = {str(key).lower(): value for key, value in record.items()}
        else:
            text = str(record).strip().strip("[]{}()")
            fields = cls._parse_key_values(text)
            if not fields:
                tokens = [token.strip().strip('"') for token in text.split(",")]
                if len(tokens) < 6:
                    return None
                if _MAC_RE.fullmatch(tokens[3]):
                    fields = {
                        "ssid": tokens[0],
                        "security_mode": tokens[1],
                        "network_type": tokens[2],
                        "bssid": tokens[3],
                        "rf_channel": tokens[4],
                        "rssi": tokens[5],
                    }
                elif _MAC_RE.fullmatch(tokens[5]):
                    fields = {
                        "rf_channel": tokens[0],
                        "security_mode": tokens[1],
                        "rssi": tokens[2],
                        "network_type": tokens[3],
                        "ssid": tokens[4],
                        "bssid": tokens[5],
                    }
                else:
                    return None
        try:
            channel = int(fields.get("rf_channel", fields.get("channel")))
            security = int(fields.get("security_mode", fields.get("security", 0)))
            rssi = int(fields.get("rssi", fields.get("rssi_val")))
            network_type = int(fields.get("network_type", fields.get("type", 0)))
            ssid = fields.get("ssid", "")
            bssid = str(fields.get("bssid", ""))
            if not _MAC_RE.fullmatch(bssid):
                return None
            return ATWiFiScanResult(
                rf_channel=channel,
                security_mode=security,
                rssi=rssi,
                network_type=network_type,
                ssid=ssid,
                bssid=bssid.replace("-", ":"),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_wireless_info(cls, payload: str) -> Dict[str, str]:
        """Map the positional at+wifi-net-info? values onto their field names.

        A key/value parse of this response matches inside the MAC address and
        drops every other field, including the SSID.
        """
        line = payload.strip()
        if not line:
            return {}
        tokens = [
            match.group(1) if match.group(1) is not None else match.group(2)
            for match in _NET_INFO_TOKEN_RE.finditer(line)
        ]
        if not tokens or not _NET_INFO_STATE_RE.fullmatch(tokens[0]):
            return cls._parse_key_values(payload)
        return dict(zip(_NET_INFO_FIELDS, tokens))

    @staticmethod
    def _parse_key_values(payload: str) -> Dict[str, str]:
        fields = {}
        for key, value in re.findall(
            r"([A-Za-z_][A-Za-z0-9 _-]*)\s*[:=]\s*([^,\r\n]+)", payload
        ):
            fields[key.strip().lower().replace(" ", "_").replace("-", "_")] = (
                value.strip().strip('"')
            )
        return fields

    def set_performance_profile(
        self,
        mode: Any = "high_performance",
        dtim_aligned_type: Any = 0,
        num_of_dtim_skip: Any = 0,
        listen_interval: Any = 0,
        monitor_interval: Any = 0,
        timeout: float = 10,
        profile_only: bool = False,
        **_,
    ) -> bytes:
        """Set the NWP performance profile and cache its UTF power state.

        at+wifi-perf-prof takes numeric arguments only, in the order
        <profile>,<dtim-aligned-type>,<num-of-dtim-skip>,<listen-interval>,
        <monitor-interval>. Profile names and the DTIM alignment values the
        test-agent CLI accepts are translated to their firmware values here;
        passing them through verbatim fails with SL_STATUS_INVALID_PARAMETER.

        C778716 / some console walks send only ``at+wifi-perf-prof=<profile>``.
        Pass ``profile_only=True`` for that compact form.
        """
        profile = self._performance_profile(mode)
        if profile_only:
            command = f"at+wifi-perf-prof={int(profile)}"
        else:
            arguments = (
                int(profile),
                self._dtim_alignment(dtim_aligned_type),
                self._number(num_of_dtim_skip),
                self._number(listen_interval),
                self._number(monitor_interval),
            )
            command = "at+wifi-perf-prof=" + self._csv(arguments)
        payload = self.issue_command(command, timeout=timeout)
        self.power_save_mode = profile.name.lower()
        self.power_save_enabled = profile != SlWifiPerformanceProfile.HIGH_PERFORMANCE
        return payload

    def _dtim_alignment(self, value: Any) -> int:
        """Map a UTF DTIM alignment argument onto the two firmware values.

        The test-agent CLI is called with vendor values such as 4; the AT
        firmware only accepts SL_WIFI_ALIGN_WITH_BEACON (0) and
        SL_WIFI_ALIGN_WITH_DTIM_BEACON (1).
        """
        alignment = self._number(value)
        if alignment in (_ALIGN_WITH_BEACON, _ALIGN_WITH_DTIM_BEACON):
            return alignment
        self.logger.info(
            "DTIM alignment %s is not an AT firmware value; using %d "
            "(align with DTIM beacon)",
            alignment,
            _ALIGN_WITH_DTIM_BEACON,
        )
        return _ALIGN_WITH_DTIM_BEACON

    @classmethod
    def _performance_profile(cls, mode: Any) -> SlWifiPerformanceProfile:
        """Map a profile name, number, or enum onto its firmware value."""
        value = cls._value(mode)
        if isinstance(value, str):
            key = value.strip().lower()
            if key.isdigit():
                return SlWifiPerformanceProfile(int(key))
            try:
                return cls._PERFORMANCE_PROFILES[key]
            except KeyError as error:
                raise ValueError(
                    f"Unsupported performance profile {mode!r}"
                ) from error
        return SlWifiPerformanceProfile(int(value))

    def enable_power_save(
        self,
        dtim_alignment_type: Any = 0,
        dtim_skip: Any = 0,
        mode: Any = "power_save_low_latency",
        listen_interval: Any = 0,
        monitor_interval: Any = 0,
        **kwargs,
    ) -> bytes:
        """Compatibility wrapper that enables the NWP power-save profile."""
        return self.set_performance_profile(
            mode,
            dtim_alignment_type,
            dtim_skip,
            listen_interval,
            monitor_interval,
            **kwargs,
        )

    def get_performance_profile(self, timeout: float = 10, **_) -> str:
        """Return the current NWP performance profile query payload."""
        return self.issue_command("at+wifi-perf-prof?", timeout=timeout).decode().strip()

    def disable_power_save(self, **kwargs) -> bytes:
        """Restore the NWP high-performance profile."""
        return self.set_performance_profile("high_performance", **kwargs)

    def cal_start(self, alarm_ms: Any = 6000, timeout: float = 10) -> bytes:
        """Start the calendar peripheral with an alarm in milliseconds."""
        return self.issue_command(
            f"at+cal-start={self._value(alarm_ms)}", timeout=timeout
        )

    def cal_stop(self, timeout: float = 10) -> bytes:
        """Stop the calendar alarm and unregister its callback."""
        return self.issue_command("at+cal-stop", timeout=timeout)

    def m4_ta_secure_handshake(
        self,
        sub_cmd_type: Any = 5,
        xtal_enable: Any = 1,
        timeout: float = 10,
    ) -> bytes:
        """Enable XTAL for M4/TA power-save entry.

        TestRail/POC name this ``at+m4-ta-secure-handshake=<sub>,<flag>``, but
        current SiWx917 AT firmware answers ``Not supported``. Use
        ``at+xtal-enable=<flag>`` instead. ``sub_cmd_type`` is kept for
        call-site compatibility with the test-agent CLI.
        """
        del sub_cmd_type
        return self.xtal_enable(xtal_enable, timeout=timeout)

    def xtal_enable(self, enabled: Any = 1, timeout: float = 10) -> bytes:
        """Enable or disable the XTAL via at+xtal-enable."""
        return self.issue_command(
            f"at+xtal-enable={int(self._value(enabled))}",
            timeout=timeout,
        )

    def m4_power_state(
        self,
        state: Any,
        additional_parameter: Any = 0,
        timeout: float = 10,
        accepted: Tuple[str, ...] = ("OK",),
    ) -> bytes:
        """Request an M4 power state (at+wifisys-psreq).

        Deep-sleep transitions may answer with READY after the configured
        calendar wake source fires, so callers can widen ``accepted``.
        """
        return self.issue_command(
            "at+wifisys-psreq=" + self._csv((state, additional_parameter)),
            timeout=timeout,
            accepted=accepted,
        )

    def get_m4_power_requirements(self, timeout: float = 10) -> str:
        """Return the M4 power-state requirement table (at+wifisys-psreq?)."""
        return (
            self.issue_command("at+wifisys-psreq?", timeout=timeout)
            .decode()
            .strip()
        )

    def get_m4_power_state(self, timeout: float = 10) -> str:
        """Return the current M4 power state (at+wifisys-ps?)."""
        return (
            self.issue_command("at+wifisys-ps?", timeout=timeout)
            .decode()
            .strip()
        )

    def m4_sleep(self, timeout: float = 10) -> bytes:
        """Put the M4 into sleep."""
        return self.issue_command("at+wifisys-sleep", timeout=timeout)

    def m4_standby(self, timeout: float = 10) -> bytes:
        """Put the M4 into standby."""
        return self.issue_command("at+wifisys-standby", timeout=timeout)

    def set_m4_wake_source(self, *values: Any, timeout: float = 10) -> bytes:
        """Configure M4 wake-source parameters."""
        suffix = "=" + self._csv(values) if values else ""
        return self.issue_command(
            "at+wifisys-wake-src" + suffix, timeout=timeout
        )

    wifisys_psreq = m4_power_state
    wifisys_psreq_query = get_m4_power_requirements
    wifisys_ps_query = get_m4_power_state
    wifisys_sleep = m4_sleep
    wifisys_standby = m4_standby
    wifisys_wake_src = set_m4_wake_source

    def create_socket(
        self,
        domain: Any = Si91xBSDSocketParams.AF_INET,
        type: Any = Si91xBSDSocketParams.SOCK_STREAM,
        protocol: Any = Si91xBSDSocketParams.IPPROTO_TCP,
        timeout: float = 10,
        **_,
    ) -> int:
        """Create a BSD socket and return its firmware socket identifier."""
        payload = self.issue_command(
            "at+socket=" + self._csv((domain, type, protocol)), timeout=timeout
        ).decode()
        match = re.search(r"(?i)(?:socket(?:[-_ ]?id)?\s*[:=,]?\s*)?(-?\d+)", payload)
        if not match:
            raise RuntimeError(f"Could not parse socket ID from {payload!r}")
        socket_id = int(match.group(1))
        self.sockets_info["sync_sockets"].append(socket_id)
        return socket_id

    socket = create_socket

    def set_socket_option(
        self,
        socket_id: Any,
        option_level: Any,
        option: Any,
        option_values: Any,
        timeout: float = 10,
    ) -> bytes:
        """Set one BSD socket option."""
        values = (
            list(option_values)
            if isinstance(option_values, (list, tuple))
            else [option_values]
        )
        return self.issue_command(
            "at+setsockopt="
            + self._csv((socket_id, option_level, option, *values)),
            timeout=timeout,
        )

    setSockopt = set_socket_option
    setsockopt = set_socket_option

    def socket_connect(
        self,
        socket_id: Any,
        address: str,
        port: Any,
        timeout: float = 30,
        **_,
    ) -> bytes:
        """Connect a BSD socket to a remote endpoint."""
        return self.issue_command(
            "at+connect=" + self._csv((socket_id, address, port)),
            timeout=timeout,
        )

    connect_socket = socket_connect

    def bind_socket(
        self,
        socket_id: Any,
        address: str,
        port: Any,
        ip_version: Any = 4,
        timeout: float = 10,
        **_,
    ) -> bytes:
        """Bind a BSD socket to a local address and port."""
        return self.issue_command(
            "at+bind=" + self._csv((socket_id, address, port, ip_version)),
            timeout=timeout,
        )

    bind = bind_socket

    def listen_socket(
        self,
        socket_id: Any,
        backlog: Any = 1,
        timeout: float = 10,
        **_,
    ) -> bytes:
        """Mark a TCP socket as listening for inbound connections."""
        return self.issue_command(
            "at+listen=" + self._csv((socket_id, backlog)),
            timeout=timeout,
        )

    listen = listen_socket

    def receive_socket(
        self,
        socket_id: Any,
        data_length: int,
        remote_ip_address: str = "",
        remote_port: Any = "",
        flags: Any = 0,
        timeout: float = 30,
        **_,
    ) -> str:
        """Receive bytes from a TCP or UDP socket and return the payload.

        Firmware format is ``at+recv=<socket-id>,<remote-ip>,<remote-port>,
        <bytes-to-read>,<flags>``. A connected TCP socket leaves the remote
        fields empty (``at+recv=0,,,29,0``); a UDP socket has to name the peer
        it receives from, otherwise the command fails as an invalid parameter.
        """
        address = self._quote(remote_ip_address) if remote_ip_address else ""
        payload = self.issue_command(
            "at+recv="
            + self._csv((socket_id, address, remote_port, data_length, flags)),
            timeout=timeout,
        ).decode("utf-8", errors="replace")
        parts = payload.split(None, 1)
        if parts and parts[0].isdigit() and len(parts) == 2:
            return parts[1][: int(parts[0])]
        return payload

    recv = receive_socket

    def socket_send(
        self,
        socket_id: Any,
        data_length: Optional[int] = None,
        data: Union[str, bytes] = b"",
        remote_ip_address: str = "",
        remote_port: Any = "",
        timeout: float = 30,
        **_,
    ) -> bytes:
        """Send raw bytes after the mapped AT send command.

        Firmware format is ``at+send=<socket-id>,<remote-ip>,<remote-port>,<len>``.
        TCP leaves the remote fields empty (``at+send=0,,,256``); UDP fills them.
        """
        payload = data.encode() if isinstance(data, str) else bytes(data)
        length = len(payload) if data_length is None else int(data_length)
        if length != len(payload):
            raise ValueError(
                f"data_length={length} does not match payload length={len(payload)}"
            )
        command = "at+send=" + self._csv(
            (socket_id, remote_ip_address, remote_port, length)
        )
        if not hasattr(self.bus, "write_bytes_and_expect"):
            raise RuntimeError("CLI transport does not support raw byte writes")
        with self._lock:
            initial = self.bus.write_line_and_expect(
                command, expected=_SEND_PROMPT_RE, timeout=timeout
            )
            if _RESPONSE_END_RE.search(self._decode(initial)):
                parsed = self._parse_response(command, initial, ("OK",))
                if parsed:
                    return parsed
            response = self.bus.write_bytes_and_expect(
                payload, expected=_RESPONSE_END_RE, timeout=timeout
            )
        return self._parse_response(command, response, ("OK",))

    send = socket_send

    def close_socket(self, socket_id: Any, timeout: float = 30, **_) -> bytes:
        """Close one BSD socket.

        A graceful TCP close can take over ten seconds, and the descriptor is
        gone either way, so tracking is dropped even when the command fails.
        """
        try:
            return self.issue_command(
                f"at+close={self._value(socket_id)}", timeout=timeout
            )
        finally:
            for sockets in self.sockets_info.values():
                while int(socket_id) in sockets:
                    sockets.remove(int(socket_id))

    socket_close = close_socket

    def close_sockets(self) -> None:
        """Close all sockets tracked by this interface, best effort."""
        for socket_id in list(
            self.sockets_info["sync_sockets"]
            + self.sockets_info["async_sockets"]
        ):
            try:
                self.close_socket(socket_id)
            except (WlanError, RuntimeError) as error:
                self.logger.info("Socket %s close failed: %s", socket_id, error)

    def http_otaf(self, *parameters: Any, timeout: float = 180) -> bytes:
        """Start HTTP OTAF using firmware-defined positional parameters."""
        suffix = "=" + self._csv(parameters) if parameters else ""
        return self.issue_command("at+http-otaf" + suffix, timeout=timeout)

    http_otaf_upgrade = http_otaf

    def start_statistics(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        channel: Any = 0,
        band: Any = 0,
        bandwidth: Any = 0,
        timeout: float = 10,
    ) -> bytes:
        """Start asynchronous Wi-Fi statistics collection."""
        with self._statistics_lock:
            self._statistics_events.clear()
        wifi_interface = self._wifi_interface(interface)
        active_channel = int(channel) if channel else (self.channel or 1)
        return self.issue_command(
            "at+wifi-stats-start="
            + self._csv((wifi_interface, active_channel, band, bandwidth)),
            timeout=timeout,
        )

    def stop_statistics(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        timeout: float = 10,
    ) -> bytes:
        """Stop asynchronous Wi-Fi statistics collection."""
        return self.issue_command(
            f"at+wifi-stats-stop={self._wifi_interface(interface)}", timeout=timeout
        )

    start_statistic_report = start_statistics
    stop_statistic_report = stop_statistics

    def get_statistics(
        self,
        interface: Any = SlNetInterfaceType.SL_NET_WIFI_CLIENT_INTERFACE,
        channel: Any = 0,
        band: Any = 0,
        bandwidth: Any = 0,
        duration: float = 0,
        timeout: float = 10,
        **_,
    ) -> List[str]:
        """Collect raw ``at+WIFI_STATS`` indications for an optional duration."""
        self.start_statistics(interface, channel, band, bandwidth, timeout)
        if duration > 0:
            time.sleep(duration)
            self.stop_statistics(interface, timeout)
        with self._statistics_lock:
            return list(self._statistics_events)

    def _on_incoming_rx_data(self, timestamp: int, record: bytes) -> None:
        text = self._decode(record)
        if "at+WIFI_STATS" in text:
            with self._statistics_lock:
                self._statistics_events.append(text.strip())
        if _SCAN_EVENT_PREFIX in text:
            with self._scan_lock:
                self._scan_pending = False
                self._scan_events.append(text.strip())
        elif self._scan_pending:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            for line in lines:
                match = _STATUS_RE.match(line)
                if match and match.group(1).upper() == "ERROR":
                    with self._scan_lock:
                        self._scan_pending = False
                        self._scan_events.append(line)
                    break

    def release_resources(self) -> None:
        """Release CLI and optional GPIO transports."""
        self.bus.release_resources()
        if self.gpio_bus is not None:
            self.gpio_bus.release_resources()

    def close(self) -> None:
        """Release resources owned by this interface."""
        self.release_resources()

    def set_state(self, value: Union[str, List[str]]) -> None:
        """Apply UTF lifecycle states supported by the raw AT interface."""
        states = [value] if isinstance(value, str) else value
        if "reset" in states:
            self.reset()
        if "init" in states and not self.inited:
            self.init()
        if "associated" in states and not self.associated:
            if not self.inited:
                self.init()
            self.join()
        if "networked" in states and not self.networked:
            if not self.associated:
                if not self.inited:
                    self.init()
                self.join()
            self.start_ip()
        if "close_sockets" in states:
            self.close_sockets()
        if "wifi_powersave_disable" in states and self.power_save_enabled:
            self.set_performance_profile("high_performance")
        if ("unassociated" in states or "disassociated" in states) and self.associated:
            self.leave()
        if "deinit" in states and self.inited:
            self.deinit()

    def set_psk(
        self, credential_id: Any, passphrase: str, timeout: float = 10
    ) -> bytes:
        """Populate a PSK credential."""
        return self.issue_command(
            "at+net-cred-wifipsk="
            + self._csv((credential_id, self._quote(passphrase))),
            timeout=timeout,
        )


# Compatibility with naming used by other UTF Wi-Fi interfaces.
SLWifiCLI = SLWifiATCLI
