"""
Reusable helpers for non-CLI WiseConnect sample-app automation.

Use SampleAppHelper from example tests that:
  - flash and boot a sample-app binary
  - open DUT console after flash (local USB serial or WSTK telnet)
  - save/read console logs
  - optionally extract IP and ping from a remote client
"""

import os
import re
import time
import string
import random
from datetime import date

from AWSIoTPythonSDK.core.protocol.internal.clients import ClientStatus
from retry import retry

from utf.utils.logger import get_logger
from utf.utf_config import UtfConfig
from utf.utils.firmware_manager import FirmwareManager
from utf.utils.stopwatch import Stopwatch
from utf.interfaces.iperf.iperf_constants import IperfConstants
from utf_wiseconnect_3.tests.devices.si91x import Si91xAwsQos


def logger():
    return get_logger(__name__)


class SampleAppHelper:
    """Class methods for repeatable non-CLI sample-app test steps."""

    DEFAULT_IP_LOG_PATTERN = r"IP address of the client:\s*(\d{1,3}(?:\.\d{1,3}){3})"
    # dual_stack / print_ip_addresses: "IPv6 Address: " then inet_ntop6 string.
    DEFAULT_IPV6_LOG_PATTERN = (
        r"IPv6 Address:\s*([0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7})"
    )

    @staticmethod
    def _is_telnet_console(bus) -> bool:
        """True when DUT console is telnet (WSTK remote), not local USB serial."""
        return hasattr(bus, "telnet_client") and not hasattr(bus, "ser")

    @staticmethod
    def open_uart(wifi_dut):
        """
        Open DUT console reader without resetting the device.

        Supports:
          - local USB serial (bus.ser)
          - WSTK telnet console (bus.telnet_client / recover_telnet_connection)
        """
        bus = wifi_dut.interfaces.wifi.bus
        if hasattr(bus, "ser"):
            _ = bus.ser  # opens /dev/ttyACM* (or COM) and starts RX reader
            logger().info("UART opened (serial reader started, no device reset)")
            return

        if hasattr(bus, "recover_telnet_connection"):
            # After release_resources()/flash the telnet session is closed; reconnect.
            bus.recover_telnet_connection()
            logger().info(
                "Telnet console opened "
                f"({getattr(bus, 'remote', '?')}:{getattr(bus, 'port', '?')}, "
                "reader started, no device reset)"
            )
            return

        if hasattr(bus, "telnet_client"):
            _ = bus.telnet_client  # opens session and starts RX reader
            logger().info(
                "Telnet console opened "
                f"({getattr(bus, 'remote', '?')}:{getattr(bus, 'port', '?')}, "
                "reader started, no device reset)"
            )
            return

        raise RuntimeError(
            f"Unsupported DUT console transport for sample-app logs: {type(bus)}. "
            "Expected serial (bus.ser) or telnet (bus.telnet_client)."
        )

    @classmethod
    def wait_and_open_uart(cls, wifi_dut, timeout_sec=10, poll_sec=0.2):
        """
        Poll until the DUT console is available after flash, then open it.

        Local serial: wait for USB re-enumeration of the COM/ACM port.
        Telnet: reconnect to WSTK console (no USB re-enumeration).
        """
        bus = wifi_dut.interfaces.wifi.bus
        transport = "telnet" if cls._is_telnet_console(bus) else "serial"
        logger().info(
            f"Waiting to open {transport} console after flash "
            f"(poll every {poll_sec}s, timeout {timeout_sec}s)..."
        )
        deadline = time.time() + timeout_sec
        last_err = None
        while time.time() < deadline:
            try:
                cls.open_uart(wifi_dut)
                return
            except Exception as ex:
                last_err = ex
                time.sleep(poll_sec)
        raise RuntimeError(
            f"Failed to open {transport} console within {timeout_sec}s after flash: "
            f"{last_err}"
        )

    @classmethod
    def flash_and_boot_sample_app(
        cls, fw_mgr, wiseconnect_duts, wifi_dut, app_name, open_uart=True
    ):
        """
        Flash a non-CLI sample app and allow the post-flash boot from commander.

        Avoid FirmwareManager.load_app_firmware(): after flash it also calls
        _process_reset() and set_state('reset_state') on every wiseconnect DUT,
        which reboots the sample app and restarts execution.

        Flow:
          1) release console (serial or telnet)
          2) flash image (commander flash performs chip reset / boot)
          3) optionally wait and open console (serial re-enum or telnet reconnect)

        Set open_uart=False for empty apps that only need flash success
        (no UART validation).
        """
        assert fw_mgr is not None, "FirmwareManager instance is not available"

        try:
            app_images = fw_mgr.manifest.firmware_applications[app_name]
        except KeyError as exc:
            raise RuntimeError(
                f"Manifest has no firmware_applications entry for '{app_name}'"
            ) from exc

        flash_device = None
        app_image = None
        candidates = list(wiseconnect_duts or [])
        for name, device in getattr(fw_mgr, "devices", {}).items():
            if device not in candidates:
                candidates.append(device)

        for device in candidates:
            matched = fw_mgr._find_app_image(app_images, device)
            if matched is not None and hasattr(device, "write_firmware"):
                flash_device = device
                app_image = matched
                break

        assert flash_device is not None and app_image is not None, (
            f"No flashable device found for sample app '{app_name}'"
        )

        logger().info("Releasing UART resources before firmware load...")
        wifi_dut.interfaces.wifi.release_resources()

        firmware_path = os.path.join(fw_mgr.manifest_path, app_image.filename)
        logger().info(
            f"Flashing and booting '{app_name}' on '{flash_device.name}': {firmware_path}"
        )
        # Optional USB recycle helps J-Link stability; happens BEFORE the new app runs.
        fw_mgr._cycle_usb_power()
        time.sleep(2)
        flash_device.write_firmware(firmware_path)
        fw_mgr.device_firmware[flash_device.name] = app_image.filename
        # Intentionally skip FirmwareManager extra resets; commander flash performs boot.

        if open_uart:
            cls.wait_and_open_uart(wifi_dut)
        else:
            logger().info(
                "Skipping UART open (flash-only sample app; no console needed)"
            )
        return flash_device

    @classmethod
    def run_flash_only_sample_app(cls, request, wiseconnect_duts, wifi_dut):
        """
        Flash a sample app and pass if flashing succeeds; do not open UART.

        Used by empty C/C++ platform templates. Erases flash in finally.
        """
        test_name = request.node.name
        app_name = cls.get_firmware_app_name(request)
        fw_mgr = FirmwareManager.get_instance()
        flash_device = None

        try:
            logger().info(
                f"Flash-only sample-app '{app_name}' (no UART) for {test_name}..."
            )
            flash_device = cls.flash_and_boot_sample_app(
                fw_mgr, wiseconnect_duts, wifi_dut, app_name, open_uart=False
            )
            logger().info(
                f"Flash of '{app_name}' succeeded — {test_name} passed"
            )
        finally:
            # UART was never opened; release is still safe / no-op if already released.
            cls.release_uart(wifi_dut)
            cls.erase_flash(flash_device)

    @staticmethod
    def read_uart_log(wifi_dut):
        """Read DUT UART log buffer as text."""
        serial_log = wifi_dut.interfaces.wifi.bus.get_input_log()
        return b"".join(line for _, line in serial_log).decode(errors="replace")

    @staticmethod
    def parse_dut_mqtt_message_payload(log_text, expected=None):
        """Extract payload after UART ``Message:`` from mqtt sample apps.

        UART often glues the next print (e.g. ``Receive Data Success``) onto the
        same line when ``\\r\\n`` is lost, so do not take until EOL blindly.
        Prefer an exact match of ``expected`` when provided.
        """
        if not log_text or "Message:" not in log_text:
            return None
        if expected:
            if re.search(
                rf"Message:\s*{re.escape(expected)}",
                log_text,
                flags=re.IGNORECASE,
            ):
                return expected
        match = re.search(
            r"Message:\s*(.+?)(?="
            r"\r?\n|"
            r"Receive Data Success|"
            r"DUT received|"
            r"Execution completed|"
            r"Unsubscription|"
            r"Disconnect|"
            r"Paho MQTT|"
            r"Socket closed|"
            r"$)",
            log_text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def send_uart_line(wifi_dut, line: str):
        """
        Send one console line to the DUT (appends bus line terminator, usually CRLF).

        Used by sample apps that take UART CLI input (e.g. calibration_app).
        """
        bus = wifi_dut.interfaces.wifi.bus
        logger().info(f"UART TX: {line}")
        bus.write_line(line)

    @classmethod
    def wait_for_uart_message(
        cls, wifi_dut, message, timeout_sec=60, poll_sec=0.25
    ):
        """
        Poll DUT UART log until ``message`` appears, or raise AssertionError.

        Used by CLI sample apps (e.g. wireless_test) that print ``Ready`` before
        accepting console commands.
        """
        logger().info(
            f"Waiting for UART message {message!r} "
            f"(timeout {timeout_sec}s, poll {poll_sec}s)..."
        )
        deadline = time.time() + timeout_sec
        last_log = ""
        while time.time() < deadline:
            last_log = cls.read_uart_log(wifi_dut)
            if message in last_log:
                logger().info(f"Saw UART message {message!r}")
                return last_log
            time.sleep(poll_sec)
        raise AssertionError(
            f"DUT did not print {message!r} within {timeout_sec}s after UART open. "
            f"CLI commands were not started. Last UART log:\n{last_log}"
        )

    @staticmethod
    def save_uart_log(log_text, test_name):
        """Save UART log under reports/<test_name>.txt."""
        logger().info(f"DUT UART log:\n{log_text}")
        reports_dir = os.path.join(".", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        uart_log_file = os.path.join(reports_dir, f"{test_name}.txt")
        with open(uart_log_file, "w", encoding="utf-8", errors="replace") as f:
            f.write(log_text)
        logger().info(f"UART console logs saved to: {uart_log_file}")
        return uart_log_file

    @classmethod
    def extract_dut_ip_from_log(cls, log_text, pattern=None):
        """
        Extract DUT IPv4 from sample-app UART log text/file contents.

        Default pattern matches enterprise_client print:
          IP address of the client: <a.b.c.d>
        """
        regex = pattern or cls.DEFAULT_IP_LOG_PATTERN
        match = re.search(regex, log_text)
        return match.group(1) if match else None

    @classmethod
    def extract_dut_ipv6_from_log(cls, log_text, pattern=None):
        """
        Extract DUT global IPv6 from sample-app UART log.

        Matches wifi_net_dual_stack_nwp_m4 print_ip_addresses():
          IPv6 Address: <inet_ntop6>
        Also accepts a bare colon-hex address after the label on the next line.
        """
        regex = pattern or cls.DEFAULT_IPV6_LOG_PATTERN
        match = re.search(regex, log_text or "", re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".")
        # Fallback: first global-looking IPv6 (skip fe80:: link-local).
        for candidate in re.findall(
            r"\b([0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,7})\b",
            log_text or "",
        ):
            lowered = candidate.lower()
            if lowered.startswith("fe80:"):
                continue
            if "::" in candidate or candidate.count(":") >= 2:
                return candidate
        return None

    _SNTP_MONTHS = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }

    @classmethod
    def parse_sntp_dut_fields(cls, log_text):
        """Extract SNTP date, IP version, and server address from DUT UART text.

        The date line looks like ``Nov 4, 2026 7:48:1.907 UTC``. A non-printable
        byte may sit in front of the month name. Time is ignored.
        IP version is ``Got Server IP version as : 4``.
        The server is ``IPv4 Address is : a.b.c.d`` (or the IPv6 line).
        """
        text = log_text or ""
        date_match = re.search(
            r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+(\d{1,2}),\s+(\d{4})\b",
            text,
        )
        version_match = re.search(
            r"Got Server IP version as\s*:\s*(\d+)",
            text,
        )
        server_match = re.search(
            r"IPv4 Address is\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})",
            text,
        )
        if not server_match:
            server_match = re.search(r"IPv6 Address is\s*:\s*(\S+)", text)
        sntp_date = None
        if date_match:
            sntp_date = date(
                int(date_match.group(3)),
                cls._SNTP_MONTHS[date_match.group(1)],
                int(date_match.group(2)),
            )
        return {
            "date": sntp_date,
            "date_text": date_match.group(0) if date_match else None,
            "ip_version": int(version_match.group(1)) if version_match else None,
            "server_address": server_match.group(1) if server_match else None,
        }

    @classmethod
    def assert_sntp_date_ip_version_and_print_server(cls, log_text, day_tolerance=1):
        """Assert SNTP calendar date is within ±day_tolerance of today; IP version 4.

        DUT prints UTC (e.g. ``Nov 5, 2026 ... UTC``) while the harness may use
        local calendar day, so allow one day before/after by default.
        """
        fields = cls.parse_sntp_dut_fields(log_text)
        assert fields["date"] is not None, (
            "SNTP date not found in DUT log "
            "(expected 'Mon D, YYYY ...').\n"
            f"Full UART log:\n{log_text}"
        )
        today = date.today()
        delta_days = abs((fields["date"] - today).days)
        assert delta_days <= day_tolerance, (
            f"SNTP date {fields['date'].isoformat()} is outside "
            f"±{day_tolerance} day(s) of today's date {today.isoformat()} "
            f"(delta={delta_days} day(s)).\n"
            f"Full UART log:\n{log_text}"
        )
        assert fields["ip_version"] == 4, (
            f"SNTP server IP version was {fields['ip_version']}, expected 4.\n"
            f"Full UART log:\n{log_text}"
        )
        logger().info(f"SNTP server address: {fields['server_address']}")
        if fields["date"] == today:
            logger().info(
                f"SNTP date {fields['date'].isoformat()} matches today; "
                "IP version is 4"
            )
        else:
            logger().info(
                f"SNTP date {fields['date'].isoformat()} is within "
                f"±{day_tolerance} day of today {today.isoformat()} "
                f"(delta={delta_days}); IP version is 4"
            )
        return fields

    @staticmethod
    def read_log_file(uart_log_file):
        """Read previously saved UART log file as text."""
        with open(uart_log_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def ping(wifi_client, device_ip, ping_count=10, retries=3, retry_delay_sec=1):
        """Ping DUT IP from remote wifi_client. Returns True on success."""
        logger().info(f"Pinging DUT IP {device_ip} from remote client...")
        for attempt in range(retries):
            try:
                rc, stdout, stderr = wifi_client.interfaces.wifi.shell.execute(
                    f"sudo ping -c {ping_count} {device_ip}"
                )
                logger().info(
                    f"Ping attempt {attempt + 1}: rc={rc}\n"
                    f"{stdout.decode(errors='replace') if isinstance(stdout, bytes) else stdout}"
                )
                if rc == 0:
                    return True
            except Exception as ex:
                logger().warning(f"Ping attempt {attempt + 1} failed: {ex}")
            time.sleep(retry_delay_sec)
        return False

    @staticmethod
    def release_uart(wifi_dut):
        """Close DUT UART resources."""
        try:
            wifi_dut.interfaces.wifi.release_resources()
        except Exception as ex:
            logger().warning(f"UART release failed: {ex}")

    @staticmethod
    def erase_flash(flash_device):
        """Erase main flash on the device used for the sample-app binary."""
        if flash_device is None:
            return
        logger().info(f"Erasing firmware on device '{flash_device.name}'...")
        flash_device.erase_flash()

    @staticmethod
    def extract_firmware_versions_from_log(log_text):
        """
        Parse sample-app prints of the form:
          Firmware version is: 1611.2.17.5.0.0.34

        Returns list of version strings in order of appearance.
        """
        return re.findall(
            r"Firmware version is:\s*([0-9A-Fa-f]+\.[0-9]+(?:\.[0-9]+)*)",
            log_text or "",
        )

    @classmethod
    def assert_firmware_versions_changed(cls, log_text):
        """
        Require before/after OTA version prints and assert they differ.

        Returns:
            (fw_version_before, fw_version_after)
        """
        versions = cls.extract_firmware_versions_from_log(log_text)
        assert len(versions) >= 2, (
            "Expected at least two 'Firmware version is:' prints "
            "(before and after upgrade). "
            f"Found {len(versions)}: {versions}. Full UART log:\n{log_text}"
        )
        fw_version_before = versions[0]
        fw_version_after = versions[-1]
        logger().info(
            f"*** DUT firmware version before upgrade = {fw_version_before} ***"
        )
        logger().info(
            f"*** DUT firmware version after upgrade = {fw_version_after} ***"
        )
        assert fw_version_before != fw_version_after, (
            "Firmware upgrade did not change version "
            f"(before={fw_version_before}, after={fw_version_after}). "
            "OTA image may match the image already on the DUT."
        )
        return fw_version_before, fw_version_after

    @staticmethod
    def restore_default_firmware(fw_mgr=None, flash_device=None):
        """
        Restore manifest default NWP firmware (load_binary).

        Falls back to erase_flash if load_default_firmware fails.
        """
        if fw_mgr is None:
            fw_mgr = FirmwareManager.get_instance()
        try:
            logger().info("Restoring default firmware from manifest load_binary...")
            fw_mgr.load_default_firmware()
        except Exception as ex:
            logger().warning(f"Default firmware restore failed: {ex}")
            SampleAppHelper.erase_flash(flash_device)

    @staticmethod
    def get_harness_wifi_flag(flag_name, default=None):
        """Read a boolean/flag from harness defaults.wifi (e.g. validate_dut_logs)."""
        value = UtfConfig.instance().defaults["wifi"].get(flag_name, default)
        logger().info(
            f"\n **** Fetching user define {flag_name} flag value = "
            f"{value} from Harness file ****"
        )
        return value

    @staticmethod
    def get_firmware_app_name(request):
        """
        Read app name from @pytest.mark.firmware_app("<name>").

        Does not flash; pair with flash_and_boot_sample_app() when loading
        without the firmware_loader fixture.
        """
        mark = request.node.get_closest_marker("firmware_app")
        assert mark is not None and mark.args, (
            "Test must declare @pytest.mark.firmware_app(\"<manifest_app_name>\")"
        )
        app_name = mark.args[0]
        logger().info(f"firmware_app marker resolved to '{app_name}'")
        return app_name

    @classmethod
    def run_crypto_sample_app(
        cls, request, wiseconnect_duts, wifi_dut, expected_logs, wait_sec=20
    ):
        """
        Flash/boot a crypto sample app, save UART logs, and optionally assert expected prints.

        No access point or sniffer required. App name comes from firmware_app marker.
        """
        test_name = request.node.name
        app_name = cls.get_firmware_app_name(request)
        fw_mgr = FirmwareManager.get_instance()
        flash_device = None
        validate_dut_logs = cls.get_harness_wifi_flag("validate_dut_logs")

        try:
            logger().info(f"Flashing and booting sample-app '{app_name}'...")
            flash_device = cls.flash_and_boot_sample_app(
                fw_mgr, wiseconnect_duts, wifi_dut, app_name
            )
            time.sleep(wait_sec)

            log_text = cls.read_uart_log(wifi_dut)
            cls.save_uart_log(log_text, test_name)

            if validate_dut_logs:
                for expected in expected_logs:
                    assert expected in log_text, (
                        f"Expected print '{expected}' not found. "
                        f"Full UART log:\n{log_text}"
                    )
            else:
                logger().info(
                    "Skipping DUT log asserts because validate_dut_logs is not "
                    "enabled in harness defaults.wifi"
                )

            logger().info(f"{test_name} completed successfully")
        finally:
            cls.release_uart(wifi_dut)
            cls.erase_flash(flash_device)

    @staticmethod
    def mqtt_wait_connected(
        mqtt_client, mqtt_server=None, timeout_s=30, poll_sec=0.5, reconnect=True
    ):
        """
        Block until the host MQTT client reports CONNACK.

        mqtt_client_connect_to_server() returns right after loop_start(); the
        CONNACK can arrive several seconds later (8s seen when Mosquitto had
        just started). Poll mqtt_client_is_connected instead of sleeping a
        fixed time. If still not connected after timeout_s and mqtt_server is
        given, reconnect once and wait again.
        """
        mqtt = mqtt_client.interfaces.mqtt

        def _wait():
            sw = Stopwatch()
            while sw.elapsed_sec < timeout_s:
                try:
                    if mqtt.mqtt_client_is_connected:
                        logger().info(
                            f"Host MQTT client connected after {sw.elapsed_sec:.1f}s"
                        )
                        return True
                except Exception as ex:
                    logger().debug(f"mqtt_client_is_connected probe failed: {ex}")
                time.sleep(poll_sec)
            return False

        if _wait():
            return True
        if reconnect and mqtt_server is not None:
            logger().warning(
                f"Host MQTT client not connected within {timeout_s}s; reconnecting once"
            )
            mqtt.mqtt_client_connect_to_server(server=mqtt_server.interfaces.mqtt)
            if _wait():
                return True
        raise RuntimeError(
            f"Host MQTT client did not connect to broker within {timeout_s}s"
        )

    @staticmethod
    def mqtt_subscribe(
        mqtt_client,
        topic,
        qos=0,
        timeout_s=30,
        retries=3,
        retry_delay_sec=2,
        connect_timeout_s=30,
    ):
        """
        Subscribe host MQTT client with longer timeout and retries.

        Waits for CONNACK before every attempt so retries are not burned while
        the paho loop is still connecting (seen as 'Cannot subscribe when not
        connected to server' x3 in ~4s, CONNACK arriving at ~8s).
        """
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                SampleAppHelper.mqtt_wait_connected(
                    mqtt_client, timeout_s=connect_timeout_s, reconnect=False
                )
                logger().info(
                    f"MQTT subscribe attempt {attempt}/{retries} "
                    f"topic='{topic}' qos={qos} timeout_s={timeout_s}"
                )
                mqtt_client.interfaces.mqtt.mqtt_client_subscribe(
                    topic=topic, qos=qos, timeout_s=timeout_s
                )
                return
            except Exception as ex:
                last_error = ex
                logger().warning(f"MQTT subscribe attempt {attempt} failed: {ex}")
                time.sleep(retry_delay_sec)
        raise RuntimeError(
            f"MQTT subscribe to '{topic}' failed after {retries} attempts: {last_error}"
        )

    @staticmethod
    @retry(Exception, delay=10, tries=3)
    def aws_connect_from_third_party_device(aws_iot_client):
        """Connect third-party-device aws_iot_client to AWS IoT (c19548-style)."""
        logger().info("Connecting to aws server from aws_iot_client")
        status = aws_iot_client.interfaces.aws_iot.client._mqtt_core._client_status.get_status()
        if status != ClientStatus.IDLE:
            logger().info(
                f"Third-party AWS client status is {status}, disconnecting before reconnect"
            )
            try:
                aws_iot_client.interfaces.aws_iot.aws_iot_disconnect()
                time.sleep(5)
            except Exception as err:
                logger().warning(
                    f"Third-party AWS disconnect before reconnect failed: {err}"
                )
        aws_iot_client.interfaces.aws_iot.aws_iot_connect()
        time.sleep(5)
        status = aws_iot_client.interfaces.aws_iot.client._mqtt_core._client_status.get_status()
        assert status == ClientStatus.STABLE, (
            f"Connecting to AWS server from aws_iot_client is failed, status={status}"
        )

    @staticmethod
    @retry(Exception, delay=10, tries=3)
    def aws_subscribe_from_third_party_device(aws_iot_client, topic, qos=Si91xAwsQos.QOS0):
        """Subscribe third-party-device aws_iot_client to an AWS IoT topic."""
        logger().info(
            f"\n\n *** aws_iot_client is Subscribing on topic '{topic}' "
            f"and QOS:'{qos}'*** \n\n"
        )
        aws_iot_client.interfaces.aws_iot.received_messages.clear()
        aws_iot_client.interfaces.aws_iot.aws_iot_subscribe(topic, qos=qos)
        status = aws_iot_client.interfaces.aws_iot.client._mqtt_core._client_status.get_status()
        assert status == ClientStatus.STABLE, (
            f"Subscribe on topic:'{topic}' is failed from aws_iot_client"
        )

    @staticmethod
    @retry(Exception, delay=5, tries=5)
    def aws_publish_from_third_party_device(
        aws_iot_client, topic, message, qos=Si91xAwsQos.QOS0
    ):
        """Publish from third-party-device aws_iot_client to an AWS IoT topic."""
        try:
            status = (
                aws_iot_client.interfaces.aws_iot.client._mqtt_core._client_status.get_status()
            )
            assert status == ClientStatus.STABLE, (
                f"Publish on topic:'{topic}' is failed from aws_iot_client"
            )
        except AssertionError:
            SampleAppHelper.aws_connect_from_third_party_device(aws_iot_client)
        if isinstance(message, list):
            for i, msg in enumerate(message):
                logger().info(
                    f"\naws_iot_client publishing message{i + 1} on topic:'{topic}' "
                    f"\nQOS:'{qos}'\nMessage{i + 1} with length:'{len(msg)} bytes'"
                    f"\nMessage{i + 1} is:'{msg}'"
                )
                aws_iot_client.interfaces.aws_iot.aws_iot_publish(topic, msg, qos=qos)
                time.sleep(5)
        else:
            aws_iot_client.interfaces.aws_iot.aws_iot_publish(topic, message, qos=qos)

    @staticmethod
    def aws_validate_messages_from_third_party_device(
        aws_iot_client, topic, qos, messages, topic_1=None, topic_2=None, wait_time=10
    ):
        """
        Pass if each expected DUT payload appears at least once among third-party
        device received AWS messages.

        Shared AWS topics may have traffic from other devices; those extras are
        ignored. Does not require ordered 1:1 matching of every received packet.
        """
        del topic_1, topic_2, qos  # kept for call-site compatibility
        expected = messages if isinstance(messages, (list, tuple)) else [messages]

        logger().info(
            "\n *** Validating DUT AWS payload(s) present among "
            "third-party-device receives ***"
        )
        time.sleep(wait_time)

        recv_messages = aws_iot_client.interfaces.aws_iot.get_received_messages()
        logger().info(
            f"Third-party device received {len(recv_messages)} message(s) total"
        )

        received_payloads = []
        for count, recv in enumerate(recv_messages):
            try:
                payload = recv.payload.decode()
            except Exception:
                payload = str(recv.payload)
            received_payloads.append(payload)
            logger().info(
                f"Received message {count + 1}: payload={payload!r} "
                f"topic={getattr(recv, 'topic', None)!r} "
                f"qos={getattr(recv, 'qos', None)!r}"
            )

        missing = []
        for expected_payload in expected:
            if expected_payload in received_payloads:
                logger().info(
                    f"Found expected DUT payload {expected_payload!r} "
                    f"on topic {topic!r} (other publishers ignored)"
                )
            else:
                missing.append(expected_payload)

        assert not missing, (
            f"Expected DUT payload(s) not found among third-party-device receives: "
            f"{missing}. All received payloads: {received_payloads}"
        )
        logger().info("AWS DUT payload validation passed (presence check)")

    @staticmethod
    def aws_classic_shadow_topics(thing_name: str) -> dict:
        """Classic Device Shadow MQTT topic names for a Thing."""
        base = f"$aws/things/{thing_name}/shadow"
        return {
            "update": f"{base}/update",
            "update_accepted": f"{base}/update/accepted",
            "update_rejected": f"{base}/update/rejected",
            "update_delta": f"{base}/update/delta",
            "update_documents": f"{base}/update/documents",
        }

    @staticmethod
    def aws_validate_payload_contains_from_third_party_device(
        aws_iot_client, substrings, wait_time=10
    ):
        """
        Pass if each substring appears in at least one third-party received payload.

        Used for Device Shadow JSON where exact full-document match is brittle
        (temperature changes, shared Thing traffic).
        """
        expected = substrings if isinstance(substrings, (list, tuple)) else [substrings]
        logger().info(
            "\n *** Validating AWS payload substrings among third-party receives ***"
        )
        time.sleep(wait_time)

        recv_messages = aws_iot_client.interfaces.aws_iot.get_received_messages()
        logger().info(
            f"Third-party device received {len(recv_messages)} message(s) total"
        )

        received_payloads = []
        for count, recv in enumerate(recv_messages):
            try:
                payload = recv.payload.decode()
            except Exception:
                payload = str(recv.payload)
            received_payloads.append(payload)
            logger().info(
                f"Received message {count + 1}: payload={payload!r} "
                f"topic={getattr(recv, 'topic', None)!r}"
            )

        combined = "\n".join(received_payloads)
        missing = [s for s in expected if s not in combined]
        assert not missing, (
            f"Expected substring(s) not found in third-party AWS receives: {missing}. "
            f"All received payloads: {received_payloads}"
        )
        logger().info(
            f"AWS payload substring validation passed for {list(expected)!r}"
        )

    @staticmethod
    def aws_cleanup_third_party_device(aws_iot_client, topic=None):
        """Unsubscribe (optional topic or list) and disconnect third-party aws_iot_client."""
        topics = []
        if topic is None:
            topics = []
        elif isinstance(topic, (list, tuple)):
            topics = list(topic)
        else:
            topics = [topic]
        for one_topic in topics:
            try:
                aws_iot_client.interfaces.aws_iot.aws_iot_unsubscribe(one_topic)
            except Exception as ex:
                logger().warning(f"AWS unsubscribe cleanup failed ({one_topic}): {ex}")
        try:
            aws_iot_client.interfaces.aws_iot.aws_iot_disconnect()
        except Exception as ex:
            logger().warning(f"AWS disconnect cleanup failed: {ex}")

    @staticmethod
    def azure_device_id_from_client(azure_iot_client) -> str:
        """DeviceId from azure_iot harness device connection string / config."""
        device_iface = azure_iot_client.interfaces.device
        device_id = device_iface.config.get("device_id")
        if device_id:
            return device_id
        conn = device_iface.config.get("connection_string_device") or ""
        match = re.search(r"DeviceId=([^;]+)", conn)
        assert match, (
            "Could not parse DeviceId from azure_iot device config "
            f"(connection_string_device={conn!r})"
        )
        return match.group(1)

    @staticmethod
    def azure_start_receiving_d2c(azure_iot_client, duration=45):
        """
        Clear hub receives and open Event Hub consumer (C19515-style).

        Returns the context manager from hub.start_receiving_events.
        Note: AzureIoTHub sleeps `duration` before yield while the consumer
        thread is already running — flash/boot the DUT before entering so
        telemetry is captured during that window.
        """
        azure_iot_client.interfaces.hub.received_messages.clear()
        logger().info(
            f"Starting Azure IoT Hub Event Hub receive (duration={duration}s)..."
        )
        return azure_iot_client.interfaces.hub.start_receiving_events(
            duration=duration
        )

    @staticmethod
    def azure_validate_hub_received_contains(azure_iot_client, substrings):
        """
        Pass if each substring appears in at least one hub D2C received payload.

        Mirrors C19515 presence check against hub.received_messages (sample app
        publishes 'Hello World : N !' telemetry).
        """
        expected = (
            substrings if isinstance(substrings, (list, tuple)) else [substrings]
        )
        received = list(azure_iot_client.interfaces.hub.received_messages)
        logger().info(
            f"Azure hub received {len(received)} D2C message(s): {received}"
        )
        combined = "\n".join(str(m) for m in received)
        missing = [s for s in expected if s not in combined]
        assert not missing, (
            f"Expected substring(s) not found in Azure hub D2C receives: {missing}. "
            f"All received payloads: {received}"
        )
        logger().info(
            f"Azure hub D2C substring validation passed for {list(expected)!r}"
        )

    @staticmethod
    def azure_send_c2d_from_hub(azure_iot_client, message, device_id=None):
        """Send cloud-to-device message via IoT Hub (C19515 send_msg_from_cloud)."""
        if device_id is None:
            device_id = SampleAppHelper.azure_device_id_from_client(azure_iot_client)
        logger().info(
            f"Sending Azure C2D to device_id={device_id!r}: {message!r}"
        )
        azure_iot_client.interfaces.hub.send_message_to_device(device_id, message)

    @staticmethod
    def azure_cleanup_third_party(azure_iot_client):
        """Disconnect azure_iot device interface used by the third-party fixture."""
        try:
            azure_iot_client.interfaces.device.disconnect()
        except Exception as ex:
            logger().warning(f"Azure device disconnect cleanup failed: {ex}")

    @staticmethod
    def resolve_dut_ip_from_log(log_text, fallback="192.168.50.134"):
        """Prefer DUT IPv4 from UART; else use lab DHCP fallback."""
        device_ip = SampleAppHelper.extract_dut_ip_from_log(
            log_text, pattern=r"(192\.168\.50\.\d{1,3})"
        )
        if not device_ip:
            device_ip = SampleAppHelper.extract_dut_ip_from_log(log_text)
        if not device_ip:
            logger().info(
                f"DUT IP not found in UART log; using fallback {fallback}"
            )
            return fallback
        logger().info(f"DUT IP from UART log: {device_ip}")
        return device_ip

    @staticmethod
    def resolve_dut_ipv6_from_log(log_text, fallback=None):
        """Prefer DUT IPv6 from UART 'IPv6 Address:' print; optional fallback."""
        device_ip = SampleAppHelper.extract_dut_ipv6_from_log(log_text)
        if not device_ip:
            if fallback:
                logger().info(
                    f"DUT IPv6 not found in UART log; using fallback {fallback}"
                )
                return fallback
            return None
        logger().info(f"DUT IPv6 from UART log: {device_ip}")
        return device_ip

    @staticmethod
    def iperf_start_tcp_server(net_perf_client, host_ip, port=5001, time_out=90):
        """Start remote iPerf TCP sink (DUT TX / send_data_to_tcp_server)."""
        logger().info(f"Starting iPerf TCP server on {host_ip}:{port}...")
        net_perf_client.interfaces.net_perf.init_server(
            host_ip=host_ip,
            device_ip=host_ip,
            protocol=IperfConstants.TCP,
            time_out=time_out,
            host={"TCP": {"port": port}, "UDP": {"port": port + 1}},
        )
        net_perf_client.interfaces.net_perf.start()

    @staticmethod
    def iperf_start_tcp_client(net_perf_client, host_ip, device_ip, port=5004, time_out=90):
        """Start remote iPerf TCP client to DUT (DUT RX / receive_data_from_tcp_client)."""
        logger().info(
            f"Starting iPerf TCP client {host_ip} -> {device_ip}:{port}..."
        )
        net_perf_client.interfaces.net_perf.init_client(
            host_ip=host_ip,
            device_ip=device_ip,
            protocol=IperfConstants.TCP,
            time_out=time_out,
            host={"TCP": {"port": port}, "UDP": {"port": port + 1}},
            device={
                "TCP": {"port": port, "data_len": 1460},
                "UDP": {"port": port + 1, "data_len": 1472},
            },
        )
        net_perf_client.interfaces.net_perf.start()

    @staticmethod
    def iperf_client_log_kbytes(log_text):
        """Largest transfer in an iperf2 client log, in KBytes. None if absent."""
        best = None
        for amount, unit in re.findall(
            r"([\d.]+)\s+(GBytes|MBytes|KBytes|Bytes)\b",
            log_text or "",
        ):
            mult = {
                "Bytes": 1.0 / 1024.0,
                "KBytes": 1.0,
                "MBytes": 1024.0,
                "GBytes": 1024.0 * 1024.0,
            }[unit]
            kbytes = float(amount) * mult
            if best is None or kbytes > best:
                best = kbytes
        return best

    @staticmethod
    def _shell_text(value):
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return value or ""

    @staticmethod
    def iperf_tcp_client_on_station(
        wifi_client,
        device_ip,
        port=5001,
        time_out=20,
    ):
        """
        Run ``iperf -c`` on the wifi_client that joined the DUT SoftAP.

        ``net_perf`` launches iperf inside the UTF container on the lab LAN.
        A SoftAP TCP listener only completes the handshake with a peer on the
        AP subnet (the associated station). Ping already runs on that station;
        this sends the TCP client from the same place, bound to its SoftAP IP.

        Returns (bind_ip, combined stdout/stderr).
        """
        bind_ip = wifi_client.interfaces.wifi.get_ip_address()
        shell = wifi_client.interfaces.wifi.shell
        command = (
            f"iperf -c {device_ip} -p {int(port)} -B {bind_ip} "
            f"-t {int(time_out)} -i 1"
        )
        logger().info(
            f"Starting iPerf TCP client on wifi_client "
            f"{bind_ip} -> {device_ip}:{port}: {command}"
        )
        try:
            shell.execute(
                "bash -c \"pkill -f 'iperf -c' || true\"",
                timeout=15,
            )
        except Exception as ex:
            logger().warning(f"wifi_client iPerf pre-clean failed: {ex}")
        rc, stdout, stderr = shell.execute(
            command, timeout=int(time_out) + 45
        )
        log_text = (
            SampleAppHelper._shell_text(stdout)
            + SampleAppHelper._shell_text(stderr)
        )
        logger().info(f"wifi_client iPerf rc={rc}\n{log_text}")
        return bind_ip, log_text

    @staticmethod
    def iperf_stop_on_station(wifi_client):
        """Stop a leftover iperf client on the SoftAP station."""
        try:
            wifi_client.interfaces.wifi.shell.execute(
                "bash -c \"pkill -f 'iperf -c' || true\"",
                timeout=15,
            )
        except Exception as ex:
            logger().warning(f"wifi_client iPerf stop failed: {ex}")

    @staticmethod
    def assert_station_iperf_tcp_transfer(label, log_text):
        """Pass when the station iperf client sent payload (KBytes > 0)."""
        kbytes = SampleAppHelper.iperf_client_log_kbytes(log_text)
        logger().info(f"{label}: wifi_client iPerf sent {kbytes} KBytes")
        assert kbytes is not None and kbytes > 0, (
            f"{label} remote validation failed: wifi_client iPerf sent no "
            f"payload (transfer_kbytes={kbytes}). iperf log:\n{log_text}"
        )
        return kbytes

    @staticmethod
    def iperf_start_udp_server(
        net_perf_client, host_ip, port=5000, time_out=90, version=6
    ):
        """
        Start remote iPerf UDP sink (DUT UDP TX).

        Matches readme / Zephyr c792373: iperf -s -u [-V] -p <SERVER_PORT>.
        """
        logger().info(
            f"Starting iPerf UDP server on {host_ip}:{port} "
            f"(IPv{version})..."
        )
        net_perf_client.interfaces.net_perf.init_server(
            host_ip=host_ip,
            device_ip=host_ip,
            protocol=IperfConstants.UDP,
            time_out=time_out,
            version=version,
            host={"TCP": {"port": port + 1}, "UDP": {"port": port}},
        )
        net_perf_client.interfaces.net_perf.start()

    @staticmethod
    def iperf_start_udp_client(
        net_perf_client,
        host_ip,
        device_ip,
        port=5007,
        time_out=30,
        version=6,
        bandwidth="20M",
    ):
        """
        Start remote iPerf UDP client to DUT (DUT UDP RX server).

        Matches dual_stack readme: iperf -c <DUT_IP> -u [-V] -p <LISTENING_PORT>.

        Pass per-call server/client_options dicts so concurrent dual-stack
        clients do not mutate shared harness net_perf defaults (which caused
        both sockets to use the last port, e.g. 5009/5009).
        """
        logger().info(
            f"Starting iPerf UDP client {host_ip} -> {device_ip}:{port} "
            f"(IPv{version}, bw={bandwidth})..."
        )
        net_perf_client.interfaces.net_perf.init_client(
            host_ip=host_ip,
            device_ip=device_ip,
            protocol=IperfConstants.UDP,
            time_out=time_out,
            version=version,
            bandwidth=bandwidth,
            # Fresh dicts per call — Iperf.init_iperf() does .update() in place.
            server_options={"interval": 1, "time": time_out},
            client_options={"interval": 1, "time": time_out},
            host={"TCP": {"port": port + 1}, "UDP": {"port": port}},
            device={
                "TCP": {"port": port + 1, "data_len": 1460},
                "UDP": {"port": port, "data_len": 1472},
            },
        )
        net_perf_client.interfaces.net_perf.start()

    @staticmethod
    def iperf_stop(net_perf_client):
        """Best-effort iPerf stop."""
        try:
            net_perf_client.interfaces.net_perf.stop()
        except Exception as ex:
            logger().warning(f"iPerf stop failed: {ex}")

    @staticmethod
    def _wifi_client_shell(wifi_client):
        wifi = wifi_client.interfaces.wifi
        if getattr(wifi, "shell", None) is not None:
            return wifi.shell
        return wifi_client.interfaces.linux_shell

    @staticmethod
    def set_static_ipv6(
        wifi_client,
        ipv6: str,
        interface: str = "eth1",
        prefix_len: int = 64,
    ):
        """
        Assign a static global IPv6 on the Pi NIC (lab eth1 by default).

        Disables accept_ra for the iface for the duration of the test so SLAAC
        does not fight the static address. Pair with restore_dynamic_ipv6().
        """
        shell = SampleAppHelper._wifi_client_shell(wifi_client)
        addr = f"{ipv6}/{int(prefix_len)}"
        logger().info(f"Setting static IPv6 {addr} on {interface}...")
        try:
            shell(f"sudo sysctl -w net.ipv6.conf.{interface}.accept_ra=0")
        except Exception as ex:
            logger().warning(f"accept_ra=0 on {interface} failed: {ex}")
        # replace is idempotent if the address is already present
        shell(f"sudo ip -6 addr replace {addr} dev {interface}")
        time.sleep(1)
        logger().info(f"Static IPv6 ready: {ipv6} on {interface}")

    @staticmethod
    def restore_dynamic_ipv6(
        wifi_client,
        ipv6: str,
        interface: str = "eth1",
        prefix_len: int = 64,
    ):
        """Remove the test static IPv6 and re-enable SLAAC/DHCPv6 on the NIC."""
        shell = SampleAppHelper._wifi_client_shell(wifi_client)
        addr = f"{ipv6}/{int(prefix_len)}"
        logger().info(
            f"Restoring dynamic IPv6 on {interface} (removing {addr})..."
        )
        try:
            shell(f"sudo ip -6 addr del {addr} dev {interface}")
        except Exception as ex:
            logger().warning(f"ip -6 addr del {addr} failed: {ex}")
        try:
            shell(f"sudo sysctl -w net.ipv6.conf.{interface}.accept_ra=1")
        except Exception as ex:
            logger().warning(f"accept_ra=1 on {interface} failed: {ex}")
        # Best-effort DHCPv6 renew; SLAAC will also resume with accept_ra=1.
        try:
            shell(f"sudo dhclient -6 -r {interface}", timeout=10)
        except Exception:
            pass
        try:
            shell(f"sudo dhclient -6 {interface}", timeout=15)
        except Exception as ex:
            logger().warning(
                f"dhclient -6 on {interface} failed (SLAAC may still apply): {ex}"
            )
        logger().info(f"Dynamic IPv6 restore attempted on {interface}")

    @staticmethod
    def free_local_tcp_port(port: int, settle_sec: float = 1.0):
        """
        Free a local TCP listen port so python_http can bind.

        UTF hosts often leave lighttpd/apache on :80; python_http then fails
        with OSError Errno 98 (Address already in use).
        """
        from utf.utils.subprocess_manager import SubprocessManager

        cmds = [
            f"fuser -k {int(port)}/tcp",
            "killall -q lighttpd",
            "killall -q apache2",
            "killall -q httpd",
        ]
        for cmd in cmds:
            try:
                rc, _stdout, stderr = SubprocessManager.simple_execute(
                    cmd, is_shell=True
                )
                if rc == 0:
                    logger().info(f"free_local_tcp_port({port}): ran '{cmd}'")
                elif stderr:
                    logger().debug(
                        f"free_local_tcp_port({port}): '{cmd}' rc={rc} "
                        f"stderr={stderr!r}"
                    )
            except Exception as ex:
                logger().debug(f"free_local_tcp_port({port}): '{cmd}' ignored: {ex}")
        if settle_sec:
            time.sleep(settle_sec)

    @staticmethod
    def remote_tcp_server_send_continuous(
        remote_socket, port, duration_sec=60, payload=None, accept_timeout_sec=90
    ):
        """
        TCP server that accepts DUT client then sends for duration_sec.

        Used for receive_data_from_tcp_server (iperf cannot drive continuous
        server-side TX the way this sample expects). Pattern from
        test_wifi_zephyr_tcp_open_send_close_socket_c792368 / c792370.

        Returns a dict with connected, packets, bytes, duration_sec, and port
        so the caller can pass/fail on remote bytes instead of DUT UART.
        """
        if payload is None:
            payload = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=100)
            )
        sock = remote_socket.interfaces.socket
        logger().info(
            f"Starting remote TCP server on port {port} "
            f"(send continuously for {duration_sec}s after DUT connect)..."
        )
        sock.start_server(port=port)
        sw_accept = Stopwatch()
        while sw_accept.elapsed_sec < accept_timeout_sec:
            if getattr(sock, "connected_tcp_socket", None) is not None:
                logger().info("DUT connected to remote TCP server (TCP_RX1)")
                break
            time.sleep(0.5)
        else:
            raise TimeoutError(
                f"DUT did not connect to remote TCP server on port {port} "
                f"within {accept_timeout_sec}s"
            )

        sw_send = Stopwatch()
        send_count = 0
        bytes_sent = 0
        while sw_send.elapsed_sec < duration_sec:
            try:
                sent = sock.send_data_tcp(payload, use_server_socket=True)
                if isinstance(sent, int) and sent >= 0:
                    bytes_sent += sent
                else:
                    raw = payload.encode() if isinstance(payload, str) else payload
                    bytes_sent += len(raw)
                send_count += 1
            except Exception as ex:
                logger().warning(f"Remote TCP send failed after {send_count} pkts: {ex}")
                break
            time.sleep(0.2)
        duration = sw_send.elapsed_sec
        logger().info(
            f"Remote TCP server sent {send_count} payload(s), "
            f"{bytes_sent} bytes, over {duration:.1f}s"
        )
        try:
            sock.socket_close_indication(1)
        except Exception:
            pass
        try:
            sock.stop()
        except Exception as ex:
            logger().warning(f"Remote TCP server stop failed: {ex}")
        return {
            "connected": True,
            "packets": send_count,
            "bytes": bytes_sent,
            "duration_sec": duration,
            "port": port,
        }

    @staticmethod
    def parse_multithread_socket_stats(log_text: str) -> dict:
        """
        Parse multithread_sockets UART totals and throughputs.

        Expected lines (thread name suffix TCP_TX / TCP_RX / TCP_RX1):
          Total bytes sent : <n> : TCP_TX
          Total bytes received : <n> : TCP_RX
          Total bytes received : <n> : TCP_RX1
          Throughput achieved @ <mbps> Mbps in <sec> sec successfully : socket id <id>
        """
        stats = {
            "TCP_TX": {"direction": "sent", "bytes": None, "throughput_mbps": None, "duration_sec": None, "socket_id": None},
            "TCP_RX": {"direction": "received", "bytes": None, "throughput_mbps": None, "duration_sec": None, "socket_id": None},
            "TCP_RX1": {"direction": "received", "bytes": None, "throughput_mbps": None, "duration_sec": None, "socket_id": None},
        }
        for thread_name, direction in (
            ("TCP_TX", "sent"),
            ("TCP_RX", "received"),
            ("TCP_RX1", "received"),
        ):
            byte_pat = (
                rf"Total bytes {direction}\s*:\s*(\d+)\s*:\s*{re.escape(thread_name)}\b"
            )
            byte_match = re.search(byte_pat, log_text)
            if byte_match:
                stats[thread_name]["bytes"] = int(byte_match.group(1))
                # Throughput print follows the Total bytes line for that thread.
                tail = log_text[byte_match.end() :]
                tp_match = re.search(
                    r"Throughput achieved\s*@\s*([0-9]+(?:\.[0-9]+)?)\s*Mbps"
                    r"\s*in\s*([0-9]+(?:\.[0-9]+)?)\s*sec"
                    r".*?socket id\s*(\d+)",
                    tail,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if tp_match:
                    stats[thread_name]["throughput_mbps"] = float(tp_match.group(1))
                    stats[thread_name]["duration_sec"] = float(tp_match.group(2))
                    stats[thread_name]["socket_id"] = int(tp_match.group(3))
        return stats

    @staticmethod
    def assert_multithread_bytes_gt_zero_and_print_throughput(
        log_text: str, assert_bytes: bool = True
    ):
        """Assert Total bytes > 0 on TCP_TX/TCP_RX/TCP_RX1; print throughput only."""
        stats = SampleAppHelper.parse_multithread_socket_stats(log_text)
        for thread_name in ("TCP_TX", "TCP_RX", "TCP_RX1"):
            entry = stats[thread_name]
            direction = entry["direction"]
            bytes_val = entry["bytes"]
            if assert_bytes:
                assert bytes_val is not None, (
                    f"Expected 'Total bytes {direction} : <n> : {thread_name}' "
                    f"not found in UART log.\nFull UART log:\n{log_text}"
                )
                assert bytes_val > 0, (
                    f"{thread_name}: Total bytes {direction} was {bytes_val}, "
                    f"expected > 0.\nFull UART log:\n{log_text}"
                )
            if bytes_val is not None:
                logger().info(
                    f"{thread_name}: Total bytes {direction} = {bytes_val}"
                )
            else:
                logger().info(
                    f"{thread_name}: Total bytes {direction} line not found"
                )
            if entry["throughput_mbps"] is not None:
                logger().info(
                    f"{thread_name}: Throughput achieved = "
                    f"{entry['throughput_mbps']:.2f} Mbps "
                    f"in {entry['duration_sec']:.3f} sec "
                    f"(socket id {entry['socket_id']})"
                )
            else:
                logger().info(
                    f"{thread_name}: Throughput line not found/parsed"
                )
        return stats

    @staticmethod
    def _iperf_transfer_kbytes(net_perf_client, is_client=False):
        """
        Parse an iPerf TCP log into total transferred KBytes.

        Interval transfers are normalized to KBytes by the iPerf parser
        (MBytes * 1024, Bytes / 1024). Returns
        (kbytes, avg_bandwidth_kbps). Either value is None when the log
        has no parseable output.
        """
        result = net_perf_client.interfaces.net_perf.process_output(
            is_client=is_client
        )
        if not result:
            return None, None
        transfer = result.get(IperfConstants.TRANSFER)
        bandwidth = result.get(IperfConstants.AVG_BANDWIDTH)
        kbytes = None if transfer is None else float(transfer)
        kbps = None if bandwidth is None else float(bandwidth)
        return kbytes, kbps

    @staticmethod
    def assert_iperf_remote_transfer(
        net_perf_client, label, remote_role="client", stop_first=True
    ):
        """
        Pass/fail one socket from the remote iPerf peer's own log.

        remote_role:
          "client" — remote iPerf -c sent payload to the DUT (DUT RX).
                     Pass when sent KBytes > 0.
          "server" — remote iPerf -s received payload from the DUT (DUT TX).
                     Pass when received KBytes > 0.

        Use when the DUT UART is interleaved by several threads and its
        'Listening on port' / 'Total bytes received' lines are unreliable.
        Returns (kbytes, avg_bandwidth_kbps).
        """
        remote_role = (remote_role or "client").lower()
        if remote_role not in ("client", "server"):
            raise ValueError(f"remote_role must be client/server, got {remote_role!r}")
        if stop_first:
            SampleAppHelper.iperf_stop(net_perf_client)
        kbytes, kbps = SampleAppHelper._iperf_transfer_kbytes(
            net_perf_client, is_client=(remote_role == "client")
        )
        verb = "sent" if remote_role == "client" else "received"
        kbps_text = "bandwidth n/a" if kbps is None else f"avg {kbps:.2f} Kbits/sec"
        logger().info(
            f"{label}: remote iPerf {remote_role} {verb} {kbytes} KBytes ({kbps_text})"
        )
        assert kbytes is not None and kbytes > 0, (
            f"{label} remote validation failed: remote iPerf {remote_role} "
            f"{verb} no payload (transfer_kbytes={kbytes})."
        )
        return kbytes, kbps

    @staticmethod
    def assert_multithread_remote_transfers(
        tx_net_perf,
        rx_net_perf,
        rx1_stats,
        host_ip,
        device_ip,
        tcp_tx_port=5001,
        tcp_rx_port=5004,
        tcp_rx1_port=5005,
    ):
        """
        Pass/fail for multithread_sockets from the remote peers.

        Worker UART prints interleave, so byte counts come from:
          TCP_TX  — iPerf server received DUT payload
          TCP_RX  — iPerf client sent payload to the DUT listener
          TCP_RX1 — python TCP server sent payload to the DUT client

        Stops both iPerf processes first so their logs are flushed.
        """
        SampleAppHelper.iperf_stop(tx_net_perf)
        SampleAppHelper.iperf_stop(rx_net_perf)

        tx_kbytes, tx_kbps = SampleAppHelper._iperf_transfer_kbytes(
            tx_net_perf, is_client=False
        )
        rx_kbytes, rx_kbps = SampleAppHelper._iperf_transfer_kbytes(
            rx_net_perf, is_client=True
        )
        rx1_stats = rx1_stats or {}
        rx1_bytes = int(rx1_stats.get("bytes") or 0)
        rx1_packets = int(rx1_stats.get("packets") or 0)
        rx1_duration = rx1_stats.get("duration_sec")

        def _kbps_text(kbps):
            if kbps is None:
                return "bandwidth n/a"
            return f"avg {kbps:.2f} Kbits/sec"

        logger().info(
            f"TCP_TX remote iPerf -s {host_ip}:{tcp_tx_port} received "
            f"{tx_kbytes} KBytes ({_kbps_text(tx_kbps)})"
        )
        logger().info(
            f"TCP_RX remote iPerf -c {device_ip}:{tcp_rx_port} sent "
            f"{rx_kbytes} KBytes ({_kbps_text(rx_kbps)})"
        )
        logger().info(
            f"TCP_RX1 remote TCP server {host_ip}:{tcp_rx1_port} sent "
            f"{rx1_bytes} bytes in {rx1_packets} packet(s) "
            f"over {rx1_duration}s"
        )

        assert tx_kbytes is not None and tx_kbytes > 0, (
            "TCP_TX remote validation failed: iPerf server "
            f"{host_ip}:{tcp_tx_port} received no DUT payload "
            f"(transfer_kbytes={tx_kbytes})."
        )
        assert rx_kbytes is not None and rx_kbytes > 0, (
            "TCP_RX remote validation failed: iPerf client sent no payload "
            f"to DUT {device_ip}:{tcp_rx_port} "
            f"(transfer_kbytes={rx_kbytes})."
        )
        assert rx1_bytes > 0, (
            "TCP_RX1 remote validation failed: python TCP server on "
            f"{host_ip}:{tcp_rx1_port} sent no payload to the DUT "
            f"(bytes={rx1_bytes}, packets={rx1_packets}, stats={rx1_stats})."
        )
