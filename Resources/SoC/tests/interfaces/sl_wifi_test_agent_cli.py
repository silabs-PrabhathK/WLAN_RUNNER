from contextlib import contextmanager
from utf_wiseconnect_3.tests.interfaces.sl_collections import SLCollections
from utf.utils.time_measurer import TimeMeasurer
from utf.interfaces.wifi import WiFiInterface, WiFiScanResult
from utf.interfaces.network import NetworkInterface
from utf.interfaces.cli import CLITransport, CLITransportException
from utf.utils.defaults import defaults
from utf.utils import mac_address_to_string
from utf.devices import Device
from utf.interfaces.http.server import WebServerInterface
from utf.interfaces.mqtt.client import MqttClientInterface
from utf_wiseconnect_3.tests.devices.si91x import Si91xPowerSaveModes, Si91xPowerSaveProcedureTypes, Si91xAesType, \
    Si91xSHA, Si91xHMAC, Si91xAesOperation, Si91xAesKeySize, Si91xKeyType, Si91xWrapIVMode, Si91xECDH, \
    Si91xECDHOperation, Si91xMdnsParams, Si91xTWTRescheduleParams, Si91xIpVersion, Si91xBSDSocketParams, Si91xIp, \
    Si91xRtsThreshold, Si91xWifiBand, Si91xBootOption, Si91xCryptoWrapMode, Si91xCryptoKeyType
from typing import Optional, Dict, Union, List, Callable, Tuple
import time
from collections import namedtuple
from socket import gethostbyname
import re
import threading

from . import AsyncIdentifiers, Protocol, AsyncEventIdentifiers
from . import TestAgentThreadStatus, TestAgentThreadResult
from base64 import b64decode, b64encode
from ..sl_status import SLStatus
from ..iot_errors import IOTStatus
from ..bsd_errors import BSDErrnoStatus
from ..lwip_errors import LwipBSDErrnoStatus
from ..lwip_errors import LwipIOTErrorStatus
from utf.interfaces.mqtt.server import MqttServer
from utf.utf_config import UtfConfig
from utf_wiseconnect_3.tests.devices.si91x import (
    Si91xOperatingMode,
    Si91xCoexMode,
    Si91xFeatureBitMap,
    Si91xTCPIPFeatureBitMap,
    Si91xCustomFeatureBitMap,
    Si91xExtCustomFeatureBitMap,
    Si91xBTFeatureBitMap,
    Si91xExtTCPIPFeatureBitMap,
    Si91xBLEFeatureBitMap,
    Si91xBLECustomFeatureBitMap,
    Si91xConfigFeatureBitMap,
    Si91xRegion,
    Si91xRegionCode,
    Si91xModuleType,
    Si91xCertificateType,
    Si91xInterface,
    Si91xApplicationProtocol,
    Si91xJoinFeatureBitMap,
    Si91xCertIdentifier,
    Si91xCustomSyncSockOptParms,
    Si91xTimeoutParams,
    Si91xBleDutyParams,
    Si91xBleConnParams,
    is_si91x_ncp_dut,
    apply_ncp_oper_mode_ext_custom_features,
    apply_ncp_oper_mode_ble_features,
)
from utf.interfaces.bluetooth.bluetooth_interface import (
    BluetoothInterface,
    BTRole,
    BTProfile,
    BTEvents,
    BLEPermissions,
    )
from queue import Queue, Empty as QueueEmpty
from retry import retry
from utf.utils.commander import reset_device
from utf.utils.firmware_manager import FirmwareManager
from utf.utils import get_tls_certificate_dir

MqttMessage = MqttClientInterface.MqttMessage

_MQTT_ASYNC_UART_HEADER_RE = re.compile(rb"F[0-9A-Fa-f]{4}\\")
_MQTT_UART_PAYLOAD_CONT_RE = re.compile(rb"^F[0-9A-Fa-f]{4}")



def create_interface(
        config, cli_transport, gpio_transport=None, reset="soft", device=None
        ) -> WiFiInterface:
    return SLWifiCLI(config, cli_transport, gpio_transport, reset, device)


class SLWifiOperatingModeOptions:
    def __init__(self, **kwargs):
        self.oper_mode = Si91xOperatingMode.Default
        self.coex_mode = Si91xCoexMode.Default
        self.features = Si91xFeatureBitMap.Default
        self.tcpip_features = Si91xTCPIPFeatureBitMap.Default
        self.custom_features = Si91xCustomFeatureBitMap.Default
        self.ext_custom_features = Si91xExtCustomFeatureBitMap.Default
        self.bt_features = Si91xBTFeatureBitMap.Default
        self.ext_tcpip_features = Si91xExtTCPIPFeatureBitMap.Default
        self.ble_features = Si91xBLEFeatureBitMap.Default
        self.ble_custom_ext_features = Si91xBLECustomFeatureBitMap.Default
        self.config_features = Si91xConfigFeatureBitMap.Default
        self.region_code = Si91xRegionCode.US
        self.keep_alive_timeout_value = Si91xTimeoutParams.keep_alive_timeout_value
        self.auth_assoc_timeout_value = Si91xTimeoutParams.auth_assoc_timeout_value
        self.active_chan_scan_timeout_value = Si91xTimeoutParams.active_chan_scan_timeout_value
        self.passive_chan_scan_timeout_value = Si91xTimeoutParams.passive_chan_scan_timeout_value
        self.enable_duty_cycle = Si91xBleDutyParams.enable_duty_cycle
        self.duty_cycle = Si91xBleDutyParams.duty_cycle
        self.rts_threshold = Si91xRtsThreshold.rts_threshold
        self.band = Si91xWifiBand.SL_SI91X_WIFI_BAND_2_4GHZ
        self.boot_option = Si91xBootOption.LOAD_NWP_FW


class TestAgentThreadRef:
    def __init__(self, type, status, identifier, index):
        self.index = index
        self.identifier = identifier
        self.status = status
        self.type = type


class AsyncEvent:
    def __init__(self):
        self.event_type = ""
        self.timestamp = 0
        self.event_data = None
        self.end_identifier_found = False
        self.start_identifier_found = False
        self.async_data = ""


class SLWifiCLI(WiFiInterface, NetworkInterface):
    ScanResult = namedtuple(
        "ScanResult", "rf_channel security_mode rssi network_type ssid bssid"
        )
    client_info = {"mac_address": [], "ip_address": []}
    mac_address_expression = re.compile(r"(?:[\da-fA-F]:?){12}")

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
            # assert(device != None, "Cannot create cli_transport. device is None")
            self.bus: CLITransport = device.create_interface(cli_transport)  # noqa
        else:
            self.bus = cli_transport
        self.bus.register_rx_data_observer(self.on_incoming_rx_data, override=False)
        self.inited = False
        self.associated = False
        self.networked = False
        self.power_save_mode = "high_performance"
        self.bt_power_save = False
        self.oper_mode_opts = SLWifiOperatingModeOptions()
        self.is_external_stack_enabled = False
        self.is_sl_net_enabled = False
        self._lock = threading.RLock()
        self.test_agent_thread_identifiers = ["A", "B", "C", "D", "E", "G", "H", "I"]
        self.test_agent_thread_index = -1
        self.test_agent_threads = {}
        self.inited_test_agent_threads = False
        self.test_agent_thread_enabled = False
        self.is_dut_bad_state = False
        self.last_retrieved_event_timestamp = 0
        self.ble_advertising = False
        self.ble_scanning = False
        self.ble_address = None
        self.enabled_twt = False
        self.enable_auto_twt = False
        self.device_commander_options = config.get('commander_options', None)
        self.region_code = Si91xRegionCode.US
        self.enable_duty_cycle = Si91xBleDutyParams.enable_duty_cycle
        self.duty_cycle = Si91xBleDutyParams.duty_cycle
        self.async_response_duration = 0
        self.aws_flags = {'topic': 'sdk_automation', 'subscribed': False, 'connected': False}
        self.azure_flags = {'topic': 'sdk_automation', 'subscribed': False, 'connected': False}
        self.certs_loaded = {'eap_cert': None, 'ca_cert': None, 'client_cert': None, 'server_cert': None,
                             'client_key': None, 'server_key': None}
        self.default_fw = False
        self.event_queues = {}
        if gpio_transport:
            self.gpio_bus = device.create_interface(gpio_transport)
        else:
            self.gpio_bus = None
        self.dut_mqtt_client_id_address = 0
        self.dut_http_server_webpage_address = 0
        self.add_hid_service = True
        self.lwip_socket_info = {
            "sockets": [],
        }
        self.sockets_info = {
            "sync_sockets": [],
            "async_sockets": []
            }
        self.mqtt_state_connected = None
        self.lwip_mqtt_state_connected = False
        self.ap_beaconing = False

    def _commander_reset(self):
        self.logger.warning("Reset the DUT through commander reset")
        reset_device(self.device_commander_options)
        time.sleep(5)

    @defaults("wifi")
    def init_test_agent_threads(self, thread_config=None):
        try:
            if thread_config is not None:
                self.test_agent_thread_enabled = True
                self.logger.info("Initializing Test Agent Threads")
                for protocol, test_agent_thread_config in thread_config.items():
                    self.logger.info(f"Creating Test Agent Threads for {protocol}")
                    for _ in range(0, test_agent_thread_config.get("count")):
                        self.__create_test_agent_thread(Protocol(protocol), test_agent_thread_config.get("stack_len"),
                                                        test_agent_thread_config.get("priority"))
                self.inited_test_agent_threads = True
        except Exception as e:
            self.deinit_test_agent_threads()
            raise RuntimeError(f"Error While Initializing Test Agent Threads {e}")

    def __create_test_agent_thread(self, type, stack_len, priority):
        self.test_agent_thread_index += 1
        test_agent_thread = TestAgentThreadRef(type=type, status=TestAgentThreadStatus.IDLE,
                                               identifier=self.test_agent_thread_identifiers[
                                                   self.test_agent_thread_index], index=self.test_agent_thread_index)
        self.test_agent_threads[test_agent_thread.identifier] = test_agent_thread
        self.initialize_thread(thread_id=test_agent_thread.index, stack_len=stack_len, priority=priority)

    def __get_test_agent_thread(self, type):
        for identifier in self.test_agent_thread_identifiers:
            if identifier in self.test_agent_threads:
                if self.test_agent_threads[identifier].type == type and self.test_agent_threads[
                    identifier].status not in [TestAgentThreadStatus.RUNNING, TestAgentThreadStatus.ASYNCTIMEOUT]:
                    return self.test_agent_threads[identifier]
        raise RuntimeError(
            f"There is no test agent thread initialized for {type} Or All test_agent_threads for {type} are in Running state")

    def __change_test_agent_thread_status(self, identifier, status: TestAgentThreadStatus):
        self.test_agent_threads[identifier].status = status

    def open_test_agent_threads(self):
        test_agent_threads = []
        for _, test_agent_thread in self.test_agent_threads.items():
            if test_agent_thread.status is not TestAgentThreadStatus.KILLED:
                test_agent_threads.append(test_agent_thread)
        return test_agent_threads

    def terminate_thread(self, thread_id, timeout=10, retries=2):
        try:
            status, data = self.issue_command(f"terminate {thread_id}", timeout=timeout, retries=retries)
            self.verify_status(status, SLStatus.SL_STATUS_OK)
        except Exception as error:
            self.logger.info(f"Error:{error}\nResetting device because of not receiving response within async timeout, "
                             f"even after '{retries}' retries")
            self.reset()

    def delete_all_test_agent_threads(self, timeout=10):
        for test_agent_thread in self.open_test_agent_threads():
            self.terminate_thread(test_agent_thread.index, timeout)
            self.__change_test_agent_thread_status(test_agent_thread.identifier, TestAgentThreadStatus.KILLED)

    def deinit_test_agent_threads(self):
        if self.is_dut_bad_state:
            self.logger.info("Resetting device because of not receiving response within async timeout")
            self.reset()
            self.is_dut_bad_state = False
        else:
            self.delete_all_test_agent_threads()
        self.test_agent_thread_index = -1
        self.test_agent_threads = {}
        self.test_agent_thread_enabled = False
        self.inited_test_agent_threads = False

    def _process_test_agent_thread_response(self, record: bytes, result, async_identifier,
                                            test_agent_thread_identifier, event_expected=None):
        data = record.decode(errors="ignore")
        self.__parse_global_async_event(data, result, async_identifier, event_expected)
        self.__parse_test_agent_thread_response(data, result, test_agent_thread_identifier)

    def __parse_global_async_event(self, data, result, identifiers, event_expected=None):
        if not result.start_identifier_found == True:
            async_data_pattern = r"(F)([0-9a-fA-F]{4})<\$\s([0-9a-fA-F]{8})\s+(.*)\r\n"
            match = re.search(async_data_pattern, data, re.DOTALL)
            if match:
                # async_thread_identifier = async_data_matches.group(1)
                # length_of_response = int(async_data_matches.group(2), 16)
                async_identifier = match.group(3)
                if async_identifier in identifiers:
                    async_data = match.group(4)
                    result.start_identifier_found = True
                    self.__parse_end_identifiers(async_data, result, event_expected)
            return
        if result.start_identifier_found and result.end_identifier_found == False:
            async_data_pattern = r"((F)([0-9a-fA-F]{4})?)+(.*)\r\n"
            match = re.search(async_data_pattern, data, re.DOTALL)
            if match:
                async_data = match.group(4)
                self.__parse_end_identifiers(async_data, result, event_expected)
            else:
                self.__parse_end_identifiers(data, result, event_expected)

            return

    def __parse_end_identifiers(self, async_data, result, event_expected=None):
        async_end_identifier = async_data[-2:]
        if async_end_identifier == "$>":
            result.async_data += async_data[:-2]
            result.end_identifier_found = True
        else:
            result.async_data = result.async_data + async_data
        if event_expected:
            if result.start_identifier_found and result.end_identifier_found:
                result.start_identifier_found = False
                result.end_identifier_found = False

    def __parse_test_agent_thread_response(self, data, result, identifier):
        status_data_pattern = r'([A-EG-Z])([0-9a-fA-F]{4})(.*)\r\n'
        match = re.search(status_data_pattern, data, re.DOTALL)
        if match:
            thread_identifier = match.group(1)
            length_of_response = int(match.group(2), 16)
            if thread_identifier == identifier:
                sync_data = match.group(3)
                if length_of_response == len(sync_data):
                    self.__split_sync_data_and_status(sync_data, result)

    def __split_sync_data_and_status(self, data, result):
        status_pattern = r'(.*)0x([0-9a-fA-F]+): \((\d+ms)\)'
        status_matches = re.search(status_pattern, data, re.DOTALL)
        if status_matches:
            result.sync_data += status_matches[1]
            result.status_code = f"0x{status_matches[2]}"
        else:
            result.sync_data += data

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
        retries += 1
        command_re = re.compile(".*\n0x(\\w*):(.*)\n", flags=re.DOTALL | re.ASCII)
        while True:
            try:
                with self._lock:
                    result = self.bus.write_line_and_expect(line, command_re, timeout)
                    if ignore_response:
                        return SLStatus.SL_STATUS_OK, ""
                    if result is None:
                        return SLStatus.SL_STATUS_TIMEOUT, ""
                    else:
                        result_match = command_re.search(result.decode(errors="ignore"))
                        if result_match:
                            status = SLStatus(int(result_match[1], 16))
                            return status, result
                        else:
                            return -1, result
            except CLITransportException as e:
                self.logger.warning(e.actual_response)
                raise e
            return -1, ""

    def issue_command_in_thread(self, line, protocol: Protocol, async_identifiers: list = [],
                                timeout: int = 2, async_timeout: int = 10, retries: int = 0, event_expected=None,
                                sleep_time=1) -> Tuple[
        SLStatus, bytes]:
        @retry(tries=retries + 1, delay=1)
        def _issue_command_in_thread():
            with self._lock:
                test_agent_thread = self.__get_test_agent_thread(protocol)

            command_issued_time = time.perf_counter_ns()

            result = TestAgentThreadResult()

            def on_incoming_rx_data(timestamp: int, record: bytes):
                self._process_test_agent_thread_response(record, result, async_identifiers,
                                                         test_agent_thread.identifier, event_expected=event_expected)

            try:
                with self._subscribe_to_rx(on_incoming_rx_data):
                    self.__change_test_agent_thread_status(test_agent_thread.identifier, TestAgentThreadStatus.RUNNING)

                    status, data = self.issue_command(
                        f"t {test_agent_thread.index} {test_agent_thread.identifier} {line}",
                        timeout, retries)
                    self.verify_status(status, SLStatus.SL_STATUS_OK)

                    since_time = command_issued_time

                    with TimeMeasurer() as t:
                        while since_time - command_issued_time <= async_timeout * 1000000000:
                            last_read_time = time.perf_counter_ns()

                            if result.status_code != "":
                                if event_expected:
                                    if event_expected in result.async_data:
                                        break
                                elif async_identifiers:
                                    # HTTPS GET body rides HTTP_EVENT (F...$>). Status alone can
                                    # arrive first; wait for $> like manual waits end_of_data.
                                    # Non-OK status: no body expected — return immediately.
                                    try:
                                        status_int = int(result.status_code, 16)
                                    except ValueError:
                                        status_int = -1
                                    if status_int != 0 or result.end_identifier_found:
                                        break
                                    time.sleep(sleep_time)
                                else:
                                    break
                            else:
                                time.sleep(sleep_time)

                            since_time = last_read_time
                    self.async_response_duration = t.duration
                self.logger.info(f"result.status_code: {result.status_code}")
                if (result.status_code == "") or (result.status_code == "-0x1"):
                    status = SLStatus.SL_STATUS_TIMEOUT
                    self.logger.info(
                        f"DUT has entered into bad state as status response is not received with in async timeout of {async_timeout} sec for thread {test_agent_thread.identifier}. Retry/Reset required")
                    self.is_dut_bad_state = True
                else:
                    status = SLStatus(int(result.status_code, 16))
                    self.is_dut_bad_state = False

            except CLITransportException as e:
                self.logger.warning(e.actual_response)
                raise e
            finally:
                self.__change_test_agent_thread_status(test_agent_thread.identifier, TestAgentThreadStatus.IDLE)

            return status, (result.async_data + result.sync_data).encode()

        return _issue_command_in_thread()

    def get_async_events(self, since_time=None, update_last_retrieved_timestamp=True) -> List[AsyncEvent]:
        if since_time is None:
            since_time = self.last_retrieved_event_timestamp
        next_time = time.perf_counter_ns()
        events: List[AsyncEvent] = []
        for timestamp, record in self._get_async_messages(since_time):
            if len(events) == 0:
                event = self.__create_event(timestamp, record)
                events = self.__extend_events(event, events)
            else:
                last_event = events[len(events) - 1]
                if last_event.end_identifier_found:
                    event = self.__create_event(timestamp, record)
                    events = self.__extend_events(event, events)
                else:
                    self.__update_event(timestamp, record, last_event)
        if update_last_retrieved_timestamp:
            self.last_retrieved_event_timestamp = next_time
        return events

    def parse_and_get_whitelist_data(self, event_data: bytes):
        event_data_string = event_data.decode()
        adv_data = re.search(r'adv_data:(.*?)-\n', event_data_string).group(1)
        adv_data_list = adv_data.split('-')
        whitelist_string = ""
        for ascii_code in adv_data_list:
            if ascii_code != '0':
                whitelist_string = whitelist_string + chr(int(ascii_code))
        return whitelist_string

    def _get_async_messages(self, since_time: int, preamble: Optional[bytes] = None):
        records = self.bus.get_input_log()
        start_timestamp = self.bus.start_timestamp
        for timestamp, record in [
            record
            for record in records
            if preamble is None or record[1].startswith(preamble)
            ]:
            timestamp += start_timestamp
            if timestamp >= since_time:
                yield timestamp, record

    def _get_async_mqtt_messages(self, since_time: int, preamble: Optional[bytes] = None):
        """
              Retrieves asynchronous MQTT messages from the input log since a specified timestamp.

              Args:
                  since_time (int): The timestamp from which to retrieve messages.
                  preamble (Optional[bytes]): Optional preamble to filter messages.

              Yields:
                  Tuple[int, bytes]: A tuple containing the timestamp and the message record.
        """

        records = self.bus.get_input_log()
        start_timestamp = self.bus.start_timestamp
        for timestamp, record in [
            record
            for record in records
            if preamble is None or record[1].startswith(preamble) or preamble in record[1]
        ]:
            timestamp += start_timestamp
            if timestamp >= since_time:
                yield timestamp, record

    def __create_event(
            self, timestamp: int, record: bytes,
            ) -> Optional[AsyncEvent]:
        temp_record = self.__sanitize(record, [b" ", b">", b"\r", b"\n", b" "])
        for async_event_identifier in list(AsyncEventIdentifiers):
            event = AsyncEvent()
            self.__parse_global_async_event(temp_record.decode('utf-8', errors='ignore'), event, [str(async_event_identifier.value)])
            if event.start_identifier_found:
                event.timestamp = timestamp
                event.event_type = async_event_identifier
                event.event_data = event.async_data
                return event

    def __update_event(self, timestamp: int, record: bytes, event: AsyncEvent):
        temp_record = self.__sanitize(record, [b" ", b">", b"\r", b"\n", b" "])
        self.__parse_global_async_event(temp_record.decode('utf-8', errors='ignore'), event, [str(event.event_type.value)])
        event.event_data = event.async_data

    def __extend_events(self, event, events):
        if event is not None:
            if event.event_type == AsyncEventIdentifiers.FIRMWARE_LOG:
                # TODO: Handle this for Firmware logs similar to RS9116.
                pass
            else:
                events.append(event)
        return events

    def __sanitize(self, record, chars: [bytes]):
        for ch in chars:
            if record.startswith(ch):
                record = record[1:]
        return record

    def get_command_data(self, response: bytes) -> bytes:
        if self.test_agent_thread_enabled:
            return response
        patterns = [
            re.compile(b".*?\n(.*)\r?\n0x\\w*:.*", flags=re.DOTALL | re.ASCII),
            re.compile(b".*?\r\n(.*)\r\n0x\w*:.*", flags=re.DOTALL),
            # Post-OTA bare CLI: wifi.get_fw_version\r<payload>\n0x...
            re.compile(b".*?\r(.*)\n0x\w*:.*", flags=re.DOTALL | re.ASCII),
        ]
        for data_re in patterns:
            match = data_re.match(response)
            if match:
                return match[1]
        status_match = re.search(b"0x[0-9a-fA-F]+:.*", response)
        if status_match:
            payload = response[:status_match.start()].strip(b"\r\n ")
            echo_sep = re.match(b"^[^\r\n]*[\r\n]+", payload)
            if echo_sep:
                payload = payload[echo_sep.end():].strip(b"\r\n ")
            if payload:
                return payload
        return None

    def read_result_async(
            self,
            async_timeout: int,
            async_events: list,
            async_expected: str,
            command_issued_time=None,
            line: str = None,
            timeout: int = 0
            ) -> [bytes]:
        if command_issued_time is None:
            command_issued_time = time.perf_counter_ns()
        success = False
        result = ""
        async_timeout_ns = async_timeout * 1000000000
        since_time = command_issued_time
        while since_time - command_issued_time <= async_timeout_ns:
            time.sleep(1)
            last_read_time = time.perf_counter_ns()
            events = self.get_async_events(
                since_time=since_time, update_last_retrieved_timestamp=False
                )
            for ev in events:
                result += ev.event_data
                if ev.event_type in async_events:
                    if async_expected in ev.event_data:
                        success = True
                        break
            if success:
                break
            since_time = last_read_time
        if not success:
            e = f"Expected async event not found :{async_expected} in the async response"
            raise e
        else:
            return result

    def issue_command_with_async_result(
            self,
            line: str,
            async_timeout: int,
            async_events: list,
            async_expected: str,
            expected_status: SLStatus.SL_STATUS_OK,
            timeout: int = 3,
            retries: int = 0,
            ) -> [bytes]:
        with self._lock:
            if self.test_agent_thread_enabled:
                status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                            async_identifiers=[async_events])
            else:
                status, data = self.issue_command(
                    line, timeout=timeout,
                    )
            self.verify_status(status, expected_status)
            command_issued_time = time.perf_counter_ns()
            async_result = self.read_result_async(line=line,
                                                  command_issued_time=command_issued_time,
                                                  async_timeout=async_timeout,
                                                  async_events=async_events,
                                                  async_expected=async_expected,
                                                  timeout=timeout)
            return async_result

    @staticmethod
    def convert_security_mode(mode: str):
        security_mode = {
            "open": 0,
            "wpa": 1,
            "wpa2": 2,
            "wep": 3,
            "wpa_enterprise": 4,
            "wpa2_enterprise": 5,
            "wpa_wpa2_mixed": 6,
            "wpa3": 7,
            "wpa3_transition": 8,
            "wpa3_enterprise": 9,
            "wpa3_transition_enterprise": 10,
            "security_unknown": 0xFFFF
        }
        if mode in security_mode.keys():
            return security_mode[mode]

    def release_resources(self):
        self.last_retrieved_event_timestamp = 0
        self.bus.release_resources()
        if self.gpio_bus is not None:
            self.gpio_bus.release_resources()
        for queue in self.event_queues:
            self.event_queues[queue] = Queue()

    def host_reset(self):
        self.issue_command(f"host_reset", timeout=3)

    def reset(self):
        self.inited = False
        self.associated = False
        self.ap_beaconing = False
        self.networked = False
        self.power_save_mode = "high_performance"
        self.bt_power_save = False
        self.ble_advertising = False
        self.ble_scanning = False
        self.enabled_twt = False
        self.enable_auto_twt = False
        self.async_response_duration = 0
        self.last_retrieved_event_timestamp = 0
        self._commander_reset()
        self.certs_loaded = dict.fromkeys(self.certs_loaded.keys(), None)
        self.dut_mqtt_client_id_address = 0
        self.dut_http_server_webpage_address = 0
        self.sockets_info = {
            "sync_sockets": [],
            "async_sockets": []
            }
        self.oper_mode_opts = SLWifiOperatingModeOptions()
        self.mqtt_state_connected = None
        self.lwip_mqtt_state_connected = False

    def close(self):
        self.release_resources()
        if self.default_fw:
            try:
                fw_mgr = FirmwareManager.get_instance()
                fw_mgr.load_default_firmware()
            finally:
                self.default_fw = False

    def init(
            self,
            mode: str = None,
            stats_arg: int = 0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            config_required=True,
            load_certificate=True,
            timeout: int = 10,
            ):
        self.logger.info(f"....applying Wi-Fi config settings....")
        if config_required:
            self.set_wifi_config()
        if self.test_agent_thread_enabled and self.inited_test_agent_threads:
            if self.is_external_stack_enabled or self.is_sl_net_enabled:
                status, data = self.issue_command_in_thread(f"net.init {mode}", protocol=Protocol.WIFI,
                                                            async_identifiers=[])
            else:
                status, data = self.issue_command_in_thread(
                    f'wifi.init{f" -i {mode}" if mode is not None else ""}', protocol=Protocol.WIFI,
                    async_identifiers=[]
                    )
        else:
            if self.is_external_stack_enabled or self.is_sl_net_enabled:
                status, data = self.issue_command(f"net.init {mode}", timeout)
            else:
                status, data = self.issue_command(
                    f'wifi.init{f" -i {mode}" if mode is not None else ""}', timeout
                    )
        if status == SLStatus.SL_STATUS_OK:
            self.inited = True
        self.verify_status(status, expected_status)
        if load_certificate:
            self.load_certs()
        return status

    def _apply_si91x_ncp_oper_mode_adjustments(
            self, ext_custom_features: int, ble_features: int, coex_mode: int
    ) -> Tuple[int, int]:
        device_name = self.parent_device.name if self.parent_device else None
        if not is_si91x_ncp_dut(device_name):
            return ext_custom_features, ble_features
        self.logger.info(
            f"Applying Si91x NCP opermode adjustments for DUT '{device_name}' "
            f"(SL_SI91X_EXT_FEAT_672K_M4SS_0K, BLE coex bitmap)"
        )
        return (
            apply_ncp_oper_mode_ext_custom_features(ext_custom_features),
            apply_ncp_oper_mode_ble_features(ble_features, coex_mode),
        )

    def find_set_bit_positions(self, n):
        positions = []
        position = 0
        # Traverse through each bit of the number
        while n > 0:
            if n & 1:  # Check if the least significant bit is set (1)
                positions.append(position)
            n >>= 1  # Right shift to check the next bit
            position += 1

        return positions

    def display_feature_list(self, opermode_params):
        dev_config_feature = opermode_params[0]
        test_feat_selection = opermode_params[1]
        self.logger.info(f'###############{str(dev_config_feature).split(".")[0].replace("enum ", "")}:#############')
        opermode_feature_list = []
        if "Si91xOperatingMode" in str(dev_config_feature).split(".")[0]:
            if test_feat_selection == Si91xOperatingMode.WiFiClient:
                opermode_feature_list.append("WiFiClient")
            elif test_feat_selection == Si91xOperatingMode.EAPWiFiClient:
                opermode_feature_list.append("EAPWiFiClient")
            elif test_feat_selection == Si91xOperatingMode.AccessPoint:
                opermode_feature_list.append("AccessPoint")
            elif test_feat_selection == Si91xOperatingMode.TransceiverMode:
                opermode_feature_list.append("TransceiverMode")
            elif test_feat_selection == Si91xOperatingMode.PERMode:
                opermode_feature_list.append("PERMode")
            elif test_feat_selection == Si91xOperatingMode.ConcurrentMode:
                opermode_feature_list.append("ConcurrentMode")
        elif "Si91xCoexMode" in str(dev_config_feature).split(".")[0]:
            if test_feat_selection == Si91xCoexMode.WLANOnly:
                opermode_feature_list.append("WLANOnly")
            elif test_feat_selection == Si91xCoexMode.WLAN:
                opermode_feature_list.append("WLAN")
            elif test_feat_selection == Si91xCoexMode.ZigBee:
                opermode_feature_list.append("ZigBee")
            elif test_feat_selection == Si91xCoexMode.Bluetooth:
                opermode_feature_list.append("Bluetooth")
            elif test_feat_selection == Si91xCoexMode.WLANBluetooth:
                opermode_feature_list.append("WLANBluetooth")
            elif test_feat_selection == Si91xCoexMode.DualBluetoothBLE:
                opermode_feature_list.append("DualBluetoothBLE")
            elif test_feat_selection == Si91xCoexMode.WLANDual:
                opermode_feature_list.append("WLANDual")
            elif test_feat_selection == Si91xCoexMode.BLE:
                opermode_feature_list.append("BLE")
            elif test_feat_selection == Si91xCoexMode.WLANBLE:
                opermode_feature_list.append("WLANBLE")
            elif test_feat_selection == Si91xCoexMode.ANT:
                opermode_feature_list.append("ANT")
        else:
            for feature_enabled_str in dev_config_feature:
                no_of_features_enabled = 0
                feature_enabled = int(feature_enabled_str.value)
                if test_feat_selection & feature_enabled:
                    feature_count = bin(feature_enabled).count('1')
                    if feature_count > 1:
                        feature_list = self.find_set_bit_positions(feature_enabled)
                        for feature in feature_list:
                            if test_feat_selection & (1 << feature):
                                no_of_features_enabled += 1
                        if no_of_features_enabled == feature_count:
                            opermode_feature_list.append(str(feature_enabled_str).split(".")[1])
                    else:
                        opermode_feature_list.append(str(feature_enabled_str).split(".")[1])
        if len(opermode_feature_list):
            self.logger.info(opermode_feature_list)
        else:
            self.logger.info(f'No feature is enabled from {str(dev_config_feature).split(".")[0].replace("enum ", "")}')

    @defaults("wifi")
    def reset_required(
            self,
            oper_mode: Optional[Si91xOperatingMode] = None,
            coex_mode: Optional[Si91xCoexMode] = None,
            features: Optional[Si91xFeatureBitMap] = None,
            tcpip_features: Optional[Si91xTCPIPFeatureBitMap] = None,
            custom_features: Optional[Si91xCustomFeatureBitMap] = None,
            ext_custom_features: Optional[Si91xExtCustomFeatureBitMap] = None,
            bt_features: Optional[Si91xBTFeatureBitMap] = None,
            ext_tcpip_features: Optional[Si91xExtTCPIPFeatureBitMap] = None,
            ble_features: Optional[Si91xBLEFeatureBitMap] = None,
            ble_custom_ext_features: Optional[Si91xBLECustomFeatureBitMap] = None,
            config_features: Optional[Si91xConfigFeatureBitMap] = None,
            region_code: Optional[Si91xRegionCode] = Si91xRegionCode.US,
            eap_cert=None,
            ca_cert=None,
            client_cert=None,
            client_key=None,
            server_cert=None,
            server_key=None,
            keep_alive_timeout_value=None,
            auth_assoc_timeout_value=None,
            active_chan_scan_timeout_value=None,
            passive_chan_scan_timeout_value=None,
            enable_duty_cycle=Si91xBleDutyParams.enable_duty_cycle,
            duty_cycle=Si91xBleDutyParams.duty_cycle,
            rts_threshold=None,
            band=None,
            boot_option=None,
            ):
        if not self.inited:
            return False
        reset_required = 0
        if (
                (oper_mode is not None and self.oper_mode_opts.oper_mode != oper_mode)
                or (coex_mode is not None and self.oper_mode_opts.coex_mode != coex_mode)
                or (features is not None and self.oper_mode_opts.features != features)
                or (
                tcpip_features is not None
                and self.oper_mode_opts.tcpip_features != tcpip_features
        )
                or (
                custom_features is not None
                and self.oper_mode_opts.custom_features != custom_features
        )
                or (
                ext_custom_features is not None
                and self.oper_mode_opts.ext_custom_features != ext_custom_features
        )
                or (
                bt_features is not None
                and self.oper_mode_opts.bt_features != bt_features
        )
                or (
                ext_tcpip_features is not None
                and self.oper_mode_opts.ext_tcpip_features != ext_tcpip_features
        )
                or (
                ble_features is not None
                and self.oper_mode_opts.ble_features != ble_features
        )
                or (
                ble_custom_ext_features is not None
                and self.oper_mode_opts.ble_custom_ext_features
                != ble_custom_ext_features
        )
                or (
                config_features is not None
                and self.oper_mode_opts.config_features != config_features
        )
                or (region_code is not None and self.region_code != region_code)
                or (eap_cert is not None and self.certs_loaded['eap_cert'] != eap_cert)
                or (ca_cert is not None and self.certs_loaded['ca_cert'] != ca_cert)
                or (client_cert is not None and self.certs_loaded['client_cert'] != client_cert)
                or (client_key is not None and self.certs_loaded['client_key'] != client_key)
                or (server_cert is not None and self.certs_loaded['server_cert'] != server_cert)
                or (server_key is not None and self.certs_loaded['server_key'] != server_key)
                or (keep_alive_timeout_value is not None and self.oper_mode_opts.keep_alive_timeout_value !=
                    keep_alive_timeout_value)
                or (auth_assoc_timeout_value is not None and self.oper_mode_opts.auth_assoc_timeout_value !=
                    auth_assoc_timeout_value)
                or (active_chan_scan_timeout_value is not None and self.oper_mode_opts.active_chan_scan_timeout_value !=
                    active_chan_scan_timeout_value)
                or (
                passive_chan_scan_timeout_value is not None and self.oper_mode_opts.passive_chan_scan_timeout_value != passive_chan_scan_timeout_value)
                or (enable_duty_cycle is not None and self.enable_duty_cycle != enable_duty_cycle)
                or (duty_cycle is not None and self.duty_cycle != duty_cycle)
                or (rts_threshold is not None and self.oper_mode_opts.rts_threshold != rts_threshold)
                or (band is not None and self.oper_mode_opts.band != band)
                or (boot_option is not None and self.oper_mode_opts.boot_option != boot_option)
        ):
            reset_required = 1
        if reset_required:
            return True
        else:
            self.logger.info(
                f"#######################  Device type#####################################################")
            if self.oper_mode_opts.ext_custom_features is not None:
                if (self.oper_mode_opts.ext_custom_features & (1 << 20)) and (
                        self.oper_mode_opts.ext_custom_features & (1 << 21)):
                    self.logger.info("NCP")
                else:
                    self.logger.info("SOC")
                    self.logger.info(
                        f"###############  MEMORY CONFIGURATION ENABLED   #########################################")
                    if self.oper_mode_opts.ext_custom_features & (1 << 20):
                        self.logger.info("SL_SI91X_EXT_FEAT_480K_M4SS_192K")
                    elif self.oper_mode_opts.ext_custom_features & (1 << 21):
                        self.logger.info("SL_SI91X_EXT_FEAT_416K_M4SS_256K")
                    else:
                        self.logger.info("SL_SI91X_EXT_FEAT_352K_M4SS_320K")

            opermode_params = [(Si91xOperatingMode, self.oper_mode_opts.oper_mode),
                               (Si91xCoexMode, self.oper_mode_opts.coex_mode),
                               (Si91xFeatureBitMap, self.oper_mode_opts.features),
                               (Si91xTCPIPFeatureBitMap, self.oper_mode_opts.tcpip_features),
                               (Si91xCustomFeatureBitMap, self.oper_mode_opts.custom_features),
                               (Si91xExtCustomFeatureBitMap, self.oper_mode_opts.ext_custom_features),
                               (Si91xBTFeatureBitMap, self.oper_mode_opts.bt_features),
                               (Si91xExtTCPIPFeatureBitMap, self.oper_mode_opts.ext_tcpip_features),
                               (Si91xBLEFeatureBitMap, self.oper_mode_opts.ble_features),
                               (Si91xBLECustomFeatureBitMap, self.oper_mode_opts.ble_custom_ext_features),
                               (Si91xConfigFeatureBitMap, self.oper_mode_opts.config_features)]
            for print_count in opermode_params:
                self.display_feature_list(print_count)

    @defaults("wifi")
    def set_wifi_config(self,
                        oper_mode: Optional[Si91xOperatingMode] = None,
                        coex_mode: Optional[Si91xCoexMode] = None,
                        features: Optional[Si91xFeatureBitMap] = None,
                        tcpip_features: Optional[Si91xTCPIPFeatureBitMap] = None,
                        custom_features: Optional[Si91xCustomFeatureBitMap] = None,
                        ext_custom_features: Optional[Si91xExtCustomFeatureBitMap] = None,
                        bt_features: Optional[Si91xBTFeatureBitMap] = None,
                        ext_tcpip_features: Optional[Si91xExtTCPIPFeatureBitMap] = None,
                        ble_features: Optional[Si91xBLEFeatureBitMap] = None,
                        ble_custom_ext_features: Optional[Si91xBLECustomFeatureBitMap] = None,
                        config_features: Optional[Si91xConfigFeatureBitMap] = None,
                        region=None,
                        region_code=None,
                        enable_feature_frame_request=None,
                        pll_mode=None,
                        rf_type=None,
                        wireless_mode=None,
                        enable_ppp=None,
                        afe_type=None,
                        features_enable=None,
                        enable_timeout_config=None,
                        keep_alive_timeout_value=None,
                        auth_assoc_timeout_value=None,
                        active_chan_scan_timeout_value=None,
                        passive_chan_scan_timeout_value=None,
                        enable_duty_cycle=None,
                        duty_cycle=None,
                        set_rts=None,
                        rts_threshold=None,
                        band=Si91xWifiBand.SL_SI91X_WIFI_BAND_2_4GHZ,
                        boot_option=Si91xBootOption.LOAD_NWP_FW,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        ):
        # Flashes the M4 application based on MEM_CONFIG specified in ext_custom_features bitmap
        # SLCollections.flash_memory_config(ext_custom_features)
        if oper_mode is None:
            oper_mode = self.oper_mode_opts.oper_mode
        if coex_mode is None:
            coex_mode = self.oper_mode_opts.coex_mode

        if features is None:
            features = self.oper_mode_opts.features

        if tcpip_features is None:
            tcpip_features = self.oper_mode_opts.tcpip_features
            if oper_mode == Si91xOperatingMode.AccessPoint:
                # in AP mode, adding DHCP server
                tcpip_features |= Si91xTCPIPFeatureBitMap.DHCPv4Server

        if custom_features is None:
            custom_features = self.oper_mode_opts.custom_features
        if ext_custom_features is None:
            ext_custom_features = self.oper_mode_opts.ext_custom_features
        if bt_features is None:
            bt_features = self.oper_mode_opts.bt_features
        if ext_tcpip_features is None:
            ext_tcpip_features = self.oper_mode_opts.ext_tcpip_features
        if ble_features is None:
            ble_features = self.oper_mode_opts.ble_features
        if ble_custom_ext_features is None:
            ble_custom_ext_features = self.oper_mode_opts.ble_custom_ext_features
        if config_features is None:
            config_features = self.oper_mode_opts.config_features
        if keep_alive_timeout_value is None:
            keep_alive_timeout_value = self.oper_mode_opts.keep_alive_timeout_value
        if auth_assoc_timeout_value is None:
            auth_assoc_timeout_value = self.oper_mode_opts.auth_assoc_timeout_value
        if active_chan_scan_timeout_value is None:
            active_chan_scan_timeout_value = self.oper_mode_opts.active_chan_scan_timeout_value
        if passive_chan_scan_timeout_value is None:
            passive_chan_scan_timeout_value = self.oper_mode_opts.passive_chan_scan_timeout_value
        if rts_threshold is None:
            rts_threshold = self.oper_mode_opts.rts_threshold
        if band is None:
            band = self.oper_mode_opts.band
        if boot_option is None:
            boot_option = self.oper_mode_opts.boot_option

        ext_custom_features, ble_features = self._apply_si91x_ncp_oper_mode_adjustments(
            ext_custom_features, ble_features, coex_mode
        )

        self.logger.info(f"#######################  Device type#####################################################")
        if (ext_custom_features & (1 << 20)) and (ext_custom_features & (1 << 21)):
            self.logger.info("NCP")
        else:
            self.logger.info("SOC")
            self.logger.info(
                f"###############  MEMORY CONFIGURATION ENABLED   #########################################")
            if ext_custom_features & (1 << 20):
                self.logger.info("SL_SI91X_EXT_FEAT_480K_M4SS_192K")
            elif ext_custom_features & (1 << 21):
                self.logger.info("SL_SI91X_EXT_FEAT_416K_M4SS_256K")
            else:
                self.logger.info("SL_SI91X_EXT_FEAT_352K_M4SS_320K")
        self.logger.info(f"####################### CONFIGURATION FEATURES ENABLED###################################")

        opermode_params = [(Si91xOperatingMode, oper_mode), (Si91xCoexMode, coex_mode), (Si91xFeatureBitMap, features),
                           (Si91xTCPIPFeatureBitMap, tcpip_features), (Si91xCustomFeatureBitMap, custom_features),
                           (Si91xExtCustomFeatureBitMap, ext_custom_features), (Si91xBTFeatureBitMap, bt_features),
                           (Si91xExtTCPIPFeatureBitMap, ext_tcpip_features), (Si91xBLEFeatureBitMap, ble_features),
                           (Si91xBLECustomFeatureBitMap, ble_custom_ext_features),
                           (Si91xConfigFeatureBitMap, config_features)]

        for print_count in opermode_params:
            self.display_feature_list(print_count)

        if self.inited:
            if self.reset_required(
                    oper_mode,
                    coex_mode,
                    features,
                    tcpip_features,
                    custom_features,
                    ext_custom_features,
                    bt_features,
                    ext_tcpip_features,
                    ble_features,
                    ble_custom_ext_features,
                    config_features,
                    region,
                    region_code,
                    keep_alive_timeout_value,
                    auth_assoc_timeout_value,
                    active_chan_scan_timeout_value,
                    passive_chan_scan_timeout_value,
                    enable_duty_cycle,
                    duty_cycle,
                    rts_threshold,
                    band,
                    boot_option,
                    ):
                raise RuntimeError(
                    "DUT has already been initialized with different settings.  A reset is required."
                    )
            else:
                return

        status, data = self.issue_command(
            f'wifi.set_config {oper_mode} {coex_mode} {features} {tcpip_features} {custom_features} {ext_custom_features} {bt_features} {ext_tcpip_features} {ble_features} {ble_custom_ext_features} {config_features}{f" -b {band}" if band is not None else ""}{f" -l {boot_option}" if boot_option is not None else ""}')
        self.verify_status(status, expected_status)

        if enable_timeout_config:
            self.set_timeout_config(keep_alive_timeout_value=keep_alive_timeout_value,
                                    auth_assoc_timeout_value=auth_assoc_timeout_value,
                                    active_chan_scan_timeout_value=active_chan_scan_timeout_value,
                                    passive_chan_scan_timeout_value=passive_chan_scan_timeout_value)

        if enable_feature_frame_request:
            self.set_feature_frame_request(pll_mode=pll_mode, rf_type=rf_type, wireless_mode=wireless_mode,
                                           enable_ppp=enable_ppp, afe_type=afe_type, features_enable=features_enable)

        if region:
            self.set_wifi_region(region_code=region_code)

        if enable_duty_cycle:
            self.set_duty_cycle(duty_cycle=duty_cycle)

        if region is None:
            region = Si91xRegion.FromUser
        if region_code is None:
            region_code = Si91xRegionCode.US
        if enable_duty_cycle is None:
            enable_duty_cycle = Si91xBleDutyParams.enable_duty_cycle
        if duty_cycle is None:
            duty_cycle = Si91xBleDutyParams.duty_cycle
        if set_rts is not None:
            self.set_rts_threshold(config_rts_threshold=set_rts, rts_threshold=rts_threshold)

        self.oper_mode_opts.oper_mode = oper_mode
        self.oper_mode_opts.coex_mode = coex_mode
        self.oper_mode_opts.features = features
        self.oper_mode_opts.tcpip_features = tcpip_features
        self.oper_mode_opts.custom_features = custom_features
        self.oper_mode_opts.ext_custom_features = ext_custom_features
        self.oper_mode_opts.bt_features = bt_features
        self.oper_mode_opts.ext_tcpip_features = ext_tcpip_features
        self.oper_mode_opts.ble_features = ble_features
        self.oper_mode_opts.ble_custom_ext_features = ble_custom_ext_features
        self.oper_mode_opts.config_features = config_features
        self.region = region
        self.region_code = region_code
        self.oper_mode_opts.keep_alive_timeout_value = keep_alive_timeout_value
        self.oper_mode_opts.auth_assoc_timeout_value = auth_assoc_timeout_value
        self.oper_mode_opts.active_chan_scan_timeout_value = active_chan_scan_timeout_value
        self.oper_mode_opts.passive_chan_scan_timeout_value = passive_chan_scan_timeout_value
        self.enable_duty_cycle = enable_duty_cycle
        self.duty_cycle = duty_cycle
        self.oper_mode_opts.rts_threshold = rts_threshold
        self.oper_mode_opts.band = band
        self.oper_mode_opts.boot_option = boot_option

    @defaults("wifi")
    def load_certs(self, eap_cert=None, ca_cert=None, client_cert=None, server_cert=None, client_key=None,
                   server_key=None):
        def __unpack_and_load_certs(cert_params):
            if all(isinstance(cert, (list, tuple)) for cert in cert_params):
                for cert_index, cert in enumerate(cert_params):
                    self.set_ssl_certificate(str(get_tls_certificate_dir().joinpath(cert[0])),
                                             eval(f"Si91xCertificateType.{cert[1]}"),
                                             eval(f"Si91xCertIdentifier.{cert[2]}"), cert_index=cert_index)
            elif len(cert_params) == 3:
                self.set_ssl_certificate(str(get_tls_certificate_dir().joinpath(cert_params[0])),
                                         eval(f"Si91xCertificateType.{cert_params[1]}"),
                                         eval(f"Si91xCertIdentifier.{cert_params[2]}"))
            else:
                raise ValueError(
                    "certificate param should be in the form of list or tuple with cert_file, cert_type, cert_identifier in sequence")

        certs = {'eap_cert': eap_cert, 'ca_cert': ca_cert, 'client_cert': client_cert, 'server_cert': server_cert,
                 'client_key': client_key, 'server_key': server_key}
        for cert_name, cert_param in certs.items():
            if cert_param and isinstance(cert_param, (list, tuple)):
                __unpack_and_load_certs(cert_param)
            self.certs_loaded[cert_name] = cert_param

    def scan(
            self,
            ssid: str = None,
            interface: str = None,
            bgscan: bool = False,
            channel: int = 0,
            sync: int = 0,
            bg_scan_periodicity: int = None,
            scan_bitmap_2_4: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 60,
            async_timeout: int = 60,
            retries: int = 0,
            sleep_time=1,
            scan_type=None,
            lp_mode=None,
            measure_scan_time=0,
            scan_count_extended=None,
            ) -> List[WiFiScanResult]:
        """
        scan_count_extended:: This parameter is applicable only when scan_type is set to 2 (SL_WIFI_SCAN_TYPE_EXTENDED).
        By default scan_count_extended is set to 50 in test agent. User can change it based on the requirement
        """
        self.logger.info(
            f"Initiating scan with the ssid->{ssid}, interface->{interface} and channel no->{channel}"
            )

        command = (
            f'wifi.scan{f" -s {ssid}" if ssid else ""}{f" -i {interface}" if interface else ""}'
            f'{f" -m bg_scan" if bgscan else ""}'
            f'{f" -c {channel}" if channel else ""}'
            f'{f" -a {sync}" if sync else ""}'
            f'{f" -t {bg_scan_periodicity}" if bg_scan_periodicity else ""}'
            f'{f" -l {scan_bitmap_2_4}" if scan_bitmap_2_4 else ""}'
            f'{f" -p {scan_type}" if scan_type is not None else ""}'
            f'{f" -b {lp_mode}" if lp_mode is not None else ""}'
            f'{f" -n {scan_count_extended}" if scan_count_extended is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(command,
                                                        timeout=timeout,
                                                        async_timeout=async_timeout,
                                                        retries=retries,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.SCAN_RESULTS],
                                                        sleep_time=sleep_time)
        else:
            status, data = self.issue_command(command, timeout, retries)

        self.verify_status(status, expected_status)
        self.logger.info(f"Scan Command Response {data}")
        lines = data.splitlines()
        scan_time = None
        if measure_scan_time:
            scan_time = lines[-2].decode()
            if "scan time" in scan_time:
                self.logger.info(f"Time taken for scan-> {scan_time}")
            else:
                scan_time = SLStatus.SL_STATUS_FAIL
        result = []
        for line in lines:
            tokens = line.split(b",")
            if len(tokens) == 6:
                ssid = tokens[0].strip()
                security_mode = int(tokens[1].strip())
                network_type = int(tokens[2].strip())
                bssid = tokens[3].strip()
                channel = int(tokens[4].strip())
                rssi = int(tokens[5].strip())

                sr = self.ScanResult._make(
                    (
                        channel,
                        security_mode,
                        rssi,
                        network_type,
                        ssid,
                        bssid.decode("ascii"),
                        )
                    )
                result.append(WiFiScanResult(**sr._asdict()))

        self.logger.info(f"Scan Results: {str(result)}")
        if measure_scan_time:
            return result, scan_time
        else:
            return result

    def close_sockets(self) -> None:
        if len(self.sockets_info["sync_sockets"]):
            self.logger.info(
                f'Closing all the Synchronous sockets {self.sockets_info["sync_sockets"]} before disconnection')
            while len(self.sockets_info["sync_sockets"]) > 0:
                socket_id = self.sockets_info["sync_sockets"][-1]
                self.logger.info(f"passing socket ID: {socket_id} from the list to close the socket")
                self.bsdSockClose(socket_fd=socket_id)
        self.sockets_info["sync_sockets"] = []
        if len(self.sockets_info["async_sockets"]):
            self.logger.info(
                f'Closing all the Asynchronous sockets {self.sockets_info["async_sockets"]} before disconnection')
            while len(self.sockets_info["async_sockets"]) > 0:
                socket_id = self.sockets_info["async_sockets"][-1]
                self.logger.info(f"passing socket ID: {socket_id} from the list to close the socket")
                self.bsdAsyncSockClose(socket_fd=socket_id)
        self.sockets_info["async_sockets"] = []

    def stop_soft_ap_interface(self, interface: str = "ap",
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout=30,
                               ):
        self.logger.info(
            f"Initiating  stop_soft_ap_interface interface->{interface}"
            )
        line = (
            f'wifi.stop_ap_interface -i {interface}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.ap_beaconing = False        

    def on_incoming_rx_data(self, timestamp: int, record: bytes):
        self.logger.debug(f"Got data: {record.decode(errors='ignore')}")

    @defaults("wifi")
    def join(
            self,
            ssid: str,
            passphrase: str,
            security: str = "wpa2",
            uid: str = None,
            enc: str = "ccmp",
            timeout_ms: int = None,
            channel: int = None,
            band: str = None,
            bandwidth: str = None,
            interface: str = 'client',
            pmk_enable: bool = False,
            channel_bitmap_2_4: int = None,
            channel_bitmap_5: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            expected_negative_status=None,
            timeout: int = 30,
            async_timeout: int = 90,
            mac: str = None,
            enable_lwip: int = 0,
            profile_id: int = 0,
            net_interface: str = None,
            ip_type: int = None,
            ip_management_mode: int = None,
            ):
        if timeout_ms is not None:
            timeout_ms = 18000
        line = (
            f'wifi.client.connect {ssid} {passphrase} -s {security} {f"-u {uid}" if uid else ""} -e {enc} '
            f'{f"-t {timeout_ms}" if timeout_ms else ""} {f"-c {channel}" if channel else ""} '
            f'{f"-b {band}" if band else ""} {f"-w {bandwidth}" if bandwidth else ""} {f" -i {interface}" if interface else ""} '
            f'{f"-p true" if pmk_enable else ""}{f" -a {channel_bitmap_2_4}" if channel_bitmap_2_4 is not None else ""}'
            f'{f" -h {channel_bitmap_5}" if channel_bitmap_5 is not None else ""}'
            f'{f" -m {mac}" if mac is not None else ""}'
            f'{f" -z {enable_lwip}" if enable_lwip else ""}'
            f'{f" -j {profile_id}" if profile_id else ""}'
            f'{f" -n {net_interface}" if net_interface is not None else ""}'
            f'{f" -o {ip_type}" if ip_type is not None else ""}'
            f'{f" -k {ip_management_mode}" if ip_management_mode is not None else ""}'
        )

        self.logger.info(
            f"\n *** Initiating join with ssid: {ssid} in channel: {channel} with security: {security} ***\n")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=async_timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.JOIN_EVENT])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        if expected_negative_status:
            return status, data
        else:
            if status == SLStatus.SL_STATUS_OK:
                self.associated = True
            self.verify_status(status, expected_status)
            return status, data

#######################################################################################################################################
    @defaults("wifi")
    def lwip_join(
            self,
            ssid: str,
            passphrase: str,
            security: str = "wpa2",
            uid: str = None,
            enc: str = "ccmp",
            timeout_ms: int = None,
            channel: int = None,
            band: str = None,
            bandwidth: str = None,
            interface: str = 'client',
            pmk_enable: bool = False,
            channel_bitmap_2_4: int = None,
            channel_bitmap_5: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            expected_negative_status=None,
            timeout: int = 30,
            async_timeout: int = 90,
            mac: str = None
        ):
        """Specific wifi connection CLI for LwIP stack to separate wifi connection & IP configuration"""

        if timeout_ms is not None:
            timeout_ms = 18000
        
        line = (
            f'wifi.client.connect_lwip {ssid} {passphrase} -s {security} {f"-u {uid}" if uid else ""} -e {enc} '
            f'{f"-t {timeout_ms}" if timeout_ms else ""} {f"-c {channel}" if channel else ""} '
            f'{f"-b {band}" if band else ""} {f"-w {bandwidth}" if bandwidth else ""} {f" -i {interface}" if interface else ""} '
            f'{f"-p true" if pmk_enable else ""}{f" -a {channel_bitmap_2_4}" if channel_bitmap_2_4 is not None else ""}'
            f'{f" -h {channel_bitmap_5}" if channel_bitmap_5 is not None else ""}'
            f'{f" -m {mac}" if mac is not None else ""}'
        )

        self.logger.info(f"\n *** Initiating join with ssid: {ssid} in channel: {channel} with security: {security} ***\n")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=async_timeout, protocol=Protocol.WIFI, async_identifiers=[AsyncIdentifiers.JOIN_EVENT])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        if expected_negative_status:
            return status, data
        else:
            if status == SLStatus.SL_STATUS_OK:
                self.associated = True
            
            self.verify_status(status, expected_status)
            return status, data

    @defaults("wifi")
    def leave(
            self,
            interface: str = "client",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            close_sockets: bool = True,
            ):
        self.logger.info(f"\n *** Initiating Leave from DUT *** \n")
        if close_sockets:
            self.close_sockets()
        line = f"wifi.client.disconnect -i {interface}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=5, protocol=Protocol.WIFI, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=5,
                )
        self.associated = False
        self.verify_status(status, expected_status)
        return status, data

    def deinit(
            self, mode: str = None, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Initiating Deinit *** \n")
        if self.is_external_stack_enabled or self.is_sl_net_enabled:
            status, data = self.issue_command(f"net_deinit {mode}")
        else:
            status, data = self.issue_command("wifi.deinit")
        self.inited = False
        self.associated = False
        self.networked = False
        self.enabled_twt = False
        self.enable_auto_twt = False
        self.verify_status(status, expected_status)

    def join_ap(
            self, access_point: Device,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            pmk_enable=False,
            expected_negative_status=None,
            channel_bitmap_2_4: int = None,
            channel_bitmap_5: int = None,
            mac: str = None,
            ):
        status, data = self.join(ssid=access_point.interfaces.wifi.ssid,
                                 passphrase=access_point.interfaces.wifi.passphrase,
                                 channel=access_point.interfaces.wifi.channel,
                                 security=access_point.interfaces.wifi.security.name.lower(),
                                 expected_status=expected_status,
                                 pmk_enable=pmk_enable,
                                 expected_negative_status=expected_negative_status,
                                 channel_bitmap_2_4=channel_bitmap_2_4,
                                 channel_bitmap_5=channel_bitmap_5,
                                 mac=mac
                                 )

        if status == SLStatus.SL_STATUS_OK:
            self.associated = True
        self.verify_status(status, expected_status)
        return self.get_command_data(data)

    def start_ip(self, static_ip: str = None, ip_version: str = 'ipv4', static_subnet: str = None,
                 static_gateway: str = None, vid: int = None,
                 static_ipv6_address: str = None,
                 ipv6_gw_address: str = None,
                 enable_dhcp: int = 0,
                 min_discover_retry_interval: int = None,
                 max_discover_retry_interval: int = None,
                 min_request_retry_interval: int = None,
                 max_request_retry_interval: int = None,
                 min_discover_retries: int = None,
                 max_request_retries: int = None,
                 expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=10):
        line = None

        self.logger.info(f"\n *** Initiating start_ip *** \n")
        if self.is_external_stack_enabled:
            line = f"net.up client"
        else:
            if not [x for x in (static_ip, static_subnet, static_gateway) if x is None]:
                line = f"net.configure_ip {ip_version} -i {static_ip} -n {static_subnet} -g {static_gateway} -v {vid}"
            elif not [x for x in (static_ipv6_address, ipv6_gw_address) if x is None]:
                line = f"net.configure_ip {ip_version} -a {static_ipv6_address} -w {ipv6_gw_address} -v {vid}"
            else:
                line = f"net.configure_ip {ip_version}"

        if enable_dhcp:
            self.logger.info("======= configure dhcp on dut")
            line = f"net.configure_ip {ip_version} -u {enable_dhcp} -m {min_discover_retry_interval} -b {max_discover_retry_interval} " \
                   f"-c {min_request_retry_interval} -d {max_request_retry_interval} -e {min_discover_retries} " \
                   f"-f {max_request_retries}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=50,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.networked = True
            ip_info = self.get_command_data(data)
            if ip_version == 'ipv4':
                matches = re.findall(b"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info)
                assert (
                        len(matches) == 3
                ), f"Error parsing IP, netmask and gateway from {ip_info}"
                ip, netmask, gateway = [match.strip() for match in matches]
                self.ip = self.IPConfig(ip=ip, netmask=netmask, gateway=gateway)
                self.logger.info(f"********ip*******:*******{self.ip}****{type(self.ip)}*")
                return self.ip
            else:
                linklocaladdr = ip_info.split(b",")[0].strip().decode()
                global_addr = ip_info.split(b",")[1].strip().decode()
                gateway_addr = ip_info.split(b",")[2].strip().decode()
                return linklocaladdr, global_addr, gateway_addr

    def get_ip_address(self, network_interface=None) -> str:
        return self.ip.ip.decode()

    def get_device_ip(self, device_ip) -> str:
        self.logger.info(f"\n *** Initiating get device ip *** \n")
        self.logger.debug(f"device_ip.ip, from dut {device_ip.ip}")
        return device_ip.ip.decode()

    def get_signal_strength(
            self,
            interface: str = "client",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info(f"\n *** Initiating get signal strength *** \n")
        status, data = self.issue_command(f"wifi.get_signal_strength -i {interface}")
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def dhcp_start(self,expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 15):
        line = f"net.dhcp_start "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
            
        if status == SLStatus.SL_STATUS_OK:
            ip_info = self.get_command_data(data)
            matches = re.findall(b"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info)
            if len(matches) >= 1:
                ip = matches[0].strip()
                self.logger.info(f"********DHCP IP acquired*******:*******{ip.decode()}*")
                return ip.decode()
            else:
                self.logger.error(f"Error parsing IP from {ip_info}")

#######################################################################################################################################
    def dhcp_stop(self,expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 5):
        line = f"net.dhcp_stop "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def poll_signal_strength( self,
                            interface: str = None,
                            timeout_ms: int = None,
                            pulse_ms: int = None,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        ):
        """Triggers polling of the Wi-Fi signal strength at regular intervals for a specified duration."""
        
        self.logger.info(f"\n *** Initiating get signal strength *** \n")
        status, data = self.issue_command(f"wifi.get_signal_strength{f' -i {interface}' if interface else ''}{f' -j {timeout_ms}' if timeout_ms is not None else ''}{f' -k {pulse_ms}' if pulse_ms is not None else ''}")
        self.verify_status(status, expected_status)

    def set_antenna(
            self,
            interface: str = None,
            antenna: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info(f"\n *** Initiating set antenna *** \n")
        status, data = self.issue_command(
            f'wifi.set_antenna {f" -i {interface}" if interface else ""}'
            f'{f" -a {antenna}" if antenna else ""}'
            )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_mtu(self,
                    mtu_size=240,
                    timeout=10,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    ):
        line = f"set_mtu {mtu_size}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
            )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)

    def start_statistic_report(
            self,
            interface: str = None,
            channel: int = None,
            max_stats_count: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            async_timeout: int = 40,
            timeout: int = 10,
            ):
        self.logger.info(f"\n *** Initiating statistic report *** \n")
        line = f'wifi.start_statistic_report{f" -i {interface}" if interface else ""}{f" -c {channel}" if channel else ""}{f" -m {max_stats_count}" if max_stats_count else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=async_timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def stop_statistic_report(
            self,
            interface: str = None,
            channel: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        status, data = self.issue_command(
            f'wifi.stop_statistic_report {f" -i {interface}" if interface else ""}'
            )
        self.verify_status(status, expected_status)

    def set_performance_profile(
            self,
            mode: str = "high_performance",
            dtim_aligned_type: int = 0,
            num_of_dtim_skip: int = 0,
            listen_interval: int = 0,
            monitor_interval: int = 0,
            beacon_miss_ignore_limit: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        if mode == "standby_power_save":
            mode = "deep_sleep_without_ram_retention"
        if mode == "standby_power_save_with_ram_retention":
            mode = "deep_sleep_with_ram_retention"
        self.logger.info(f"\n *** Initiating set performance profile for {mode} *** \n")
        line = f"wifi.set_performance_profile {mode} {dtim_aligned_type} {num_of_dtim_skip} {listen_interval} {monitor_interval}"
        
        if beacon_miss_ignore_limit is not None:
            line += f" -i {beacon_miss_ignore_limit}"
        
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=5, protocol=Protocol.WIFI, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=5,
                )
        self.power_save_mode = mode
        self.verify_status(status, expected_status)
        return status

    def get_performance_profile(
            self, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Initiating get performance profile *** \n")
        status, data = self.issue_command(f"wifi.get_performance_profile ")
        self.verify_status(status, expected_status)

        if status != SLStatus.SL_STATUS_OK:
            return

        expression = re.compile("Performance Mode: (.*)")
        match = expression.search(data)
        if match:
            return match[1].lower()

    def sl_wifi_set_antenna(
            self,
            interface: str = None,
            channel: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        status, data = self.issue_command(
            f'wifi.sl_wifi_set_antenna {f" -i {interface}" if interface else ""}'
            f'{f" -c {channel}" if channel else ""}',
            timeout=timeout,
            )
        self.verify_status(status, expected_status)

    def sl_si91x_transmit_test_start(
            self,
            enable: int = None,
            power: int = None,
            rate: int = None,
            length: int = None,
            mode: int = None,
            channel: int = None,
            aggr_enable: int = None,
            enable_11ax: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        status, data = self.issue_command(
            f'wifi.sl_si91x_transmit_test_start {f" -i {enable}" if enable else ""}'
            f'{f" -j {power}" if power else ""}'
            f'{f" -k {rate}" if rate else ""}'
            f'{f" -l {length}" if length else ""}'
            f'{f" -m {mode}" if mode else ""}'
            f'{f" -n {channel}" if channel else ""}'
            f'{f" -o {aggr_enable}" if aggr_enable else ""}'
            f'{f" -p {enable_11ax}" if enable_11ax is not None else ""}',
            timeout=timeout,
            )
        self.verify_status(status, expected_status)

    def sl_si91x_transmit_test_stop(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"\n *** Stop wifi statistic report *** \n")
        status, data = self.issue_command('wifi.sl_si91x_transmit_test_stop', timeout)
        self.verify_status(status, expected_status)
        return data

    def set_state(self, value: Union[str, List[str]]):
        if isinstance(value, str):
            value = [value]
        if self.parent_device is not None:
            self.logger.info(
                f"Setting state of wifi interface of device '{self.parent_device.name}' to '{value}'"
                )
        if "reset" in value:
            self.logger.info(f"Resetting the device")
            self.reset()

        if "net_init" in value:
            self.set_wifi_config()
            self.sl_net_init(mode="ap")

        if "net_init_stats" in value:
            self.sl_net_init(mode="ap", stats_arg=1)

        if "net_init_client" in value:
            self.is_external_stack_enabled = True

        if "disable_external_stack" in value:
            self.is_external_stack_enabled = False

        if "sl_net_init_client" in value:
            self.is_external_stack_enabled = True
            try:
                if self.reset_required():
                    self.logger.info(f"Resetting DUT due to change in DUT settings")
                    self.reset()
                if self.associated:
                    self.logger.info(f"Setting state: associated -> init")
                    self.leave()
                elif not self.inited:
                    self.logger.info(f"Setting state: deinit -> init")
                    self.init(mode="client")
            except AssertionError:
                self.logger.info(f"Init failed. Resetting device and trying again")
                self.reset()
                self.init(mode="client")

        if "deinit" in value:
            if self.inited:
                self.logger.info(f"Setting state: init -> deinit")
                self.deinit()
        if "set_default_region" in value:
            self.logger.info(f"Setting region to --->US")
            self.set_wifi_region()
        if "init" in value:
            try:
                if self.reset_required():
                    self.logger.info(f"Resetting DUT due to change in DUT settings")
                    self.reset()
                if self.associated:
                    self.logger.info(f"Setting state: associated -> init")
                    self.leave()
                elif not self.inited:
                    self.logger.info(f"Setting state: deinit -> init")
                    self.init()
            except AssertionError:
                self.logger.info(f"Init failed. Resetting device and trying again")
                self.reset()
                self.init()
        if "associated" in value:
            if not self.inited:
                try:
                    self.init()
                except AssertionError:
                    self.logger.info(f"Init failed. Resetting device and trying again")
                    self.reset()
                    self.init()
            if not self.associated:
                self.logger.info(f"Setting state: not associated -> associated")
                self.join()
        if "networked" in value:
            if not self.inited:
                try:
                    self.init()
                except AssertionError:
                    self.logger.info(f"Init failed. Resetting device and trying again")
                    self.parent_device.reset()
                    self.init()
            if not self.associated:
                self.logger.info(f"Setting state: not associated -> associated")
                self.join()
            if not self.networked:
                self.logger.info(f"Setting state: non networked -> networked")
                self.start_ip()
        if "softap" in value:
            if self.inited:
                self.deinit()
            try:
                self.init(mode="ap")
            except AssertionError:
                self.logger.info(f"Init failed. Resetting device and trying again")
                self.reset()
                self.init(mode="ap")
            self.logger.info(f"Setting state: softap")
            self.start_ap()

        if "ble_stop_adv" in value:
            if self.ble_advertising:
                self.logger.info("Initiating stop advertise from DUT")
                self.ble_stop_advertising()

        if "ble_stop_scan" in value:
            if self.ble_scanning:
                self.logger.info("Initiating stop ble_scanning from DUT")
                self.ble_stop_scanning()

        if "close_sockets" in value:
            if self.associated:
                self.close_sockets()

        if "aws_unsubscribe" in value:
            if self.aws_flags['subscribed']:
                self.aws_iot_mqtt_unsubscribe(topic_name=self.aws_flags['topic'])

        if "mqtt_disconnect" in value:
            if self.inited:
                if self.mqtt_state_connected:
                    self.logger.info("Disconnect MQTT Broker")
                    self.mqtt_client_disconnect()
        if "lwip_mqtt_disconnect" in value:
            if self.inited:
                if self.lwip_mqtt_state_connected:
                    self.logger.info("Disconnect MQTT Broker")
                    self.lwip_mqtt_disconnect()

        if "azure_iot_unsubscribe" in value:
            if self.azure_flags['subscribed']:
                self.azure_iot_unsubscribe()

        if "aws_disconnect" in value:
            if self.aws_flags['connected']:
                self.aws_iot_mqtt_disconnect()

        if "azure_iot_disconnect" in value:
            if self.azure_flags['connected']:
                self.azure_iot_disconnect()

        if "clear_certs" in value:
            self.clear_certificate()
            self.certs_loaded = dict.fromkeys(self.certs_loaded.keys(), None)

        if "bt_powersave_disable" in value:
            self.logger.info("Disabling of bt power save")
            if self.bt_power_save:
                self.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveDisabled,
                                          psp_type=Si91xPowerSaveProcedureTypes.MaxPowerSave)

        if "wifi_powersave_disable" in value:
            self.logger.info("Disabling of wifi power save")
            if self.power_save_mode != "high_performance":
                self.set_performance_profile(mode="high_performance")

        if "disable_twt" in value and self.enabled_twt:
            self.logger.info(f"Disabling TWT")
            self.disable_twt()

        if "disable_auto_twt" in value and self.enable_auto_twt:
            self.logger.info(f"Disabling Auto TWT")
            self.twt_auto_config(twt_enable=0)

        if ("unassociated" in value) or ("disassociated" in value):
            if self.associated:
                self.logger.info(f"Setting state: associated -> unassociated")
                self.leave()
            elif not self.inited:
                self.logger.info(f"Setting state to init")
                self.init()
        if "net_down" in value:
            if self.associated:
                self.logger.info(f"Setting state: associated -> unassociated")
                self.sl_net_down(mode="client")
            elif not self.inited:
                self.logger.info(f"Setting state to init")
                self.init()     
        if "stop_ap_beaconing" in value:
            if self.ap_beaconing:
                self.stop_soft_ap_interface()                           
        if "set_default_timeout_config" in value:
            self.logger.info(f"Setting config timeout to default values")
            self.set_timeout_config()
        if "reset_wifi_conn_stats" in value:
            self.logger.info(f"Setting wifi connection and disconnection stats to zero")
            self.reset_wifi_connection_disconnection_stats()
        if "set_default_ssl_cipher" in value:
            self.logger.info(f"Setting default ssl_cipher")
            self.set_default_ssl_cipher()
        if "set_default_extended_ssl_cipher" in value:
            self.logger.info(f"Setting extended default ssl cipher")
            self.set_default_extended_ssl_cipher()
        if "load_default_fw" in value:
            self.default_fw = True
        if "set_default_rts_threshold" in value:
            self.logger.info(f"Setting default rts threshold")
            self.set_rts_threshold()
        if "set_default_feature_frame_request" in value:
            self.logger.info(f"Setting default feature frame request")
            self.set_feature_frame_request()
        if "sl_net_deinit_client" in value:
            self.sl_net_deinit(mode="client")
        if "cleanup_ble" in value:
            self.cleanup_ble()


    def start_ap(
            self,
            security: str = None,
            ssid: str = None,
            encryption=None,
            channel=None,
            band=None,
            bandwidth=None,
            rate_protocol=None,
            options=None,
            credential_id=None,
            client_idle_timeout=255,
            dtim_beacon_count=None,
            max_clients=None,
            keepalive_type=None,
            beacon_interval=None,
            psk=None,
            ht_caps=None,
            beacon_stop=None,
            tdi_flags=None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 12,
            ):
        if security is not None:
            security = security.lower()
        self.logger.info(f"Sending wifi.ap.start CLI command with following parameters:\n"
                         f'{f",a::ssid:{ssid}" if ssid is not None else ""}'
                         f'{f",b::security:{security}" if security is not None else ""}'
                         f'{f",c::encryption:{encryption}" if encryption is not None else ""}'
                         f'{f",d::channel:{channel}" if channel is not None else ""}'
                         f'{f",e::band:{band}" if band is not None else ""}'
                         f'{f",f::bandwidth:{bandwidth}" if bandwidth is not None else ""}'
                         f'{f",g::rate_protocol:{rate_protocol}" if rate_protocol is not None else ""}'
                         f'{f",h::options:{options}" if options is not None else ""}'
                         f'{f",i::credential_id:{credential_id}" if credential_id is not None else ""}'
                         f'{f",j::client_idle_timeout:{client_idle_timeout}" if client_idle_timeout is not None else ""}'
                         f'{f",k::dtim_beacon_count:{dtim_beacon_count}" if dtim_beacon_count is not None else ""}'
                         f'{f",l::max_clients:{max_clients}" if max_clients is not None else ""}'
                         f'{f",m::keepalive_type:{keepalive_type}" if keepalive_type is not None else ""}'
                         f'{f",n::beacon_interval:{beacon_interval}" if beacon_interval is not None else ""}'
                         f'{f",o::ht_caps:{ht_caps}" if ht_caps is not None else ""}'
                         f'{f",p::psk:{psk}" if psk is not None else ""}'
                         f'{f",q::beacon_stop:{beacon_stop}" if beacon_stop is not None else ""}'
                         f'{f",r::tdi_flags:{tdi_flags}" if tdi_flags is not None else ""}')

        line = f"wifi.ap.start{f' -a {ssid}' if ssid else ''}{f' -b {security}' if security else ''}{f' -c {encryption}' if encryption else ''}{f' -d {channel}' if channel is not None else ''}{f' -e {band}' if band else ''}{f' -f {bandwidth}' if bandwidth else ''}{f' -g {rate_protocol}' if rate_protocol else ''}{f' -h {options}' if options else ''}{f' -i {credential_id}' if credential_id else ''}{f' -j {client_idle_timeout}' if client_idle_timeout else ''}{f' -k {dtim_beacon_count}' if dtim_beacon_count else ''}{f' -l {max_clients}' if max_clients else ''}{f' -m {keepalive_type}' if keepalive_type else ''}{f' -n {beacon_interval}' if beacon_interval else ''}{f' -p {psk}' if psk else ''}{f' -o {ht_caps}' if ht_caps else ''}{f' -q {beacon_stop}' if beacon_stop is not None else ''}{f' -r {tdi_flags}' if tdi_flags is not None else ''}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line,  protocol=Protocol.WIFI,
                                                        async_identifiers=[], timeout=timeout)
        else:
            status, data = self.issue_command(line)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.ap_beaconing = True        

    def stop_ap(self):
        self.logger.info(f"\n *** Initiating stop ap *** \n")
        self.reset()

    def version(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        return self.get_fw_version(expected_status)

    def get_fw_version(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        line = f"wifi.get_fw_version"
        self.logger.info(f"\n *** Initiating get firmware version *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line)
        self.verify_status(status, expected_status)
        payload = self.get_command_data(data)
        if payload is None:
            fw_match = re.search(rb"Firmware version is:\s*(.+?)\s*(?:[\r\n]|0x)", data)
            if fw_match:
                return fw_match.group(1).decode().strip()
            self.logger.error("Failed to parse firmware version response: %r", data)
            raise RuntimeError(
                f"Could not parse firmware version from DUT response: {data!r}"
            )
        fw_version_response = payload.replace(b"\r\n", b"").replace(b"\r", b"").decode()
        if "Firmware version is:" in fw_version_response:
            fw_version = fw_version_response.split("Firmware version is:")[1].strip()
        else:
            fw_version = fw_version_response.strip()
        return fw_version

    def get_mac_address(
            self, interface: int = 1, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Initiating get mac address *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"wifi.get_mac_address -i {interface}", protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(f"wifi.get_mac_address -i {interface}")
        self.verify_status(status, expected_status)
        return data.decode().strip()

    def get_statistics(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"\n *** Initiating get statistics *** \n")
        status, data = self.issue_command('wifi.get_statistics', timeout)
        self.verify_status(status, expected_status)
        return data

#######################################################################################################################################
    def get_statistics_v2(self,
                          interface: str = None,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 10):
        """Get NWP/PPE broadcast-multicast filter statistics (sli_wifi_get_statistics_v2)"""
        line = (f"wifi.get_statistics_v2"
                f"{f' -i {interface}' if interface else ''}")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                       async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        self.verify_status(status, expected_status)
        return data

    def get_client_info(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        self.logger.info(f"\n *** Get client information *** \n")
        status, data = self.issue_command("wifi.ap.get_client_info")
        self.verify_status(status, expected_status)

        match_result = re.findall(self.mac_address_expression, data)
        if status == expected_status and not match_result:
            return

        for key, value in self.client_info.items():
            self.client_info[key] = []
        for i in match_result:
            self.client_info["mac_address"].append(i)
        return self.client_info["mac_address"]

    def disconnect_ap_client(
            self,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            client_mac=None,
            deauth_option: str = None,
            timeout=10
            ):
        self.logger.info(f"\n *** Initiating disconnect ap client for client : {client_mac}*** \n")
        line = f'wifi.ap.disconnect_ap_client {client_mac} {f" -u {deauth_option}" if deauth_option else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status)
        return data

    def is_interface_up(
            self, interface: str, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Initiating is interface up *** \n")
        status, data = self.issue_command(f"wifi.is_interface_up {interface}")
        self.verify_status(status, expected_status)

    def set_default_interface(
            self, interface: str, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Initiating set default interface *** \n")
        status, data = self.issue_command(f"wifi.set_default_interface {interface}")
        self.verify_status(status, expected_status)

    def get_default_interface(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        self.logger.info(f"\n *** Get default interface *** \n")
        status, data = self.issue_command(f"wifi.get_default_interface")
        self.verify_status(status, expected_status)
        return data

    def set_transmit_rate(
            self,
            rate_protocol: str,
            data_rate: str,
            interface: str = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info(
            f"\n *** Initiating set transmit rate for {interface} mode: {rate_protocol} and data rate: {data_rate} *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line=f'wifi.set_transmit_rate {rate_protocol} {data_rate}{f" -i {interface}" if interface else ""}',
                protocol=Protocol.WIFI)
        else:
            status, data = self.issue_command(
                f'wifi.set_transmit_rate {rate_protocol} {data_rate}{f" -i {interface}" if interface else ""}'
                )
        self.verify_status(status, expected_status)
        return data

    def get_transmit_rate(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        self.logger.info(f"\n *** Initiating get transmit rate *** \n")
        status, data = self.issue_command(f"wifi.get_transmit_rate")
        self.verify_status(status, expected_status)
        return data

    def join_multicast_address(
            self,
            interface: str,
            multicast_address: str,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        self.logger.info(f"\n *** Initiating get transmit rate *** \n")
        status, data = self.issue_command(
            f"net.join_multicast_address -i {interface} -p {multicast_address}", timeout
            )
        self.verify_status(status, expected_status)

    def leave_multicast_address(
            self,
            interface: str,
            multicast_address: str,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        self.logger.info(f"\n *** Initiating leave multicast address: {multicast_address}*** \n")
        status, data = self.issue_command(
            f"net.leave_multicast_address -i {interface} -p {multicast_address}", timeout
            )
        self.verify_status(status, expected_status)

    def generate_wps_pin(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        self.logger.info(f"\n *** Generate wps pin *** \n")
        status, data = self.issue_command(f"wifi.generate_wps_pin")
        self.verify_status(status, expected_status)
        return data

    def wifi_get_ap_client_list(
            self, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Get ap client list *** \n")
        status, data = self.issue_command(f"wifi.ap.get_client_list")
        self.verify_status(status, expected_status)

    def wifi_get_ap_client_count(
            self, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Get ap client count *** \n")
        status, data = self.issue_command(f"wifi.ap.get_client_count")
        self.verify_status(status, expected_status)

    def get_channel_info(
            self, interface: str = None, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Get channel information *** \n")
        status, data = self.issue_command(f"wifi.get_channel {interface}")
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            match_channel_result = re.split(r"and [\d-]*", data.decode())
            match_channel = match_channel_result[0].split(":")
            match_band_result = match_channel_result[1].split(":")
            match_band = match_band_result[1].split(" ")
            channel = match_channel[1]
            band = match_band[1]
            self.logger.info(f"Channel: {channel}, Band: {band}\n")
            return channel, band

#######################################################################################################################################
    def set_advanced_scan_configuration(
            self,
            adv_active_channel_time: int = 1000,
            adv_passive_channel_time: int = 0,
            adv_trigger_level: int = -40,
            adv_trigger_level_change: int = 10,
            adv_enable_multi_probe: int = 0,
            adv_enable_instant_scan: int = 0,
            has_adv_scan_bit_map: int = None,
            advanced_scan_bitmap: int = None,
            timeout: int = 10,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info("\n *** Enable set advance scan configuration *** \n")
        line = (f"wifi.set_advanced_scan_configuration "
                f"{f' -i {adv_active_channel_time}' if adv_active_channel_time is not None else ''}"
                f"{f' -j {adv_passive_channel_time}' if adv_passive_channel_time is not None else ''}"
                f"{f' -k {adv_trigger_level}' if adv_trigger_level is not None else ''}"
                f"{f' -l {adv_trigger_level_change}' if adv_trigger_level_change is not None else ''}"
                f"{f' -m {adv_enable_multi_probe}' if adv_enable_multi_probe is not None else ''}"
                f"{f' -n {adv_enable_instant_scan}' if adv_enable_instant_scan is not None else ''}"
                f"{f' -o {has_adv_scan_bit_map}' if has_adv_scan_bit_map is not None else ''}"
                f"{f' -p {advanced_scan_bitmap}' if advanced_scan_bitmap is not None else ''}")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line = line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line = line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_advanced_scan_configuration(
            self, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info("\n *** Get advance scan configuration *** \n")
        status, data = self.issue_command(f"wifi.get_advanced_scan_configuration")
        self.verify_status(status, expected_status)
        return data

    def stop_scan(
            self,
            interface: str = "client",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info("\n *** Enable Stop scan *** \n")
        status, data = self.issue_command(f"wifi.stop_scan -i {interface}")
        self.verify_status(status, expected_status)

    def set_roam_configuration(
            self,
            interface: str = "client",
            trigger_level: int = -40,
            trigger_level_change: int = 10,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info("\n *** Enable set roam configuration *** \n")
        status, data = self.issue_command(
            f"wifi.set_roam_configuration "
            f'{f"-i {interface} " if interface is not None else ""}'
            f'{f"{trigger_level} " if trigger_level else ""}'
            f'{f"{trigger_level_change}" if trigger_level_change else ""}'
            )
        self.verify_status(status, expected_status)

    def wifi_get_ap_config(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        self.logger.info("\n *** Enable wifi get ap configuration *** \n")
        status, data = self.issue_command(f"wifi.ap.get_configuration")
        self.verify_status(status, expected_status)
        return data

    @defaults("wifi")
    def wifi_test_client_configuration(
            self,
            ssid: str,
            passphrase: str,
            time: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        self.logger.info("\n *** Enable wifi test client configuration *** \n")
        status, data = self.issue_command(
            f'wifi.test_client_configuration {ssid} {passphrase} {f"-t {time}" if time else ""}',
            timeout,
            )
        self.verify_status(status, expected_status)

    def wifi_set_advanced_client_config(
            self,
            max_retry_attempts: int = None,
            scan_interval: int = None,
            beacon_missed_count: int = None,
            first_time_retry_enable: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            ):
        self.logger.info("\n *** Enable wifi set advanced client configuration *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f"wifi.client.set_advanced_config{f' -r {max_retry_attempts}' if max_retry_attempts is not None else ''}{f' -i {scan_interval}' if scan_interval else ''}{f' -b {beacon_missed_count}' if beacon_missed_count else ''}{f' -f {first_time_retry_enable}' if first_time_retry_enable else ''}",
                protocol=Protocol.WIFI)
        else:
            status, data = self.issue_command(
                f"wifi.client.set_advanced_config{f' -r {max_retry_attempts}' if max_retry_attempts is not None else ''}{f' -i {scan_interval}' if scan_interval else ''}{f' -b {beacon_missed_count}' if beacon_missed_count else ''}{f' -f {first_time_retry_enable}' if first_time_retry_enable else ''}"
                )
        self.verify_status(status, expected_status)

    # BSD SOCKET COMMANDS
    @defaults("iop_sockets")
    def socket(self, domain: str, stream_type: str, protocol: str, expected_status=SLStatus.SL_STATUS_OK,
               timeout: int = 10):
        """ Arguments
            domain = ["AF_INET"/"AF_INET6"]
            type = ["SOCK_STREAM"/"SOCK_DGRAM"/"SOCK_STREAM_NONBLOCK"]
            protocol = ["IPPROTO_TCP"/"IPPROTO_UDP"]
        """
        self.logger.info(f"\n *** Create {protocol} BSD Socket  *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.create {domain} {stream_type} {protocol}",
                                                        protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'bsd_socket.create {domain} {stream_type} {protocol}', timeout)

        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id = {socket_id}")
        self.sockets_info["sync_sockets"].append(socket_id)
        self.logger.info(f'\n\n *** Sync Socket id list = {self.sockets_info["sync_sockets"]}')
        return int(socket_id)

    @defaults("iop_sockets")
    def bind(self, socket_fd: int = None, device_ip: str = None, ip_len: int = None, server_port: int = None,
             asynch: int = None,
             ip_version=Si91xIpVersion.SL_IPV4_VERSION,
             expected_status=SLStatus.SL_STATUS_OK,
             timeout: int = 10):
        self.logger.info(f"\n *** Bind BSD Socket on {device_ip} *** \n")
        line = f'bsd_socket.bind {socket_fd} {device_ip} {ip_len} {server_port}{f" -j {asynch}" if asynch else ""}{f" -v {ip_version}" if ip_version is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(
                line,
                timeout)
        self.verify_status(status, expected_status, data)

    def bsdSockClose(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, async_timeout=70):
        self.logger.info(f"\n *** Close BSD Socket {socket_fd}*** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.close {socket_fd}", protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                f"bsd_socket.close {socket_fd} ", timeout
                )
        if self.sockets_info["sync_sockets"]:
            self.sockets_info["sync_sockets"].remove(str(socket_fd))
        self.logger.info(f'current sync socket id list = {self.sockets_info["sync_sockets"]}')
        self.verify_status(status, expected_status, data)
        return status, data

    def listen(
            self,
            socket_fd: int,
            backlog: int,
            asynch: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 30
            ):
        line = f"bsd_socket.listen {socket_fd} {backlog} -j {asynch}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)

    def bsdSocketAccept(
            self, socket_fd: int, asynch: int,
            ip_version=Si91xIpVersion.SL_IPV4_VERSION,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 30
            ):
        line = f"bsd_socket.accept {socket_fd}{f' -j {asynch}' if asynch else ''}{f' -v {ip_version}' if ip_version is not None else ''}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)
        return data

    def bsdSocketGetSockName(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
            ):
        status, data = self.issue_command(
            f"bsd_socket.get_sock_name {socket_fd}", timeout
            )
        self.verify_status(status, expected_status, data)

    def bsdSocketGetPeerName(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
            ):
        status, data = self.issue_command(
            f"bsd_socket.get_peer_name {socket_fd}", timeout
            )
        self.verify_status(status, expected_status, data)

    def bsdGetSocketOpt(
            self,
            socket_fd: int,
            option_name: str,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        status, data = self.issue_command(
            f"bsd_socket.get_opt {socket_fd} {option_name}", timeout
            )
        self.verify_status(status, expected_status, data)
        return status, data

    def bsdSetSocketOpt(
            self,
            socket_fd: int,
            option_level: str = 'SOL_TCP',
            option_name: str = 'TCP_ULP',
            option_val: str = "tls",
            tls_extensions_enable: int = 0,
            tls_sni_extension: str = "example.com",
            tls_alpn_enable: int = 0,
            tls_alpn_extension: str = "http/1.1",
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
    ):
        if tls_alpn_enable:
            address = self.allocate_memory(size=len(tls_alpn_extension) + 1)
            self.load_memory(address=address, size=len(tls_alpn_extension), write_content=tls_alpn_extension)

        self.logger.info(f"Setting Socket Option with {option_level} {option_name} {option_val}")
        line = (
            f"bsd_socket.set_opt {socket_fd} {option_level} {option_name} {option_val} "
            f"{f' -e {tls_extensions_enable}' if tls_extensions_enable else ''}"
            f"{f' -s {tls_sni_extension}' if tls_sni_extension and tls_extensions_enable else ''}"
            f"{f' -x {tls_alpn_enable}' if tls_alpn_enable else ''}"
            f"{f' -a {address}' if tls_alpn_enable and tls_alpn_extension else ''}"
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if tls_alpn_enable:
            self.memory_free(address)
        self.verify_status(status, expected_status)

    def bsdSetSocketOption(
            self,
            socket_fd: int,
            option_level: str = 'SOL_TCP',
            option_name: str = 'TCP_ULP',
            tv_sec: str = "0",
            tv_usec: str = "2000",
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = f"bsd_socket.set_option {socket_fd} {option_level} {option_name} {tv_sec} {tv_usec}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_dtls_extensions(
            self,
            socket_fd: int,
            tls_extension_sni_type: int,
            tls_extension_alpn_type: int,
            tls_sni_extension: str = None,
            tls_alpn_extension: str = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = (
            f'bsd_socket.set_dtls_extensions{f" -a {socket_fd}" if socket_fd else ""}'
            f'{f" -b {tls_sni_extension}" if tls_sni_extension is not None else ""}'
            f'{f" -c {tls_extension_sni_type}" if tls_extension_sni_type else ""}'
            f'{f" -d {tls_alpn_extension}" if tls_alpn_extension is not None else ""}'
            f'{f" -e {tls_extension_alpn_type}" if tls_extension_alpn_type else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def bsdSsetCustomSyncSockopt(
            self,
            socket_fd: int,
            option_level: str = Si91xCustomSyncSockOptParms.SOL_SOCKET,
            option_name: str = Si91xCustomSyncSockOptParms.SL_SO_CERT_INDEX,
            cert_index: int = 0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = f"bsd_socket.set_custom_sock_opt {socket_fd} {option_level} {option_name} {cert_index}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def bsdSetSocketOptAsync(
            self,
            socket_fd: int,
            option_level: str = Si91xCustomSyncSockOptParms.SOL_SOCKET,
            option_name: str = Si91xCustomSyncSockOptParms.SL_SI91X_SO_MAXRETRY,
            cert_index: int = 0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = f"bsd_socket.set_sock_opt_async {socket_fd} {option_level} {option_name} {cert_index}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("iop_sockets")
    def bsdSocketConnect(self, socket_fd: int, server_ip: str, ip_len: int, server_port: int,
                         is_nonblocking: int = 0,
                         expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(
            f"\n *** Initiate BSD socket connect for server_ip: {server_ip}, server_port: {server_port} *** \n")

        line = (
            f'bsd_socket.connect {socket_fd} {server_ip} {ip_len} {server_port}'
            f'{f" -i {is_nonblocking}" if is_nonblocking else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, protocol=Protocol.WIFI, timeout=timeout,
                                                        async_timeout=60)
        else:
            status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)
        return data

    def bsdSocketSend(self, socket_fd: int, data: str, higher_data_len=0, expected_status=SLStatus.SL_STATUS_OK,
                      timeout: int = 10):
        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        self.logger.info(
            f"\n *** Initiate BSD socket data transfer *** \n")
        line = (
            f'bsd_socket.send {socket_fd} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, receive_data)
        if status != SLStatus.SL_STATUS_OK:
            return status, receive_data.decode()
        output = receive_data.decode()
        send_no_of_bytes = re.search(r'\d+ bytes sent', output)
        if higher_data_len:
            self.memory_free(address)
        return send_no_of_bytes.group(0).split()[0]

    def dtlsSocketSendTo(
            self,
            socket_fd: int,
            port: int,
            data: str = None,
            ip_addr: str = None,
            has_high_data_len: int = None,
            data_buffer: str = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):

        line = (
            f'bsd_socket.dtls_sendto {socket_fd} {port}{f" -a {data}" if data is not None else ""}{f" -d {ip_addr}" if ip_addr is not None else ""}{f" -i {has_high_data_len}" if has_high_data_len is not None else ""}{f" -j {data_buffer}" if data_buffer is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)

    def bsdSocketSendTo(
            self,
            socket_fd: int,
            data: str,
            ip_addr: str,
            ip_len: int,
            port: int,
            higher_data_len=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        line = (
            f'bsd_socket.send_to {socket_fd} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""} {ip_addr} {ip_len} {port}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)
        if higher_data_len:
            self.memory_free(address)

    def bsdGetHostByName(
            self, url: str, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
            ):
        status, data = self.issue_command(f"bsd_socket.get_host_by_name {url}", timeout)
        self.verify_status(status, expected_status, data)

    def bsdSocketSelect(
            self,
            numberOfFds: int,
            time,
            timeout_disable=0,
            socket_fd: int = None,
            wait_on_write: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 40
            ):
        line = (
            f'bsd_socket.select {numberOfFds} {time}{f" -t {timeout_disable}"}'
            f'{f" -s {socket_fd}" if socket_fd is not None else ""}'
            f'{f" -w {wait_on_write}" if wait_on_write is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)
        return status, data

    def bsdSocketReceive(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, async_timeout: int = 40
            ):
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.receive {socket_fd}", protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                f"bsd_socket.receive {socket_fd}", timeout
                )
        self.verify_status(status, expected_status, data)
        decoded = data.decode(errors="ignore")
        matches = re.findall(r"Received:([^\r\n]+)", decoded)
        if not matches:
            raise AssertionError(
                f"bsd_socket.receive: no Received: payload in response (status={status}): {decoded!r}"
            )
        rx_data = matches[-1].strip()
        self.logger.info(f"rx_data :{rx_data}")

        return rx_data

    def bsdSocketReceiveFrom(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, async_timeout: int = 40
            ):
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.receive_from {socket_fd}", protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                f"bsd_socket.receive_from {socket_fd}", timeout
                )
        self.verify_status(status, expected_status, data)
        rx_data = re.findall(r'Received:(\w+)', data.decode())[-1]
        return rx_data

    def bsdAsyncSocketSelect(
            self,
            numberOfFds: int,
            time: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 40
            ):
        line = f"bsd_socket.async_select {numberOfFds} {time}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)
        return data

    def bsdAsyncEvent(
            self,
            time: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 40
            ):
        line = f"bsd_socket.async_event {time}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)

    def bsdAsyncSockClose(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, async_timeout: int = 70):
        self.logger.info(f"\n *** Close BSD Socket {socket_fd}*** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.async_close {socket_fd} ", Protocol.WIFI, [],
                                                        async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                f"bsd_socket.async_close {socket_fd} ", timeout
                )
        self.verify_status(status, expected_status, data)
        if self.sockets_info["async_sockets"]:
            self.sockets_info["async_sockets"].remove(str(socket_fd))
        self.logger.info(f'current async socket id list = {self.sockets_info["async_sockets"]}')

    @defaults("iop_sockets")
    def Asyncsocket(self, domain: str, stream_type: str, protocol: str, expected_status=SLStatus.SL_STATUS_OK,
                    timeout: int = 10):
        """ Arguments
            domain = ["AF_INET"/"AF_INET6"]
            type = ["SOCK_STREAM"/"SOCK_DGRAM"]
            protocol = ["IPPROTO_TCP"/"IPPROTO_UDP"]
        """
        self.logger.info(f"\n *** Create {protocol} BSD Socket  *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"bsd_socket.async_create {domain} {stream_type} {protocol}",
                                                        protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'bsd_socket.async_create {domain} {stream_type} {protocol}', timeout)

        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id{socket_id}")
        self.sockets_info["async_sockets"].append(socket_id)
        self.logger.info(f'\n\n *** Async Socket id list = {self.sockets_info["async_sockets"]}')
        return int(socket_id)

    # IOT SOCKET COMMANDS
    @defaults("iot_sockets")
    def iotSocketCreate(self, stream_type: str, protocol: str, address_family: str,
                        expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10):
        """ Arguments
            type = ["stream"/"dgram"]
            protocol = ["tcp"/"udp"]
            address_family = ["ipv4"/"ipv6"]
        """
        self.logger.info(f"\n *** Create {stream_type} type {protocol} Iot Socket  *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f"iot_socket.create {stream_type} {protocol} -j {address_family}",
                protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.create {stream_type} {protocol} -j {address_family}',
                                              timeout)
        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id{socket_id}")
        return int(socket_id)

    @defaults("iot_sockets")
    def iotSocketBind(
            self,
            socket: int,
            client_ip: str,
            port: int,
            ip_len: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10
            ):
        """ Arguments
            socket = pass socket-id
            client_ip = use dut-ip to bind the socket
            port = use any TCP/UDP valid port number or assign in harness file
            ip_len = [4/16]
        """
        self.logger.info(f"\n *** Initiating Iot socket bind operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.bind {socket} {client_ip} {port} -l {ip_len}', protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.bind {socket} {client_ip} {port} -l {ip_len}',
                                              timeout)
        self.verify_status(status, expected_status, data)

    def iotSocketListen(
            self, socket: int, backlog: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
            ):
        self.logger.info(f"\n *** Initiating Iot socket Listen operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.listen {socket} {backlog}', protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.listen {socket} {backlog}',
                                              timeout)
        self.verify_status(status, expected_status, data)

    @defaults("iot_sockets")
    def iotSocketAccept(
            self, socket: int, port: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 5
            ):
        self.logger.info(f"\n *** Initiating Iot socket Accept operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.accept {socket} {port}', protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.accept {socket} {port}',
                                              timeout)
        self.logger.info(f"\n *** Data= {data.decode().strip()}*** \n")
        self.verify_status(status, expected_status, data)
        return data.decode().strip()

    @defaults("iot_sockets")
    def iotSocketConnect(
            self,
            socket: int,
            server_ip: str,
            port: int,
            ip_len: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10
            ):
        """ Arguments
            socket = pass socket-id
            server_ip = use TCP/UDP server_ip or assign in harness file
            port = use any TCP/UDP valid port number or assign in harness file
            ip_len = [4/16]
        """
        self.logger.info(
            f"\n *** Initiate IoT socket connect for server_ip: {server_ip}, server_port: {port} *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f'iot_socket.connect {socket} {server_ip} {port} -l {ip_len}',
                                                        protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.connect {socket} {server_ip} {port} -l {ip_len}',
                                              timeout)
        self.verify_status(status, expected_status, data)
        return data

    def iotSocketReceive(self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout=10):
        self.logger.info(f"\n *** Initiating Iot socket receive operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.receive {socket}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.receive {socket}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)
        return data

    def iotSocketReceiveFrom(
            self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
            ):
        self.logger.info(f"\n *** Initiating Iot socket receive From operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.receive_from {socket}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.receive_from {socket}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)
        return data

    def iotSocketSend(self, socket: int, data: str, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10
                      ):
        self.logger.info(f"\n *** Initiating Iot socket send operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.send {socket} {data}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.send {socket} {data}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)

    def iotSocketSendTo(
            self,
            socket: int,
            data: str,
            ip: str,
            ip_len: int,
            port: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
        self.logger.info(f"\n *** Initiating Iot socket send_to operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.send_to {socket} {data} {ip} {port} -l {ip_len}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.send_to {socket} {data} {ip} {port} -l {ip_len}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)

    def iotSocketGetSockName(self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout=10):
        self.logger.info(f"\n *** Initiating Get Iot socket name operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.get_sock_name {socket}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.get_sock_name {socket}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)

    def iotSocketGetPeerName(self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout=10):
        self.logger.info(f"\n *** Initiating Get Iot socket peer name operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.get_peer_name {socket}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.get_peer_name {socket}', timeout)

        self.verify_status(status, expected_status, data)

    def iotSocketGetOpt(
            self, socket: int, opt_id: str, expected_status=SLStatus.SL_STATUS_OK, timeout=10
            ):
        self.logger.info(f"\n *** Initiating Get Iot socket option *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.get_opt {socket} {opt_id}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.get_opt {socket} {opt_id}', timeout)

        self.verify_status(status, expected_status, data)

    def iotSocketSetOpt(
            self,
            socket: int,
            opt_id: str,
            opt_value: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
        self.logger.info(f"\n *** Initiating Set Iot socket option *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.set_opt {socket} {opt_id} {opt_value}', protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.set_opt {socket} {opt_id} {opt_value}', timeout)

        self.verify_status(status, expected_status, data)

    def iotSocketClose(self, socket: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"\n *** Initiating Iot socket close operation *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.close {socket}', protocol=Protocol.WIFI, timeout=timeout,async_timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.close {socket}', timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)

    def iotSocketGetHostByName(
            self,
            url: str,
            address_family: str,
            ip_len: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
        self.logger.info(f"\n *** Initiating Iot socket get host by name *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f'iot_socket.get_host_by_name {url} {address_family} -l {ip_len}', protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(f'iot_socket.get_host_by_name {url} {address_family} -l {ip_len}',
                                              timeout)

        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        self.verify_status(status, expected_status, data)

    def verify_status(self, status, expected_status, data=None):
        if isinstance(expected_status, list):
            assert status in expected_status, f"expected status should be one of the ->{expected_status}, But " \
                                              f"received {SLStatus(status).name if status in list(SLStatus) else status} "
        else:
            if type(expected_status) == SLStatus:
                if (
                        expected_status is not None
                        and expected_status != SLStatus.SL_STATUS_IGNORE_RESULT
                ):
                    assert (
                            status == expected_status
                    ), f"{SLStatus(status).name if status in list(SLStatus) else status} != {SLStatus(expected_status).name}" \
                       f", status:{hex(status)}"
            else:
                if SLStatus.SL_STATUS_OK != status:
                    if type(expected_status) == BSDErrnoStatus:
                        result = re.search("errno: (\d+)", str(data))
                        status = BSDErrnoStatus(int(result.group(1), 10))
                        assert (
                                status == expected_status
                        ), f"{BSDErrnoStatus(status).name if status in list(BSDErrnoStatus) else status} !=" \
                           f" {BSDErrnoStatus(expected_status).name}, status:{hex(status)}"
                    elif type(expected_status) == IOTStatus:
                        result = re.search("\nError:(.*)\n", str(data))
                        status = IOTStatus(int(result[1], 10))
                        assert (
                                status == expected_status
                        ), f"{IOTStatus(status).name if status in list(IOTStatus) else status} !=" \
                           f" {IOTStatus(expected_status).name}, status:{hex(status)}"
                    elif type(expected_status) == LwipBSDErrnoStatus:
                        result = re.search("\nerrno:(.*)\n", str(data))
                        status = LwipBSDErrnoStatus(int(result[1], 10))
                        assert (
                                status == expected_status
                        ), f"{LwipBSDErrnoStatus(status).name if status in list(LwipBSDErrnoStatus) else status} !=" \
                           f" {LwipBSDErrnoStatus(expected_status).name} ,status:{hex(status)}"
                    elif type(expected_status) == LwipIOTErrorStatus:
                        result = re.search("\nError:(.*)\n", str(data))
                        status = LwipIOTErrorStatus(int(result[1], 10))
                        self.logger.info(f"{status} and {expected_status}")
                        assert (
                                status == expected_status
                        ), f"{LwipIOTErrorStatus(status).name if status in list(LwipIOTErrorStatus) else status} !=" \
                           f" {LwipIOTErrorStatus(expected_status).name} ,status:{hex(status)}"

    def start_wps(
            self,
            interface="ap",
            wps_mode="push_button",
            wps_pin: str = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info(f"\n *** Initiating start wps configuration *** \n")
        status, data = self.issue_command(
            f'wifi.ap.start_wps {interface} {wps_mode} {f"-p {wps_pin} " if wps_pin else ""}'
            )
        self.verify_status(status, expected_status)

    def start_client_wps(
            self,
            interface="client",
            wps_mode=0,  # 0-PBC, 1-PIN
            wps_role=0,  # 0-Enrollee, 1-Ragistrar
            wps_pin: str=None,
            auto_connect=True,
            null_response=False,
            timeout=130,
            async_timeout=200,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
    ):
        line = f'wifi.client.start_wps {interface}{f" -m {wps_mode}"}{f" -r {wps_role}"}{f" -n 1" if null_response else " -n 0"}{f" -a 1" if auto_connect else " -a 0"}{f" -p {wps_pin}" if wps_pin else ""}'

        self.logger.info(f"\n *** Initiating start wps configuration *** \n")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI, timeout=timeout,
                                                        async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line, timeout)

        if status == SLStatus.SL_STATUS_OK:
            self.associated = True
        self.verify_status(status, expected_status)
        self.logger.info(f"\n *** WPS Response Data: {data} *** \n")
        if expected_status != SLStatus.SL_STATUS_OK:
            return data

        response = data.decode('utf-8')
        lines = response.split(',')

        response_struct = {}
        for line in lines:
            if 'SSID:' in line and 'Length' not in line:
                response_struct['ssid'] = line.split('SSID:')[1].strip()
                if response_struct['ssid'] == '(empty)':
                    response_struct['ssid'] = ''
            elif 'SSID Length:' in line:
                response_struct['ssid_length'] = int(line.split('SSID Length:')[1].split('bytes')[0].strip())
            elif 'Security Type:' in line:
                response_struct['security_type'] = line.split('Security Type:')[1].strip()
            elif 'Status:' in line:
                response_struct['status'] = line.split('Status:')[1].strip()
            elif 'Key:' in line:
                response_struct['key'] = line.split('Key:')[1].strip()
            elif 'AP MAC Address' in line:
                response_struct['ap_mac_address'] = line.split(':', 1)[1].strip()
            elif 'Reserved' in line:
                response_struct['reserved'] = line.split(':')[1].strip()

        self.logger.info(f"\n Response Structure is:  {response_struct} \n")
        return response_struct


    def set_tx_power(
            self, tx_power_in_dBm: int, expected_status: SLStatus = SLStatus.SL_STATUS_OK
            ):
        self.logger.info(f"\n *** Configure/Set TX power: {tx_power_in_dBm} *** \n")
        status, data = self.issue_command(f"wifi.set_tx_power {tx_power_in_dBm}")
        self.verify_status(status, expected_status)

    def get_tx_power(
            self,
            expected_tx_power_in_dBm: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info(f"\n *** Get TX power *** \n")
        status, data = self.issue_command(f"wifi.get_tx_power")
        self.verify_status(status, expected_status)

        if (
                expected_status == SLStatus.SL_STATUS_OK
                and expected_tx_power_in_dBm is not None
        ):
            # Result specific logic
            returned_value = int(data.split("\r\n\r\n")[1].split(":")[1].strip())
            assert (
                    returned_value == expected_tx_power_in_dBm
            ), f"{returned_value} != {expected_tx_power_in_dBm}"

    # SL_NET COMMANDS
    def sl_net_init(self, mode: str = None, stats_arg: int = 0, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 10):
        self.logger.info(f"\n *** sl net initialization  *** \n")
        status, data = self.issue_command(f'net.init {mode}{f" -i {stats_arg}" if stats_arg else ""}', timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.inited = True
        return status

    def sl_net_deinit(self, mode: str = None, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 30):
        self.logger.info(f"\n *** sl net deinit *** \n")
        line = f'net.deinit {mode}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=timeout,
                                                        )
        else:
            status, data = self.issue_command(line, timeout)
        self.logger.info(f"status: {status}, data: {data}")
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.inited = False
            self.associated = False
            self.networked = False

    def sl_net_down(
            self, mode: str = None, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 30
            ):
        self.logger.info(f"\n *** sl net down *** \n")
        line = f"net.down {mode}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=timeout,
                                                        )
        else:
            status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.inited = True
            self.associated = False
        return status

    def sl_net_up(
            self,
            mode: str = None,
            profile_id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 100,
    ):
        self.logger.info(f"\n *** sl net up *** \n")
        line = f'net.up {mode} {f" -i {profile_id}" if profile_id else ""}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=timeout,
                                                        )
        else:
            status, data = self.issue_command(line, timeout)
        self.logger.info(f"status: {status}, data: {data}")
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def print_ip_command_handler( self,
                                 mode: str = "client",
                                 profile_id: int = None,
                                 ip_version: str = "ipv4",
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout: int = 20,
                                ):
        """ This function is to handle the print ip command for both ipv4 and ipv6 and return the parsed result in a structured format."""
        # Build the command line with optional parameters
        line = (f"net.print_ip {mode} "
                f"{f' -i {profile_id}' if profile_id is not None else ''}"
                f"{f' -p {ip_version}' if ip_version else ''}")

        # Issue the command and get the status and data
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        self.verify_status(status, expected_status)

        # If the status is OK, parse the data based on the IP version and return the structured result
        if status == SLStatus.SL_STATUS_OK:
            self.networked = True
            ip_info = self.get_command_data(data)

            # For IPv4, we expect the format to be "ip, netmask, gateway"
            if ip_version == 'ipv4':
                matches = re.findall(b"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info)
                assert (len(matches) == 3), f"Error parsing IP, netmask and gateway from {ip_info}"    
                ip, netmask, gateway = [match.strip() for match in matches]
                self.ip = self.IPConfig(ip=ip, netmask=netmask, gateway=gateway)
                self.logger.info(f"********ip*******:*******{self.ip}****{type(self.ip)}*")
                return self.ip
            # For IPv6, we expect the format to be "linklocaladdr, globaladdr, gateway"
            else:
                linklocaladdr = ip_info.split(b",")[0].strip().decode()
                global_addr = ip_info.split(b",")[1].strip().decode()
                gateway_addr = ip_info.split(b",")[2].strip().decode()
                return linklocaladdr, global_addr, gateway_addr

    def ping(
            self,
            server_ip,
            num_ping_attempts=10,
            ping_timeout=10,
            ip_version='ipv4',
            ping_size: int = 10,
            dest_mac: str = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30
            ):
        self.logger.info(f"\n *** Initiating ping for server_ip: {server_ip} *** \n")
        success_count = 0
        exp_count = num_ping_attempts
        if isinstance(server_ip, bytes):
            server_ip = server_ip.decode()
        while num_ping_attempts > 0:
            num_ping_attempts -= 1
            line = f"net.ping {ip_version} {server_ip} {ping_size}"
            
            if dest_mac:
                line += f" -i {dest_mac}"

            if self.test_agent_thread_enabled:
                status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                            timeout=timeout, async_timeout=30,
                                                            async_identifiers=[AsyncIdentifiers.PING],
                                                            event_expected="bytes received"
                                                            )
            else:
                status, data = self.issue_command(line)
            self.logger.info(f"ping status: {status}, data: {data}")
            self.verify_status(status, expected_status)
            if "bytes received" in data.decode():
                success_count += 1
                self.logger.info(f"ping success count: {success_count}")
            else:
                self.logger.info(f"ping failed")
            time.sleep(1)
        assert (success_count / exp_count) * 100 >= 80, "ping success count should be greater than 80 percent " \
                                                        "of  number of attempts"

    def sl_net_get_profile(
            self,
            profile_id: int,
            interface: str = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
       
        line = (
            f'net.get_profile{f" -a {interface}" if interface is not None else ""}'
            f'{f" -b {profile_id}" if profile_id  else ""}'
        )
 
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)
 
        self.verify_status(status, expected_status)
        ssid = None
        pattern = r'SSID0:\s*([^\s]+)'
        match = re.search(pattern, data.decode())
        if match:
            ssid = match.group(1)
        return ssid
 
    def sl_net_get_credential(
            self,
            cred_id: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
       
        line = (
            f'net.get_credential{f" -a {cred_id}" if cred_id else ""}'
        )
 
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)
 
        self.verify_status(status, expected_status)
        credential_id = None
        pattern = r'CREDENTIAL0:\s*(\d+)'
        match = re.search(pattern, data.decode())
        if match:
            credential_id = match.group(1)
        return credential_id



    def sl_net_set_profile(
            self,
            ssid: str = None,
            channel: int = None,
            security: int = None,
            encryption: int = None,
            credential_id: int = None,
            priority: int = None,
            profile_id: int = None,
            ip_type: str = None,
            interface: str = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):

        line = (
            f'net.set_profile{f" {ssid}"}'
            f'{f" -a {channel}" if channel else ""}'
            f'{f" -b {security}"}'
            f'{f" -c {encryption}" if encryption else ""}'
            f'{f" -d {credential_id}"}'
            f'{f" -e {ip_type}" if ip_type is not None else ""}'
            f'{f" -f {priority}" if priority else ""}'
            f'{f" -g {interface}" if interface is not None else ""}'
            f'{f" -h {profile_id}" if profile_id else ""}'
        )
 
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)
 
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def sl_net_set_application_profile( self,
                                        profile_group: int = None,
                                        expected_status=SLStatus.SL_STATUS_OK,
                                        timeout=10
                                      ):
        """Set application power/behavior profile"""
        # Build the command line with optional parameters
        line = (
                f'net.set_application_profile'
                f'{f" -a {profile_group}" if profile_group is not None else ""}'
            )

        # Issue the command and get the status and data
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the status and data
        self.verify_status(status, expected_status)

    def sl_net_set_eap_credential(
            self,
            username: str = None,
            password: str = None,
            certificate_id: int = None,
            eap_flags: int = None,
            credential_id: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
    ):
        """
        Set EAP enterprise credentials using the net.set_eap_credential command.

        Args:
            username: Enterprise username for authentication
            password: Enterprise password for authentication
            certificate_id: Certificate ID for enterprise authentication (optional)
            eap_flags: EAP configuration flags (optional)
            credential_id: Credential ID to store the EAP credentials (optional)
            expected_status: Expected status code
            timeout: Command timeout in seconds
        """

        line = (
            f'net.set_eap_credential{f" {username}" if username else ""}'
            f'{f" {password}" if password else ""}'
            f'{f" -c {certificate_id}" if certificate_id is not None else ""}'
            f'{f" -f {eap_flags}" if eap_flags is not None else ""}'
            f'{f" -i {credential_id}" if credential_id is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line, timeout)

        self.verify_status(status, expected_status)
 
    def sl_net_set_credential(
            self,
            credential: str = None,
            type: int = None,
            cred_id: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10
            ):
       
        line = (
            f'net.set_credential{f" {credential}"}'
            f'{f" -a {type}" if type else ""}'
            f'{f" -b {cred_id}" if cred_id else ""}'
        )
 
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)
 
        self.verify_status(status, expected_status)
        
    @defaults("thread_params")
    def initialize_thread(self, thread_id: int = 0, stack_len: int = 2048, buffer_len: int = 128,
                          expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, priority: int = 0):
        """
        :param thread_id:
        :param stack_len:
        :param buffer_len:
        :param expected_status:
        :param timeout:
        :param priority:
        :return:
        """

        line = (f'thread {thread_id} {stack_len} {buffer_len}'
                f'{f" -p {priority}" if priority else ""}')

        status, data = self.issue_command(line, timeout)
        self.verify_status(status, expected_status, data)

    @defaults("wifi")
    def load_certificate(self,
                         load: int,
                         certificate_index: int,
                         type: int,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout: int = 10,
                         ):
        status = self.issue_command(f'wifi.load_certificate -l {load} -i {certificate_index} -t {type}', timeout)
        self.verify_status(status, expected_status)

    @defaults("mqtt")
    def set_advanced_mqtt_client_configuration(self,
                                               server_port: int = 1883,
                                               is_connection_encrypted: bool = False,
                                               connect_timeout: int = 5,
                                               keep_alive_interval: int = 0,
                                               is_clean_session: bool = True,
                                               client_id: str = None,
                                               client_port: int = 1883,
                                               is_retained: bool = True,
                                               qos: int = 0,
                                               will_topic: str = None,
                                               will_message: str = None,
                                               ip_version: str = None,
                                               keep_alive_retries: int = 0,
                                               host_name: str = None,
                                               enable_sni: bool = False,
                                               sni_host_name: str = None,
                                               tls_flags: int = None,
                                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                               timeout: int = 10,
                                               ):
        qos_levels = {0: 'qos0', 1: 'qos1', 2: 'qos2'}
        self.logger.info("Sending mqtt client configuration command with following parameters:\n"
                         f'{f",i::server_port:{server_port}" if server_port is not None else ""}'
                         f'{f",j::is_connection_encrypted:{is_connection_encrypted}" if is_connection_encrypted is not None else ""}'
                         f'{f",k::connect_timeout:{connect_timeout}" if connect_timeout is not None else ""}'
                         f'{f",l::keep_alive_interval:{keep_alive_interval}" if keep_alive_interval is not None else ""}'
                         f'{f",m::is_clean_session:{is_clean_session}" if is_clean_session is not None else ""}'
                         f'{f",n::client_id:{client_id}" if client_id is not None else ""}'
                         f'{f",o::client_id_length:{len(client_id)}" if client_id is not None else ""}'
                         f'{f",p::client_port:{client_port}" if client_port is not None else ""}'
                         f'{f",q::is_retained:{is_retained}" if is_retained is not None else ""}'
                         f'{f",r::qos:{qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}'
                         f'{f",s::will_topic:{will_topic}" if will_topic is not None else ""}'
                         f'{f",t::will_topic_len:{len(will_topic)}" if will_topic is not None else ""}'
                         f'{f",u::will_message:{will_message}" if will_message is not None else ""}'
                         f'{f",v::will_message_len:{len(will_message)}" if will_message is not None else ""}'
                         f'{f",a::ip_version:{ip_version}" if ip_version is not None else ""}'
                         f'{f",b::keep_alive_retries:{keep_alive_retries}" if keep_alive_retries is not None else ""}'
                         f'{f",c::host_name:{host_name}" if host_name is not None else ""}'
                         f'{f",d::enable_sni:{enable_sni}" if enable_sni is not None else ""}'
                         f'{f",e::sni_host_name:{sni_host_name}" if sni_host_name is not None else ""}'
                         f'{f",f::tls_flags:{tls_flags}" if tls_flags is not None else ""}'
                         )
        if client_id is not None:
            address = self.allocate_memory(size=len(client_id) + 1)
            self.load_memory(address=address, size=len(client_id), write_content=client_id)
            self.dut_mqtt_client_id_address = address

        if will_topic is not None:
            will_topic_address = self.allocate_memory(size=len(will_topic) + 1)
            self.load_memory(address=will_topic_address, size=len(will_topic), write_content=will_topic)

        line = (
            f'mqtt.set_advanced_client_configuration{f" -i {server_port}" if server_port else ""}'
            f'{f" -j true" if is_connection_encrypted else ""}{f" -k {connect_timeout}" if connect_timeout else ""}{f" -l {keep_alive_interval}" if keep_alive_interval is not None else ""}'
            f'{f" -m true" if is_clean_session else ""}'
            f'{f" -n {address}" if client_id is not None else ""}'
            f'{f" -o {len(client_id)}" if client_id is not None else ""}'
            f'{f" -p {client_port}"}{f" -q true" if is_retained else ""}'
            f'{f" -r {qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}'
            f'{f" -s {will_topic_address}" if will_topic is not None else ""} {f" -t {len(will_topic)}" if will_topic is not None else ""}'
            f'{f" -u {will_message}" if will_message is not None else ""} {f" -v {len(will_message)}" if will_message is not None else ""}'
            f'{f" -a {ip_version}" if ip_version is not None else ""}'
            f'{f" -b {keep_alive_retries}" if keep_alive_retries is not None else ""}'
            f'{f" -c {host_name}" if host_name is not None else ""}'
            f'{f" -d true" if enable_sni else ""}'
            f'{f" -e {sni_host_name}" if sni_host_name is not None else ""}'
            f'{f" -f {tls_flags}" if tls_flags is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        if will_topic is not None:
            self.memory_free(will_topic_address)

    @defaults("mqtt")
    def mqtt_client_set_tcp_tls_advanced_configuration(
            self,
            tcp_keepalive_initial_time_sec: int = 180,
            tcp_max_retry_count: int = 10,
            max_retransmission_timeout_value: int = 3,
            ssl_ciphers_bitmap: int = 0,
            ssl_ext_ciphers_bitmap: int = 0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = (
            "mqtt.set_tcp_tls_advanced_configuration"
            f" -a {tcp_keepalive_initial_time_sec}"
            f" -b {tcp_max_retry_count}"
            f" -c {max_retransmission_timeout_value}"
            f" -d {ssl_ciphers_bitmap}"
            f" -e {ssl_ext_ciphers_bitmap}"
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], timeout=timeout)
        else:
            status, data = self.issue_command(line)
        self.verify_status(status, expected_status)

    @defaults("mqtt")
    def mqtt_client_connect_to_server(self,
                                      server: MqttServer,
                                      mqtt_server: str = None,
                                      send_credentials: bool = False,
                                      username: str = None,
                                      password: str = None,
                                      expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                                      sync_timeout: int = 0,
                                      timeout: int = 15,
                                      ):
        self.logger.info(f"Sending mqtt client connect command with following parameters:\n"
                         f'{f",mqtt_server:{mqtt_server}" if mqtt_server is not None else server.hostname_or_ip_address}'
                         f'{f",i::send_credentials:{send_credentials}" if send_credentials is not None else ""}'
                         f'{f",j::username:{username}" if username is not None else ""}'
                         f'{f",k::password:{password}" if password is not None else ""}'
                         f'{f",l::sync_timeout:{sync_timeout}" if sync_timeout is not None else ""}')
        if username is not None:
            address1 = self.allocate_memory(size=len(username) + 1)
            self.load_memory(address=address1, size=len(username), write_content=username)
        if password is not None:
            address2 = self.allocate_memory(size=len(password) + 1)
            self.load_memory(address=address2, size=len(password), write_content=password)
        line = (
            f'mqtt.connect {f"{mqtt_server}" if mqtt_server is not None else server.hostname_or_ip_address}{f" -i true" if send_credentials else ""}'
            f'{f" -j {address1}" if username is not None else ""}{f" -k {address2}" if password is not None else ""}{f" -l {sync_timeout}"}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [AsyncIdentifiers.MQTT_CONNECT_EVENT],
                                                        async_timeout=30, timeout=timeout)
        else:
            status, data = self.issue_command(line)
        self.verify_status(status, expected_status)
        if username is not None:
            self.memory_free(address1)
        if password is not None:
            self.memory_free(address2)
        if self.dut_mqtt_client_id_address:
            self.memory_free(self.dut_mqtt_client_id_address)
            self.dut_mqtt_client_id_address = 0
        self.mqtt_state_connected = True

    def mqtt_client_subscribe(self,
                              topic: str = None,
                              qos: int = 0,
                              sync_timeout: int = 0,
                              expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                              timeout: int = 15,
                              topic_address = None,
                              ):
        qos_levels = {0: 'qos0', 1: 'qos1', 2: 'qos2'}
        self.logger.info(f"Sending mqtt client subscribe command with following parameters:\n"
                         f'{f",a::topic:{topic}" if topic is not None else ""}'
                         f'{f",b::topic_len:{len(topic)}" if topic is not None else ""}'
                         f'{f",c::qos:{qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}'
                         f'{f",l::sync_timeout:{sync_timeout}" if sync_timeout is not None else ""}')

        allocated_topic_address = topic_address is None and topic is not None
        if topic_address is None:
            if topic is not None:
                address = self.allocate_memory(size=len(topic) + 1)
                self.load_memory(address=address, size=len(topic), write_content=topic)
        else:
            address = topic_address


        line = (
            f'mqtt.subscribe {f" -a {address}" if topic is not None else ""}{f" -b {len(topic)}" if topic is not None else ""}'
            f'{f" -c {qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}{f" -l {sync_timeout}"}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.MQTT_SUBSCRIBE_EVENT],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        if allocated_topic_address:
            self.memory_free(address)

    def mqtt_client_publish(self,
                            qos: int = 0,
                            retain: bool = False,
                            is_duplicate_message: bool = False,
                            topic: str = None,
                            message: str = None,
                            sync_timeout: int = 0,
                            expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                            timeout: int = 15,
                            msg_address=None,
                            topic_address=None,
                            async_timeout: int = 30,
                            ):
        qos_levels = {0: 'qos0', 1: 'qos1', 2: 'qos2'}
        self.logger.info(f"Sending mqtt client publish command with following parameters:\n"
                         f'{f",m::qos:{qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}'
                         f'{f",n::retain:{retain}" if retain is not None else ""}'
                         f'{f",o::is_duplicate_message:{is_duplicate_message}" if is_duplicate_message is not None else ""}'
                         f'{f",p::topic:{topic}" if topic is not None else ""}'
                         f'{f",q::topic_len:{len(topic)}" if topic is not None else ""}'
                         f'{f",r::message:{message}" if message is not None else ""}'
                         f'{f",s::message_len:{len(message)}" if message is not None else ""}'
                         f'{f",t::sync_timeout:{sync_timeout}" if sync_timeout is not None else ""}')
        if msg_address is None:
            if message is not None:
                address = self.allocate_memory(size=len(message) + 1)
                self.load_memory(address=address, size=len(message), write_content=message)
        else:
            address = msg_address
        if topic_address is None:
            if topic is not None:
                address1 = self.allocate_memory(size=len(topic) + 1)
                self.load_memory(address=address1, size=len(topic), write_content=topic)
        else:
            address1 = topic_address
        line = (
            f'mqtt.publish {f" -m {qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}{f" -n true" if retain else ""}'
            f'{f" -o true" if is_duplicate_message else ""}{f" -p {address1}" if topic is not None else ""}{f" -q {len(topic)}" if topic is not None else ""}'
            f'{f" -r {address}" if message is not None else ""}{f" -s {len(message)}" if message is not None else ""}{f" -t {sync_timeout}"}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.MQTT_PUBLISH_EVENT],
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        if msg_address is None:
            if message is not None:
                self.memory_free(address)
        if topic_address is None:
            if topic is not None:
                self.memory_free(address1)

    def mqtt_client_publish_allocate_mem(self,
                                         qos: int = 0,
                                         retain: bool = False,
                                         is_duplicate_message: bool = False,
                                         topic: str = None,
                                         message: str = None,
                                         sync_timeout: int = 0,
                                         expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                                         timeout: int = 15,
                                         load_mem=False,
                                         message_address=None,
                                         topic_address=None,
                                         ):
        qos_levels = {0: 'qos0', 1: 'qos1', 2: 'qos2'}
        self.logger.info(f"Sending mqtt client publish command with following parameters:\n"
                         f'{f",m::qos:{qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}'
                         f'{f",n::retain:{retain}" if retain is not None else ""}'
                         f'{f",o::is_duplicate_message:{is_duplicate_message}" if is_duplicate_message is not None else ""}'
                         f'{f",p::topic:{topic}" if topic is not None else ""}'
                         f'{f",q::topic_len:{len(topic)}" if topic is not None else ""}'
                         f'{f",r::message:{message}" if message is not None else ""}'
                         f'{f",s::message_len:{len(message)}" if message is not None else ""}'
                         f'{f",t::sync_timeout:{sync_timeout}" if sync_timeout is not None else ""}')
        if load_mem is not True:
            self.logger.info(f"Allocating default memory ")
            if message is not None:
                address = self.allocate_memory(size=len(message) + 1)
                self.load_memory(address=address, size=len(message), write_content=message)
            if topic is not None:
                address1 = self.allocate_memory(size=len(topic) + 1)
                self.load_memory(address=address1, size=len(topic), write_content=topic)

        if load_mem is True:
            self.logger.info(f"Allocating memory from test case")
            if message is not None:
                address = message_address
                self.logger.info(f"Message received is {message}")
                self.logger.info(f"Message address from test case {address}")
            if topic is not None:
                address1 = topic_address
                self.logger.info(f"Topic received is  {topic}")
                self.logger.info(f"Topic address from test case {address1}")

        line = (
            f'mqtt.publish {f" -m {qos_levels.get(qos)}" if qos in qos_levels.keys() else "qos0"}{f" -n true" if retain else ""}'
            f'{f" -o true" if is_duplicate_message else ""}{f" -p {address1}" if topic is not None else ""}{f" -q {len(topic)}" if topic is not None else ""}'
            f'{f" -r {address}" if message is not None else ""}{f" -s {len(message)}" if message is not None else ""}{f" -t {sync_timeout}"}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.MQTT_PUBLISH_EVENT],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        if message is not None:
            self.memory_free(address)
        if topic is not None:
            self.memory_free(address1)

    def mqtt_client_unsubscribe(self,
                                topic: str = None,
                                sync_timeout: int = 0,
                                expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                                timeout: int = 15,
                                ):
        self.logger.info(f"Sending mqtt client unsubscribe command with following parameters:\n"
                         f'{f",s::topic:{topic}" if topic is not None else ""}'
                         f'{f",u::topic_len:{len(topic)}" if topic is not None else ""}'
                         f'{f",p::sync_timeout:{sync_timeout}" if sync_timeout is not None else ""}')
        if topic is not None:
            address = self.allocate_memory(size=len(topic) + 1)
            self.load_memory(address=address, size=len(topic), write_content=topic)
        line = f'mqtt.unsubscribe {f" -s {address}" if topic is not None else ""}{f" -u {len(topic)}" if topic is not None else ""}{f" -p {sync_timeout}"}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.MQTT_UNSUBSCRIBE_EVENT],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        if topic is not None:
            self.memory_free(address)

    def mqtt_client_disconnect(self,
                               sync_timeout: int = 0,
                               expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                               timeout: int = 15,
                               async_timeout: int = 30,
                               ):
        line = f"mqtt.disconnect -e {sync_timeout}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.MQTT_DISCONNECT_EVENT],
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        self.mqtt_state_connected = False

    def mqtt_client_deinit(self,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout: int = 15):
        line = f"mqtt.deinit"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line)

        self.verify_status(status, expected_status)
        self.mqtt_state_connected = False

    def set_profile(
            self,
            interface: str = "client",
            profile_id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=3,
            ):
        line = f'nvm.set_profile {interface} -i {profile_id}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_wifi_region(
            self,
            region_code: Optional[Si91xRegionCode] = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=3,
            ):
        line = f"wifi.set_wifi_region -i {region_code}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_dns_address(
            self,
            primary_dns_server_address: str = "NULL",
            secondary_dns_server_address: str = "NULL",
            interface=Si91xInterface.SL_WIFI_CLIENT_2_4GHZ_INTERFACE,
            primary_dns_server_ip_version=Si91xIp.SL_IPV4,
            secondary_dns_server_ip_version=Si91xIp.SL_IPV4,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        """
        Set DNS address for primary and secondary DNS servers.

        Arguments:
        primary_dns_server_address:: expected input is NULL or valid ipv4 address or ipv6 address
        secondary_dns_server_address:: expected input is NULL or valid ipv4 address or ipv6 address
        interface:: expected input is client or ap. It selects client by default in the test agent when not provided
        primary_dns_server_ip_version:: expected input is ipv4 or ipv6. It selects ipv4 by default in the test agent when not provided
        secondary_dns_server_ip_version:: expected input is ipv4 or ipv6. It selects ipv4 by default in the test agent when not provided

        When primary_dns_server_address and secondary_dns_server_address are NULL, DUT uses DNS server received in the DHCP process for DNS query.
        Otherwise, it selects the static primary and secondary DNS server address provided using this API.
        """
        # Logging the set DNS command
        self.logger.info(f"Sending set_dns_server CLI command with the following parameters:\n"
                         f"primary_dns_server_address: {primary_dns_server_address}, "
                         f"secondary_dns_server_address: {secondary_dns_server_address}, "
                         f"interface: {interface}, "
                         f"primary_dns_server_ip_version: {primary_dns_server_ip_version}, "
                         f"secondary_dns_server_ip_version: {secondary_dns_server_ip_version}")

        # Constructing the command line
        line = (
            f'dns.set_dns_server {primary_dns_server_address} {secondary_dns_server_address} '
            f'{f"-i {interface}" if interface is not None else ""} '
            f'{f"-p {primary_dns_server_ip_version}" if primary_dns_server_ip_version is not None else ""} '
            f'{f"-s {secondary_dns_server_ip_version}" if secondary_dns_server_ip_version is not None else ""}'
        )

        # Issue the command based on whether the test agent thread is enabled or not
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.logger.info(f"STATUS = {status}, DATA = {data}")
        if status == SLStatus.SL_STATUS_TIMEOUT:
            return status
        elif status == SLStatus.SL_STATUS_INVALID_PARAMETER:
            return status
        else:
            # Verify if the status matches the expected status
            self.verify_status(status, expected_status)

    def dns_get(
            self,
            domain_name: str = "www.google.com",
            query_timeout: int = 20,
            ip_version: str = "ipv4",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            negative_flag=False,
            timeout=10,
            async_timeout=300,
            ):
        # Constructing the DNS query command
        line = f'dns.get_host_by_name {domain_name} -i {query_timeout} -j {ip_version}'
        # Issue the command based on whether the test agent thread is enabled or not
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        if negative_flag:
            self.logger.info(f"STATUS = {status}, DATA = {data}")
            return status

        else:
            self.verify_status(status, expected_status)
            result = self.get_command_data(data)
            return result.strip()

#######################################################################################################################################
    def dns_get_host_by_name_v2(
            self,
            domain_name: str = "www.google.com",
            timeout_sec: int = None,
            ip_version: str = None,
            retry_count: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            async_timeout=300,
            ):
        line = (
            f'dns.get_host_by_name_v2 {domain_name}'
            f'{f" -i {timeout_sec}" if timeout_sec is not None else ""}'
            f'{f" -j {ip_version}" if ip_version else ""}'
            f'{f" -k {retry_count}" if retry_count is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=async_timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return status

    def http_client_init(self,
                         username: str = None,
                         password: str = None,
                         interface: str = "client",
                         ip_version: str = "ipv4",
                         https_enable: bool = False,
                         http_version: str = "http_v_1_1",
                         tls_version: str = "tls_v_1_2",
                         certificate_index: int = 0,
                         sni_enable: bool = None,
                         url: str = None,
                         sni_type: int = 1,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=30,
                         ):
        line = (
            f'http_client.init {f"-i {username}" if username is not None else ""}{f" -j {password}" if password is not None else ""}'
            f'{f" -k {interface}"}{f" -l {ip_version}"}{f" -m {http_version}"}{f" -n true" if https_enable else ""}'
            f'{f" -o {tls_version}"}{f" -p {certificate_index}" if not certificate_index else ""}'
            f'{f" -q true" if sni_enable is not None else ""}{f" -r {url}" if url is not None else ""}{f" -s {sni_type}" if sni_type is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return status

#######################################################################################################################################
    def http_client_set_tcp_tls_advanced_config(
            self,
            tcp_keepalive_initial_time_sec: int = None,
            tcp_max_retry_count: int = None,
            max_retransmission_timeout_value: int = None,
            ssl_ciphers_bitmap: int = None,
            ssl_ext_ciphers_bitmap: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ):
        line = (
            f'http_client.set_tcp_tls_advanced_config'
            f'{f" -a {tcp_keepalive_initial_time_sec}" if tcp_keepalive_initial_time_sec is not None else ""}'
            f'{f" -b {tcp_max_retry_count}" if tcp_max_retry_count is not None else ""}'
            f'{f" -c {max_retransmission_timeout_value}" if max_retransmission_timeout_value is not None else ""}'
            f'{f" -d {ssl_ciphers_bitmap}" if ssl_ciphers_bitmap is not None else ""}'
            f'{f" -e {ssl_ext_ciphers_bitmap}" if ssl_ext_ciphers_bitmap is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return status

    def http_client_request_init(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            server_ip: str = None,
            host_name: str = None,
            server_port: int = 80,
            put_data_length=None,
            http_method_type: int = 3,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ) -> Tuple[int, bytes]:
        if resource_path is not None:
            address = self.allocate_memory(size=len(resource_path) + 1)
            self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        line = (
            f'http_client.request_init {f" -i {ip_addr}"}{f" -p {server_port}" if server_port else ""}{f" -h {host_name}" if host_name else ""}'
            f'{f" -r {address}" if resource_path is not None else ""}{f" -b {put_data_length}" if put_data_length is not None else ""}{f" -t {http_method_type}" if http_method_type is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        data = self.get_command_data(data)
        if resource_path is not None:
            self.memory_free(address)
        return status, data

    def http_client_send_request(self,
                                 http_method_type: int = 3,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout=30,
                                 ):
        line = (
            f'http_client.send_request {f" -t {http_method_type}" if http_method_type is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    def set_config(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                   code=0,  # SET_XTAL_GOOD_TIME_FROM_HOST,SET_PMU_GOOD_TIME_FROM_HOST
                   config_val=100,
                   timeout=10):
        line = f"set_nwp_config {code} {config_val}"
        self.logger.info(f"**** initiating  ble_set_random_addr Cli command  *****")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
            )
        else:
            status = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)

    def http_get(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            server_ip: str = None,
            server_port: int = 80,
            higher_url_length: int = 0,
            url_address=None,
            skip_http_data_print=0,
            http_print_plain_text=0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ) -> Tuple[int, bytes]:
        len_url = len(resource_path)
        if len_url > 80:
            higher_url_length = 1
        if url_address is None:
            if higher_url_length:
                if resource_path is not None:
                    address = self.allocate_memory(size=len(resource_path) + 1)
                    self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        else:
            address = url_address
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)

        if server_ip is not None:
            host_name = None
        else:
            host_name = ip_addr

        line = (
            f'http_client.get {f"-i {ip_addr}"}{f" -p {server_port}" if server_port else ""}{f" -l {higher_url_length}" if higher_url_length else ""} '
            f'{f" -r {address}" if higher_url_length else ""}{f" -o {resource_path}" if not higher_url_length else ""}{f" -h {host_name}" if host_name else ""}{f" -s {skip_http_data_print}" if skip_http_data_print else ""}{f" -t {http_print_plain_text}" if http_print_plain_text else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.HTTP_EVENT])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if url_address is None:
            if higher_url_length:
                if resource_path is not None:
                    self.memory_free(address)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            if (skip_http_data_print == 1) or (http_print_plain_text == 1):
                return status, data
            else:
                # Firmware prints "<base64>end". Do not use data.split(b"end"):
                # concurrent BSD traffic (C19218) includes "bsd_socket.send", and
                # the substring "end" inside "send" falsely splits the buffer and
                # feeds UART junk to b64decode (binascii 221 / len%4==1).
                # Require a real base64 run ({8,}) before "end" so "send" does not
                # match; strip a leading Fxxxx event header; ignore invalid chunks.
                decode_data = b""
                body_matches = list(
                    re.finditer(rb"((?:F[0-9A-Fa-f]{4})?[A-Za-z0-9+/]{8,}={0,2})end", data)
                )
                chunks = []
                if body_matches:
                    for match in body_matches:
                        raw = match.group(1)
                        f_hdrs = list(re.finditer(rb"F[0-9A-Fa-f]{4}", raw))
                        if f_hdrs:
                            raw = raw[f_hdrs[-1].end() :]
                        chunks.append(raw)
                elif b"end" in data:
                    # URL-length / split-frame: drop status tails after final end
                    region = data.rsplit(b"end", 1)[0]
                    f_hdrs = list(re.finditer(rb"F[0-9A-Fa-f]{4}", region))
                    if f_hdrs:
                        region = region[f_hdrs[-1].end() :]
                    chunk = re.sub(rb"[^A-Za-z0-9+/=]", b"", region)
                    if chunk:
                        chunks.append(chunk)
                for chunk in chunks:
                    data_chars = chunk.rstrip(b"=")
                    if not data_chars or len(data_chars) % 4 == 1:
                        continue
                    pad = (-len(data_chars)) % 4
                    try:
                        decode_data += b64decode(data_chars + b"=" * pad)
                    except Exception:
                        continue
                return status, decode_data

    def http_post(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            post_data: str = None,
            server_ip: str = None,
            server_port: int = 80,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ) -> Tuple[int, bytes]:
        if resource_path is not None:
            address = self.allocate_memory(size=len(resource_path) + 1)
            self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        line = (
            f'http_client.post {f"-i {ip_addr}"}{f" -p {server_port}" if server_port else ""}'
            f'{f" -r {address}" if resource_path is not None else ""}{f" -b {post_data}" if post_data is not None else ""}{f" -l {len(post_data)}" if post_data is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if resource_path is not None:
            self.memory_free(address)
        return status, data

    def http_post_allocate_mem(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            post_data: str = None,
            server_ip: str = None,
            server_port: int = 80,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            load_mem=False,
            ) -> Tuple[int, bytes]:
        if load_mem is not True:
            self.logger.info("Allocating default memory location")
            if resource_path is not None:
                address = self.allocate_memory(size=len(resource_path) + 1)
                self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        if load_mem is True:
            self.logger.info("Allocating memory from test case")
            address = resource_path
            self.logger.info(f"Address allocated from test case {address}")
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        line = (
            f'http_client.post {f"-i {ip_addr}"}{f" -p {server_port}" if server_port else ""}'
            f'{f" -r {address}" if resource_path is not None else ""}{f" -b {post_data}" if post_data is not None else ""}{f" -l {len(post_data)}" if post_data is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        if resource_path is not None:
            self.memory_free(address)
        return status, data

    def http_put(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            server_ip: str = None,
            host_name: str = None,
            server_port: int = 80,
            put_data_length=None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ) -> Tuple[int, bytes]:
        if resource_path is not None:
            address = self.allocate_memory(size=len(resource_path) + 1)
            self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        line = (
            f'http_client.put {f" -i {ip_addr}"}{f" -p {server_port}" if server_port else ""}{f" -h {host_name}" if host_name else ""}'
            f'{f" -r {address}" if resource_path is not None else ""}{f" -b {put_data_length}" if put_data_length is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        data = self.get_command_data(data)
        if resource_path is not None:
            self.memory_free(address)
        return status, data

    def http_put_allocate_mem(
            self,
            server: WebServerInterface,
            resource_path: str = None,
            server_ip: str = None,
            host_name: str = None,
            server_port: int = 80,
            put_data_length=None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            load_mem=False,
            ) -> Tuple[int, bytes]:
        if load_mem is not True:
            if resource_path is not None:
                address = self.allocate_memory(size=len(resource_path) + 1)
                self.load_memory(address=address, size=len(resource_path), write_content=resource_path)
        if load_mem is True:
            self.logger.info("Allocating memory from test case")
            address = resource_path
            self.logger.info(f"Allocated memory address is {address}")
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        line = (
            f'http_client.put {f" -i {ip_addr}"}{f" -p {server_port}" if server_port else ""}{f" -h {host_name}" if host_name else ""}'
            f'{f" -r {address}" if resource_path is not None else ""}{f" -b {put_data_length}" if put_data_length is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        data = self.get_command_data(data)
        if resource_path is not None:
            self.memory_free(address)
        return status, data

    def http_client_deinit(self,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout=30,
                           ):
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=f'http_client.deinit',
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=f'http_client.deinit', timeout=timeout)

        self.verify_status(status, expected_status)
        return status

    def http_client_download(
            self,
            socket_id: int = 0,
            file_name: str = None,
            ip_address: str = None,
            mode: int = 0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=500,
            async_timeout=500
            ):
        line = f'bsd_socket.http_download {socket_id} {file_name} {ip_address} {mode}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_timeout=async_timeout,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        result = self.get_command_data(data)
        return result

    def iperf(self, family=Si91xBSDSocketParams.AF_INET, transfer_type=Si91xBSDSocketParams.SOCK_STREAM,
              protocol=Si91xBSDSocketParams.IPPROTO_TCP, local_port='5001', local_ip=None, remote_ip='',
              remote_port=5001, size=1000, ttl=30, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40,
              throughput_type: int = 1, qos: int = 0, async_socket=0, ip_version=Si91xIpVersion.SL_IPV4_VERSION,
              host_tcp_ip_stack_enable=0):
        # Ensure async wait covers full DUT traffic duration + completion margin.
        if timeout <= ttl:
            self.logger.info(f"iperf: adjusting async timeout {timeout}s -> {ttl + 10}s (timeout <= ttl)")
            timeout = ttl + 10
        assert timeout > ttl, "iperf timeout must be greater than TTL"
        if host_tcp_ip_stack_enable == 0:
            if not local_ip:
                local_ip = self.get_ip_address()
            if throughput_type == 3 and async_socket == 0:
                self.set_remote_terminate_callback()
            self.logger.info(
                f"Sending iperf command with parameters family->{family}, transfer_type->{transfer_type}, protocol->{protocol}, local_port->{local_port}, local_ip->{local_ip}, remote_ip->{remote_ip}, remote_port->{remote_port}, size->{size}, ttl->{ttl}, throughput_type->{throughput_type}, qos->{qos}, async_socket->{async_socket}, ip_version->{ip_version}")
            line = f"iperf {family} {transfer_type} {protocol} {local_port} {local_ip} {remote_ip} {remote_port} {size} {ttl} {throughput_type} {qos} {async_socket} {ip_version}"
        else:
            if not local_ip:
                local_ip = self.get_ip_address()
            self.logger.info(
                f"Sending iperf command with parameters family->{family}, transfer_type->{transfer_type}, protocol->{protocol}, local_port->{local_port}, local_ip->{local_ip}, remote_ip->{remote_ip}, remote_port->{remote_port}, size->{size}, ttl->{ttl}, throughput_type->{throughput_type}")
            line = f"lwip.iperf {family} {transfer_type} {protocol} {local_port} {local_ip} {remote_ip} {remote_port} {size} {ttl} {throughput_type}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        expected_status = [SLStatus.SL_STATUS_OK, SLStatus.SL_STATUS_SI91X_SOCKET_TX_OR_RX_FAIL,
                           SLStatus.SL_STATUS_SI91X_TCP_SERVER_SOCKET_CLOSE_FAIL]
        self.verify_status(status, expected_status)
        self.logger.info(f"data is **********{data.decode()}***********")
        return status, data.decode()

#######################################################################################################################################
    def dual_stack_set_socket_config(self,
                                     total_sockets=1,
                                     total_tcp_sockets=1,
                                     total_udp_sockets=0,
                                     tcp_tx_only_sockets=0,
                                     tcp_rx_only_sockets=1,
                                     udp_tx_only_sockets=0,
                                     udp_rx_only_sockets=0,
                                     tcp_rx_high_performance_sockets=1,
                                     tcp_rx_window_size_cap=44,
                                     tcp_rx_window_div_factor=44,
                                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                     timeout: int = 10
                                     ):
        """Configure offload socket pool via dual_stack.set_socket_config."""
        self.logger.info(
            f"Sending dual_stack.set_socket_config with parameters total_sockets->{total_sockets}, "
            f"total_tcp_sockets->{total_tcp_sockets}, total_udp_sockets->{total_udp_sockets}, "
            f"tcp_tx_only_sockets->{tcp_tx_only_sockets}, tcp_rx_only_sockets->{tcp_rx_only_sockets}, "
            f"udp_tx_only_sockets->{udp_tx_only_sockets}, udp_rx_only_sockets->{udp_rx_only_sockets}, "
            f"tcp_rx_high_performance_sockets->{tcp_rx_high_performance_sockets}, "
            f"tcp_rx_window_size_cap->{tcp_rx_window_size_cap}, "
            f"tcp_rx_window_div_factor->{tcp_rx_window_div_factor}"
        )
        line = (
            f"dual_stack.set_socket_config {total_sockets} {total_tcp_sockets} {total_udp_sockets} "
            f"{tcp_tx_only_sockets} {tcp_rx_only_sockets} {udp_tx_only_sockets} {udp_rx_only_sockets} "
            f"{tcp_rx_high_performance_sockets} {tcp_rx_window_size_cap} {tcp_rx_window_div_factor}"
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    # Run iperf test using dual stack-offload
    def dual_stack_offload_iperf_command_handler(self,
                                 family=Si91xBSDSocketParams.AF_INET,
                                 transfer_type=Si91xBSDSocketParams.SOCK_STREAM,
                                 protocol=Si91xBSDSocketParams.IPPROTO_TCP,
                                 port: int = 5001, 
                                 remote_ip: str ='',
                                 size: int = 1000,
                                 ttl: int = 30,
                                 throughput_type: int = 1,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout: int = 40
                                ):
        """ Run iperf test using dual stack offload stack """

        # Ensure timeout is greater than TTL
        if timeout <= ttl:
            self.logger.info(
                f"dual_stack.offload_iperf: adjusting async timeout {timeout}s -> {ttl + 10}s (timeout <= ttl)"
            )
            timeout = ttl + 10
        assert timeout > ttl, "iperf timeout must be greater than TTL"
        
        # Build command line for dual stack offload iperf
        line = f"dual_stack.offload_iperf {family} {transfer_type} {protocol} {port} {remote_ip} {size} {ttl} {throughput_type}"
        self.logger.info(f"Sending iperf command with parameters family->{family}, transfer_type->{transfer_type}, protocol->{protocol}, port->{port}, remote_ip->{remote_ip}, size->{size}, ttl->{ttl}, throughput_type->{throughput_type}")
        
        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Accept multiple possible status codes
        expected_status = [SLStatus.SL_STATUS_OK, SLStatus.SL_STATUS_SI91X_SOCKET_TX_OR_RX_FAIL, SLStatus.SL_STATUS_SI91X_TCP_SERVER_SOCKET_CLOSE_FAIL]
        self.verify_status(status, expected_status)
        
        # Log the iperf result data
        self.logger.info(f"data is **********{data.decode()}***********")
        return status, data.decode()
    
#######################################################################################################################################
    # Run iperf test using dual stack-LWIP
    def dual_stack_lwip_iperf_command_handler(self,
                                 family=Si91xBSDSocketParams.AF_INET,
                                 transfer_type=Si91xBSDSocketParams.SOCK_STREAM,
                                 protocol=Si91xBSDSocketParams.IPPROTO_TCP,
                                 port: int = 5001, 
                                 remote_ip: str ='',
                                 size: int = 1000,
                                 ttl: int = 30,
                                 throughput_type: int = 1,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout: int = 40
                                ):
        """ Run iperf test using dual stack lwip """

        # Ensure timeout is greater than TTL
        assert timeout > ttl, "iperf timeout must be greater than TTL"

        # Build command line for dual stack lwip iperf
        line = f"dual_stack.lwip_iperf {family} {transfer_type} {protocol} {port} {remote_ip} {size} {ttl} {throughput_type}"
        self.logger.info(f"Sending iperf command with parameters family->{family}, transfer_type->{transfer_type}, protocol->{protocol}, port->{port}, remote_ip->{remote_ip}, size->{size}, ttl->{ttl}, throughput_type->{throughput_type}")
        
        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Accept multiple possible status codes
        expected_status = [SLStatus.SL_STATUS_OK, SLStatus.SL_STATUS_SI91X_SOCKET_TX_OR_RX_FAIL, SLStatus.SL_STATUS_SI91X_TCP_SERVER_SOCKET_CLOSE_FAIL]
        self.verify_status(status, expected_status)
        
        # Log the iperf result data
        self.logger.info(f"data is **********{data.decode()}***********")
        return status, data.decode()

    _MEM_ALLOC_ADDRESS_RE = re.compile(rb"0x[0-9A-Fa-f]+", re.ASCII)
    def allocate_memory(self, size=1024,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout: int = 10,
                        ):
        status, data = self.issue_command(f'mem.alloc {size}', timeout)
        self.verify_status(status, expected_status)
        # Parse address robustly: device may echo command and async frames can interleave,
        # so use the token that looks like a hex address (e.g. 0x2A638) instead of fixed positions.
        first_segment = data.split(b"\r\n\n")[0]
        match = self._MEM_ALLOC_ADDRESS_RE.search(first_segment)
        if match:
            address = match.group(0).decode()
        else:
            # Fallback: second line before first \r\n\n (legacy behavior)
            parts = first_segment.split(b"\r\n")
            if len(parts) >= 2:
                address = parts[1].decode()
            else:
                address = None
        if not address or not re.match(r"^0x[0-9A-Fa-f]+$", address):
            self.logger.warning(
                "allocate_memory: parsed invalid address from response (possible async interleave). "
                "data segment: %r", first_segment[:200] if first_segment else None
            )
            raise CLITransportException(
                f"mem.alloc returned no valid hex address; got {address!r}. "
                "Response may have been interleaved with async MQTT frames."
            )
        return address

    def write_data(self,
                   write_data="",
                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                   timeout: int = 10,
                   ):
        status, data = self.issue_command(write_data, timeout)
        self.verify_status(status, expected_status)

    def load_memory(self, address,
                    size=1024,
                    write_content="",
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 10,
                    ):
        if not re.match(r"^0x[0-9A-Fa-f]+$", str(address).strip()):
            raise CLITransportException(
                f"load_memory requires a hex address (e.g. 0x2A638), got {address!r}. "
                "This may indicate allocate_memory response was corrupted by async frames."
            )
        status, data = self.issue_command(f'mem.write {address} {size}', timeout, ignore_response=1)
        # self.verify_status(status, expected_status)
        self.write_data(write_data=write_content)

    def memory_free(self, address,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 10,
                    ):
        status, data = self.issue_command(f'mem.free {address}', timeout)
        self.verify_status(status, expected_status)

    def generate_wrap_key(self,
                          address=None,
                          key_type: Si91xCryptoKeyType = None,
                          wrap_iv_mode: Si91xCryptoWrapMode = None,
                          iv=None,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 20,
                          ):
        command = (
            f'wrap {address}{f" -k {key_type}" if key_type is not None else ""}{f" -m {wrap_iv_mode}" if wrap_iv_mode is not None else ""}{f" -i {iv}" if iv is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=command, timeout=timeout, async_timeout=20,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(command, timeout)
        self.verify_status(status, expected_status)
        return data

    def load_private_wrap_key(self,
                              address=None,
                              cert_type: Si91xCertificateType = None,
                              cert_identifier: Si91xCertIdentifier = None,
                              cert_index=0,
                              iv=0,
                              cert_length=0,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                              timeout: int = 20,
                              ):
        command = (
            f'wifi.load_cert {address}{f" -c {cert_type}" if cert_type else ""}{f" -i {cert_identifier}" if cert_identifier else ""}{f" -n {cert_index}" if cert_index else ""}{f" -v {iv}" if iv else ""}{f" -l {cert_length}" if cert_length else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=command, timeout=timeout, async_timeout=20,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(command, timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def paho_mqtt_set_advanced_configuration_command_handler(self,                                                    
                                                            last_will_topic: str = None,
                                                            last_will_message: str = None,
                                                            last_will_qos: int = None,
                                                            last_will_retain: int = None,
                                                            is_will_enabled: int = None,
                                                            clean_session: int = None,
                                                            ca_cert: str = None,
                                                            ca_cert_length: int = None,
                                                            credential_id: int = None,
                                                            credential_type: int = None,
                                                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                            timeout: int = 20
                                                        ):
        """Configure last will, clean session, and TLS credentials for the Paho MQTT client"""
        
        # Build command line for advanced MQTT configuration
        line = f"paho_mqtt.set_advanced_configuration "

        # Append parameters to the command line if they are provided
        if last_will_topic:
            line += f" -a {last_will_topic}"
        if last_will_message:
            line += f" -b {last_will_message}"
        if last_will_qos is not None:
            line += f" -c {last_will_qos}"
        if last_will_retain is not None:
            line += f" -d {last_will_retain}"
        if is_will_enabled is not None:
            line += f" -e {is_will_enabled}"
        if clean_session is not None:
            line += f" -f {clean_session}"
        if ca_cert:
            line += f" -g {ca_cert}"
        if ca_cert_length is not None:
            line += f" -h {ca_cert_length}"
        if credential_id is not None:
            line += f" -i {credential_id}"
        if credential_type is not None:
            line += f" -j {credential_type}"
        
        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def paho_mqtt_client_connect_to_server_command_handler(self,
                                                        broker_address: str = None,
                                                        enable_ssl: int = None,
                                                        username: str = None,
                                                        password: str = None,
                                                        timeout_ms: int = None,
                                                        broker_port: int = None,
                                                        dut_client_port: int = None,
                                                        ip_type: int = None,
                                                        keep_alive_time_ms: int = None,
                                                        mqtt_ver: int = None,
                                                        client_id: str = None,
                                                        transport_type: int = None,
                                                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                        timeout: int = 20
                                                    ):
        """Establish TCP or WebSocket connection and send MQTT CONNECT to the broker (transport_type: 0=TCP, 1=WS)"""
        
        # Build command line for MQTT connect with all parameters
        line = f"paho_mqtt.connect "

        # Append parameters to the command line if they are provided
        if broker_address is not None:
            line += f" {broker_address}"
        if enable_ssl is not None:
            line += f" -a {enable_ssl}"
        if username is not None:
            line += f" -b {username}"
        if password is not None:
            line += f" -c {password}"
        if timeout_ms is not None:
            line += f" -d {timeout_ms}"
        if broker_port is not None:
            line += f" -e {broker_port}"
        if dut_client_port is not None:
            line += f" -f {dut_client_port}"
        if ip_type is not None:
            line += f" -g {ip_type}"
        if keep_alive_time_ms is not None:
            line += f" -h {keep_alive_time_ms}"
        if mqtt_ver is not None:
            line += f" -i {mqtt_ver}"
        if client_id is not None:
            line += f" -j {client_id}"
        if transport_type is not None:
            line += f" -k {transport_type}"

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def paho_mqtt_client_subscribe_command_handler(self,
                                                   topic: str = None,
                                                   qos_level: int = None,
                                                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                   timeout: int = 20
                                                ):
        """Subscribe to an MQTT topic with a specified QoS level and register a message callback"""
        
        # Build command line for MQTT subscribe with topic and QoS
        line = f"paho_mqtt.subscribe "

        # Append parameters to the command line if they are provided
        if topic is not None:
            line += f" -a {topic}"
        if qos_level is not None:
            line += f" -b {qos_level}"

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################

    def paho_mqtt_client_yield_command_handler(self,
                                               timeout_ms: int = None,
                                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                               timeout: int = 30,
                                               async_timeout: int = None
                                               ):
        """Yield control to the MQTT client to process incoming messages for a given timeout"""

        # Build command line for MQTT yield with timeout
        line = f"paho_mqtt.yield "

        # Append timeout parameter to the command line if it is provided
        if timeout_ms is not None:
            line += f" -a {timeout_ms}"

        # Yield can block up to timeout_ms; async_timeout must be larger or harness
        if async_timeout is None:
            if timeout_ms is not None:
                async_timeout = max(20, int(timeout_ms / 1000) + 15)
            else:
                async_timeout = 20

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line=line, timeout=timeout, async_timeout=async_timeout,
                protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def paho_mqtt_client_publish_command_handler(self,
                                                 qos_level: int = None,
                                                 is_msg_retained: int = None,
                                                 is_msg_dup: int = None,
                                                 topic: str = None,
                                                 msg_payload: str = None,
                                                 msg_payload_len: int = None,
                                                 use_higher_data_len: int = None,
                                                 data_buffer: str = None,
                                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                 timeout: int = 20
                                                ):
        """Publish a message to an MQTT topic with configurable QoS, retain, and duplicate flags"""
        
        # Determine the message payload length if not provided
        if msg_payload_len is None and msg_payload is not None:
            msg_payload_len = len(msg_payload)

        # Build command line for MQTT publish with all parameters
        line = f"paho_mqtt.publish "

        # Append parameters to the command line if they are provided
        if qos_level is not None:
            line += f" -a {qos_level}"
        if is_msg_retained is not None:
            line += f" -b {is_msg_retained}"
        if is_msg_dup is not None:
            line += f" -c {is_msg_dup}"
        if topic is not None:
            line += f" -d {topic}"
        if msg_payload is not None:
            line += f" -e {msg_payload}"
        if msg_payload_len is not None:
            line += f" -f {msg_payload_len}"
        if use_higher_data_len is not None:
            line += f" -g {use_higher_data_len}"
        if data_buffer is not None:
            line += f" -h {data_buffer}"

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def paho_mqtt_client_unsubscribe_command_handler(self,
                                                     topic: str = None,
                                                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                     timeout: int = 20
                                                    ):
        """Unsubscribe from an MQTT topic to stop receiving messages on it"""
        
        # Build command line for MQTT unsubscribe with topic
        line = f"paho_mqtt.unsubscribe "

        # Append topic parameter to the command line if it is provided
        if topic is not None:
            line += f" -a {topic}"

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def paho_mqtt_client_disconnect_command_handler(self,
                                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                    timeout: int = 20
                                                    ):
        """Gracefully disconnect from the MQTT broker, free TLS credentials, and close the network connection"""
        
        # Build command line for MQTT disconnect
        line = "paho_mqtt.disconnect "

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)
    
#######################################################################################################################################
    def aws_lwip_mqtt_init_command_handler(self,
                                           auto_reconnect: int = None,
                                           host_URL: str = None,
                                           port: int = None,
                                           cacert: str = None,
                                           cacert_length: int = None,
                                           client_cert: str = None,
                                           client_cert_length: int = None,
                                           client_key: str = None,
                                           client_key_length: int = None,
                                           cmd_timeout_ms: int = None,
                                           handshake_timeout_ms: int = None,
                                           host_name_verify_enable: int = None,
                                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                           timeout: int = 20
                                        ):
        """Initialize AWS IoT MQTT client with TLS credentials and connection parameters"""
        
        # Build command line for advanced MQTT configuration
        line = (f"aws_lwip.mqtt_init "
                f"{f' -a {auto_reconnect}' if auto_reconnect is not None else ''}"
                f"{f' -b {host_URL}' if host_URL else ''}"
                f"{f' -c {port}' if port is not None else ''}"
                f"{f' -d {cacert}' if cacert else ''}"
                f"{f' -e {cacert_length}' if cacert_length is not None else ''}"
                f"{f' -f {client_cert}' if client_cert else ''}"
                f"{f' -g {client_cert_length}' if client_cert_length is not None else ''}"
                f"{f' -h {client_key}' if client_key else ''}"
                f"{f' -i {client_key_length}' if client_key_length is not None else ''}"
                f"{f' -j {cmd_timeout_ms}' if cmd_timeout_ms is not None else ''}"
                f"{f' -k {handshake_timeout_ms}' if handshake_timeout_ms is not None else ''}"
                f"{f' -l {host_name_verify_enable}' if host_name_verify_enable is not None else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def aws_lwip_mqtt_connect_command_handler(self,
                                              keepalive_interval: int = None,
                                              is_clean_session: int = None,
                                              mqtt_ver: int = None,
                                              client_id: str = None,
                                              client_id_len: int = None,
                                              is_will_present: int = None,
                                              username: str = None,
                                              username_len: int = None,
                                              password: str = None,
                                              password_len: int = None,
                                              will_topic: str = None,
                                              will_topic_len: int = None,
                                              will_message: str = None,
                                              will_message_len: int = None,
                                              will_qos: int = None,
                                              is_will_retain: int = None,
                                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                              timeout: int = 20
                                            ):
        """Connect to AWS IoT MQTT broker with configurable keepalive, session, and last will options"""

        # Build command for MQTT connect with all parameters
        line = (f"aws_lwip.mqtt_connect "
                f"{f' -a {keepalive_interval}' if keepalive_interval is not None else ''}"
                f"{f' -b {is_clean_session}' if is_clean_session is not None else ''}"
                f"{f' -c {mqtt_ver}' if mqtt_ver is not None else ''}"
                f"{f' -d {client_id}' if client_id is not None else ''}"
                f"{f' -e {client_id_len}' if client_id_len is not None else ''}"
                f"{f' -f {is_will_present}' if is_will_present is not None else ''}"
                f"{f' -g {username}' if username else ''}"
                f"{f' -h {username_len}' if username_len is not None else ''}"
                f"{f' -i {password}' if password else ''}"
                f"{f' -j {password_len}' if password_len is not None else ''}"
                f"{f' -k {will_topic}' if will_topic else ''}"
                f"{f' -l {will_topic_len}' if will_topic_len is not None else ''}"
                f"{f' -m {will_message}' if will_message else ''}"
                f"{f' -n {will_message_len}' if will_message_len is not None else ''}"
                f"{f' -o {will_qos}' if will_qos is not None else ''}"
                f"{f' -p {is_will_retain}' if is_will_retain is not None else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def aws_lwip_mqtt_subscribe_command_handler(self,
                                                topic: str = None,
                                                topic_len: int = None,
                                                qos_level: int = None,
                                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                timeout: int = 20
                                            ):
        """Subscribe to an MQTT topic with specified QoS level"""

        # Build command line for MQTT subscribe with topic and QoS parameters
        line = (f"aws_lwip.mqtt_subscribe "
                f"{f' -a {topic}' if topic else ''}"
                f"{f' -b {topic_len}' if topic_len is not None else ''}"
                f"{f' -c {qos_level}' if qos_level is not None else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def aws_lwip_mqtt_yield_command_handler(self,
                                            timeout_ms: int = None,
                                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                            timeout: int = 20
                                        ):
        """Receive incoming MQTT messages"""

        # Build command line for MQTT yield with specified timeout
        line = f"aws_lwip.yield {f' -a {timeout_ms}' if timeout_ms is not None else ''}"
        
        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def aws_lwip_mqtt_publish_command_handler(self,
                                              qos_level: int = None,
                                              is_msg_retained: int = None,
                                              topic: str = None,
                                              topic_len: int = None,
                                              msg_payload: str = None,
                                              msg_payload_len: int = None,
                                              use_higher_data_len: int = None,
                                              data_buffer: str = None,
                                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                              timeout: int = 20
                                            ):
        """Publish a message to an MQTT topic with configurable QoS and retain flag"""

        # Build command line for MQTT publish with all parameters
        line = (f"aws_lwip.mqtt_publish "
                f"{f' -a {qos_level}' if qos_level is not None else ''}"
                f"{f' -b {is_msg_retained}' if is_msg_retained is not None else ''}"
                f"{f' -c {topic}' if topic else ''}"
                f"{f' -d {topic_len}' if topic_len is not None else ''}"
                f"{f' -e {msg_payload}' if msg_payload else ''}"
                f"{f' -f {msg_payload_len}' if msg_payload_len is not None else ''}"
                f"{f' -g {use_higher_data_len}' if use_higher_data_len is not None else ''}"
                f"{f' -h {data_buffer}' if data_buffer else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def aws_lwip_mqtt_unsubscribe_command_handler(self,
                                                  topic: str = None,
                                                  topic_len: int = None,
                                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                  timeout: int = 20
                                                ):
        """Unsubscribe from a previously subscribed MQTT topic"""

        # Build command line for MQTT unsubscribe with topic and length parameters
        line = (f"aws_lwip.mqtt_unsubscribe "
                f"{f' -a {topic}' if topic else ''}"
                f"{f' -b {topic_len}' if topic_len is not None else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def aws_lwip_mqtt_disconnect_command_handler(self,
                                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                 timeout: int = 20
                                                ):
        """Disconnect from the AWS IoT MQTT broker"""

        # Build command line (no arguments needed for disconnect)
        line = "aws_lwip.mqtt_disconnect"

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)
    
#######################################################################################################################################
    # Configure LWIP MQTT advanced settings
    def lwip_mqtt_configure(self,
                            will_topic: str = None,
                            will_message: str = None,
                            will_qos: int = None,
                            retain_will: int = None,
                            enable_will: int = None,
                            is_clean_session: int = None,
                            ca_cert: str = None,
                            ca_cert_size: int = None,
                            client_cert: str = None,
                            client_cert_size: int = None,
                            client_key: str = None,
                            client_key_size: int = None,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 20,
                        ):
        """Configure last will, clean session, and TLS credentials for the LWIP MQTT client"""

        # Build command line for advanced MQTT configuration with conditional parameters
        line = (f"lwip_mqtt.set_advanced_configuration "
                f"{f' -a {will_topic}' if will_topic is not None else ''}"
                f"{f' -b {will_message}' if will_message else ''}"
                f"{f' -c {will_qos}' if will_qos is not None else ''}"
                f"{f' -d {retain_will}' if retain_will is not None else ''}"
                f"{f' -e {enable_will}' if enable_will is not None else ''}"
                f"{f' -f {is_clean_session}' if is_clean_session is not None else ''}"
                f"{f' -g {ca_cert}' if ca_cert else ''}"
                f"{f' -h {ca_cert_size}' if ca_cert_size is not None else ''}"
                f"{f' -i {client_cert}' if client_cert else ''}"
                f"{f' -j {client_cert_size}' if client_cert_size is not None else ''}"
                f"{f' -k {client_key}' if client_key else ''}"
                f"{f' -l {client_key_size}' if client_key_size is not None else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def lwip_mqtt_connect(self,
                          server: MqttServer,
                          mqtt_server: str = None,
                          enable_ssl: int = None,
                          username: str = None,
                          password: str = None,
                          connection_timeout_ms: int = None,
                          broker_port: int = None,
                          dut_port: int = None,
                          ip_type: int = None,
                          keep_alive_interval_ms: int = None,
                          mqtt_version: int = None,
                          client_id: str = None,
                          tls_hostname: str = None,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 100,
                          async_timeout: int = 50,
                        ):
        """Establish TCP connection and send MQTT CONNECT to the broker with configurable credentials and keepalive"""

        # Build command line for MQTT connect with all parameters
        line = (f"lwip_mqtt.connect "
                f"{f' {mqtt_server}' if mqtt_server else server.hostname_or_ip_address}"
                f"{f' -a {enable_ssl}' if enable_ssl is not None else ''}"
                f"{f' -b {username}' if username else ''}"
                f"{f' -c {password}' if password else ''}"
                f"{f' -d {connection_timeout_ms}' if connection_timeout_ms is not None else ''}"
                f"{f' -e {broker_port}' if broker_port is not None else ''}"
                f"{f' -f {dut_port}' if dut_port is not None else ''}"
                f"{f' -g {ip_type}' if ip_type is not None else ''}"
                f"{f' -h {keep_alive_interval_ms}' if keep_alive_interval_ms is not None else ''}"
                f"{f' -i {mqtt_version}' if mqtt_version is not None else ''}"
                f"{f' -j {client_id}' if client_id else ''}"
                f"{f' -k {tls_hostname}' if tls_hostname else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.lwip_mqtt_state_connected = True

#######################################################################################################################################
    def lwip_mqtt_subscribe(self,
                            topic: str = None,
                            qos: int = None,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 20,
                        ):
        """Subscribe to an MQTT topic with configurable QoS"""

        # Build command line for MQTT subscribe
        line = (f"lwip_mqtt.subscribe "
                f"{f' -a {topic}' if topic else ''}"
                f"{f' -b {qos}' if qos is not None else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def lwip_mqtt_publish(self,
                          qos: int = None,
                          retain: int = None,
                          is_duplicate_message: int = None,
                          topic: str = None,
                          message: str = None,
                          higher_data_len: int = None,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 20,
                          async_timeout: int = 30,
                        ):
        """Publish a message to an MQTT topic with configurable QoS, retain, and duplicate flags, and support for higher data length"""

        # Determine the message payload length if not provided
        higher_data_len_flag =  higher_data_len is not None and higher_data_len > 0

        if higher_data_len_flag:
            address = self.allocate_memory(size=len(message) + 1)
            self.load_memory(address=address, size=len(message), write_content=message, timeout=1)
        
        # Build command line for MQTT publish
        line = (f"lwip_mqtt.publish "
                f"{f' -a {qos}' if qos is not None else ''}"
                f"{f' -b {retain}' if retain is not None else ''}"
                f"{f' -c {is_duplicate_message}' if is_duplicate_message is not None else ''}"
                f"{f' -d {topic}' if topic else ''}"
                f"{f' -e {message}' if not higher_data_len_flag else ''}"
                f"{f' -f {len(message)}' if message else ''}"
                f"{f' -g {higher_data_len}' if higher_data_len_flag else ''}"
                f"{f' -h {address}' if higher_data_len_flag else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Free allocated memory if higher data length was used
        if higher_data_len_flag:
            self.memory_free(address)
        self.verify_status(status, expected_status)

        # Verify the command status
        return status, data.decode()

#######################################################################################################################################
    def lwip_mqtt_yield(self,
                        yield_timeout_ms: int = None,
                        timeout: int = 30,
                        async_timeout: int = 40,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        ):
        """Yield control to the MQTT client to process incoming messages for a given timeout"""

        # Build command line for MQTT publish
        line = f"lwip_mqtt.yield {f'-a {yield_timeout_ms}' if yield_timeout_ms is not None else ''}"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def lwip_mqtt_unsubscribe(self,
                              topic: str = None,
                              timeout: int = 20,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            ):
        """Unsubscribe from an MQTT topic to stop receiving messages on it"""

        # Build command line for MQTT unsubscribe
        line = f"lwip_mqtt.unsubscribe {f'-a {topic}' if topic else ''}"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def lwip_mqtt_disconnect(self,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout: int = 20,
                            ):
        """Gracefully disconnect from the MQTT broker, free TLS credentials, and close the network connection"""

        # Build command line for MQTT disconnect
        line = f"lwip_mqtt.disconnect"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        
        if status == SLStatus.SL_STATUS_OK:
            self.lwip_mqtt_state_connected = False

    @defaults("wifi")
    def set_ssl_certificate(self,
                            cert_file: str = None,
                            cert_type: Si91xCertificateType = None,
                            cert_identifier: Si91xCertIdentifier = None,
                            cert_index=0,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 20,
                            ):
        with open(cert_file) as f:
            cert_contents = f.read()
        size = len(cert_contents)
        self.logger.info(f"\nLoading  certificate '{cert_type}' at index {cert_index}")
        buffer_size = (512 * (int(size / 512))) + 512  # buffer_size should be more than size
        address = self.allocate_memory(size=buffer_size)
        self.load_memory(address, size=size, write_content=cert_contents)
        command = (
            f'wifi.load_cert {address}{f" -c {cert_type}" if cert_type else ""}{f" -i {cert_identifier}" if cert_identifier else ""}{f" -n {cert_index}" if cert_index else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=command, timeout=timeout, async_timeout=20,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(command, timeout)
        self.verify_status(status, expected_status)
        self.memory_free(address)

    def clear_certificate(self,
                          cert_index=0,
                          cert_type: Si91xCertificateType = None,
                          cert_identifier: Si91xCertIdentifier = None,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 10,
                          ):
        command = f'wifi.clear_ca_store{f" -c {cert_type}" if cert_type else ""}{f" -i {cert_identifier}" if cert_identifier else ""}{f" -n {cert_index}" if cert_index else ""}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=command, timeout=timeout, async_timeout=20,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(command, timeout)
        self.verify_status(status, expected_status)
        self.certs_loaded = dict.fromkeys(self.certs_loaded.keys(), None)

    @defaults("bluetooth")
    def __get_bt_address(self, timeout=2, expected_status: SLStatus = SLStatus.SL_STATUS_OK) -> str:
        line = "bt_get_local_address"
        if self.test_agent_thread_enabled:
            status, result = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
            )
        else:
            status, result = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)
        self.logger.info(f" BT mac address ======= {result}")
        address_str = result.strip().decode()
        return mac_address_to_string(address_str)

    @defaults("bluetooth")
    def bt_get_local_address(self, timeout=2):
        return self.__get_bt_address(timeout)

    @defaults("bluetooth")
    def ble_set_random_addr(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout=10):
        line = f"ble_set_random_addr"

        self.logger.info(f"**** initiating  ble_set_random_addr Cli command  *****")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_encrypt(self, key: str, data: str, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout=10):
        """ Arguments
                            key :  16 Bytes key for Encryption of data.
                        	data: 16 Bytes of Data request to encrypt
                        	resp: Encrypted data
                """
        self.logger.info(
            f"**** initiating  ble_encrypt CLI command with Arguments: key:{key}, data:{data}  *****")
        line = f"ble_encrypt {key} {data}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)
        values = re.findall(r"- resp: - (\w+)", data.decode("utf-8"))
        return values

    @defaults("bluetooth")
    def ble_resolvlist(self, process_type: int, addr_type: int, remote_dev_addr: str, peer_irk: str, local_irk: str,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout=10):
        """ Arguments
                process_type         - Indicates which type of process this is, as follows: 1 - add a device to the resolve list 2 - remove a device from the resolve list 3 - clear the entire resolve list
            	remote_dev_addr_type - typr of the remote device address
                remote_dev_address   - remote device address 0 - Public identity address 1 - Random (static) identity address
                peer_irk        	 - 16-byte IRK of the peer device
            	local_irk	         - 16-byte IRK of the local device
                """
        self.logger.info(
            f"**** initiating  ble_resolvlist Cli command with Arguments: process_type:{process_type}, addr_type:{addr_type}, remote_dev_addr:{remote_dev_addr}, peer_irk:{peer_irk}, local_irk:{local_irk}  *****")
        line = f"ble_resolvlist {process_type} {addr_type} {mac_address_to_string(remote_dev_addr, ':')} {peer_irk} {local_irk}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_resolving_list_size(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout=10):
        """ Arguments
            resp - output parameter which consists of supported resolving the list size.
        """
        self.logger.info(f"**** initiating  ble_get_resolving_list_size Cli command *****")
        line = f"ble_get_resolving_list_size"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_cap_data(self,
                         remote_addr_type=None,
                         smp_io_cap=None,
                         smp_auth_req_bonding=None,
                         smp_auth_req_mitm=None,
                         smp_auth_req_sc=None,
                         smp_max_enc_key_size=None,
                         smp_local_oob_data_flag_not_present=None,
                         smp_enc_key=None,
                         smp_id_key=None,
                         smp_sign_key=None,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=10):
        '''

        :param remote_addr_type:
            -0 Public Identity Address
            -1 Random (static) Identity Address
        :param smp_io_cap:
            -0 Display Only
            -1 Display Yes/No
            -2 Keyboard Only
            -3 No Input No Output
            -4 Keyboard Display
        :param smp_auth_req_bonding:
            -0 No bonding
            -1 Bonding
        :param smp_auth_req_mitm:
            -0 No MITM
            -1 MITM
        :param smp_auth_req_sc:
            -0 No Secure Connections
            -1 Secure Connections
        :param smp_max_enc_key_size:
            -16 16 bytes
        :param smp_local_oob_data_flag_not_present:
            -0 OOB data not present
            -1 OOB data present
        :param smp_enc_key:
            -0 No encryption key
            -1 Encryption key
        :param smp_id_key:
            -0 No identity key
            -1 Identity key
        :param smp_sign_key:
            -0 No signing key
            -1 Signing key

        '''
        self.logger.info("**** ble set  pairing data Cli command *****")
        line = f"ble_set_pairing_cap_data {remote_addr_type} {smp_io_cap} {smp_auth_req_bonding} {smp_auth_req_mitm} {smp_auth_req_sc} {smp_max_enc_key_size} {smp_local_oob_data_flag_not_present} {smp_enc_key} {smp_id_key} {smp_sign_key}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_modify_passkey_event(self,
                                 passkey_state=0,
                                 delay=0,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout=10):
        '''

        :param passkey_state:
            -0 Enter the correct passkey
            -1 Enter the wrong passkey
            -2 Do not enter the passkey
            -3 Enter the passkey with a delay
        :param delay: delay in milli seconds

        '''

        self.logger.info("**** ble modify passkey event Cli command *****")
        line = f"ble_modify_passkey_event {passkey_state} {delay}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_addr_resolution_enable(self, enable: int, tout: int,
                                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                       timeout=10):
        """ Arguments
                           enable - value to enable/disable address resolution 1 - enables address resolution 0 - disables address resolution
                        	tout  - the period for changing address of our local device in seconds Value ranges from 0x0001 to 0xA1B8 (1 s to approximately 11.5 hours
                """
        self.logger.info(
            f"**** initiating  ble_set_addr_resolution_enable Cli command with Arguments enable:{enable}, tout:{tout}  *****")
        line = f"ble_set_addr_resolution_enable {enable} {tout}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_privacy_mode(self, addr_type: int, remote_dev_addr: str, privacy_mode: int,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout=10):
        """ Arguments
                 remote_dev_addr_type - type of the remote device address \n
 *                                    0 - Public Identity Address \n
 *                                    1 - Random (static) Identity Address
 * @param[in]  remote_dev_address   - remote device address
 * @param[in]  privacy_mode 	    - type of the privacy mode \n
					0 - Network privacy mode \n
 *                            		1 - Device privacy mode
        """
        self.logger.info(
            f"**** initiating  ble_set_privacy_mode Cli command with Arguments: addr_type:{addr_type}, remote_dev_addr:{remote_dev_addr}, privacy_mode:{privacy_mode} *****")
        line = f"ble_set_privacy_mode {addr_type} {mac_address_to_string(remote_dev_addr, ':')} {privacy_mode}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_inc_services(self, remote_dev_addr: str, start_handle: int, end_handle: int,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout=10):
        """ Arguments
          remote_dev_address   - remote device address
            start_handle       - start handle (index) of the remote device's service records
            end_handle         - end handle (index) of the remote device's service records
        """
        self.logger.info(
            f"**** initiating  ble_get_inc_services Cli command with Arguments: remote_dev_addr:{remote_dev_addr}, start_handle:{start_handle}, end_handle:{end_handle} *****")
        line = f"ble_get_inc_services {mac_address_to_string(remote_dev_addr, ':')} {start_handle} {end_handle}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_set_bd_addr(self, remote_dev_addr: str,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=10):
        """ Arguments
                 remote_dev_addr_type - type of the remote device address \n
        """
        self.logger.info(
            f"**** initiating  ble_set_bd_addr Cli command with Arguments: remote_dev_addr:{remote_dev_addr} *****")
        line = f"ble_set_bd_addr {mac_address_to_string(remote_dev_addr, ':')}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)

    def ble_end_test_mode(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=10,
                          ):
        """ Arguments
              num_of_pkts -Number of RX packets received are displayed when RX test is stopped
        """
        self.logger.info(
            f"**** initiating  ble_end_test_mode Cli command  *****")
        line = f"ble_end_test_mode"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def ble_tx_test_mode(self, tx_channel: int, phy: int, tx_len: int, mode: int,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=10,
                         ):
        """ Arguments
                tx_channel -  RF Channel (0-39). \n
 * @param[in]  phy - 0x00  Reserved for future use \n
 *                   0x01  Transmitter set to use the LE 1M PHY \n
 *                   0x02  Transmitter set to use the LE 2M PHY \n
 *                   0x03  Transmitter set to use the LE Coded PHY with S=8 data coding \n
 *                   0x04  Transmitter set to use the LE Coded PHY with S=2 data coding \n
 *                   (0x05 - 0xFF)  Reserved for future use.
 * @param[in] tx_len - Length in bytes of payload data in each packet ( 1 - 251 bytes).
 * @param[in] mode - 0x00  PRBS9 sequence '11111111100000111101...' \n
 *                   0x01  Repeated '11110000' \n
 *                   0x02  Repeated '10101010' \n
 *                   0x03  PRBS15 \n
 *                   0x04  Repeated '11111111' \n
 *                   0x05  Repeated '00000000' \n
 *		     0x06  Repeated '00001111' \n
 *		     0x07  Repeated '01010101' \n
 *                   0x08 - 0xFF Reserved for future use \n
        """
        self.logger.info(
            f"**** initiating  ble_tx_test_mode Cli command with Arguments tx_channel:{tx_channel}, phy:{phy}, tx_len:{tx_len}, mode:{mode} *****")
        line = f"ble_tx_test_mode {tx_channel} {phy} {tx_len} {mode}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_rx_test_mode(self, rx_channel: int, phy: int, modulation: int,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=10,
                         ):
        """ Arguments
                rx_channel	- Channel in which packet have to be received (0 - 39)
            	phy	        - 0x00 Reserved for future use 0x01 Receiver set to use the LE 1M PHY 0x02 Receiver set to use the LE 2M PHY 0x03 Receiver set to use the LE Coded PHY (0x04 - 0xFF) Reserved for future use.
            	modulation	- 0x00 Assume transmitter will have a standard standard modulation index 0x01 Assume transmitter will have a stable modulation index (0x02 - 0xFF) Reserved for future use
        """
        self.logger.info(
            f"**** initiating  ble_rx_test_mode Cli command with Arguments: rx_channel:{rx_channel}, phy:{phy}, modulation:{modulation}  *****")
        line = f"ble_rx_test_mode {rx_channel} {phy} {modulation}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_read_transmit_power(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10,
                                ):
        """ Arguments
                Min_TX_Power : Units in dBm Ranges from -127 to +20 \n
 *             Max_TX_Power : Units in dBm Ranges from -127 to +20 \n
        """
        self.logger.info(
            f"**** initiating  ble_read_transmit_power Cli command  *****")
        line = f"ble_read_transmit_power"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def ble_app_set_periodic_ae(self, enable: int, handle: int,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10,
                                ):
        """ Arguments
                enable:Enable, BIT map for Enable \n
 *
 *                0      -  Enable Periodic Advertising  \n
 *                1      -  Include the ADI field in AUX_SYNC_IND PDUs \n
                handle:Advertising_Handle - Used to Identify an Advertsing Set \n
        """

        self.logger.info(
            f"**** initiating  ble_app_set_periodic_ae Cli command with Arguments: enable:{enable}, handle:{handle}  *****")
        line = f"ble_app_set_periodic_ae {enable} {handle}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_app_adv_set_clear_or_remove(self, type: int, handle: int,
                                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                        timeout=10,
                                        ):
        """ Arguments
                type   :  Specifies whether to remove or clear the advertising sets.
 *             {1}  - clear
 *             {2}  - remove
                handle : Advertising_Handle - Used to identify an Advertising set. Possible Values : 0x00 to 0xEF
        """
        line = f"ble_app_adv_set_clear_or_remove {type} {handle}"
        self.logger.info(
            f"**** initiating  ble_app_adv_set_clear_or_remove Cli command with Arguments: type:{type}, handle: {handle} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_gatt_write_response(self, remote_dev_addr: str, type: int,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10,
                                ):
        """ Arguments
                remote_dev_addr: mac address of remote device
                type           : response type 0 - write response, 1 - execute write response
        """
        line = f"ble_gatt_write_response {mac_address_to_string(remote_dev_addr, ':')} {type}"
        self.logger.info(
            f"**** initiating  ble_gatt_write_response Cli command with Arguments: remote_dev_addr: {remote_dev_addr}, type:{type} *****"
            )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_gatt_prepare_write_resp(self, remote_dev_addr: str, handle: int, offset: int, length: int, data: str,
                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout=10,
                                    ):
        """ Arguments
                remote_dev_addr: mac address of remote device
                handle         : attribute value handle
                offset         :  attribute value offset
                length         : attribute value length
                data           : attribute value
        """
        line = f"ble_gatt_prepare_write_resp {mac_address_to_string(remote_dev_addr, ':')} {handle} {offset} {length} {data}"
        self.logger.info(
            f"**** initiating  ble_gatt_prepare_write_resp Cli command with Arguments: remote_dev_addr:{remote_dev_addr}, handle:{handle}, offset:{offset}, length:{length}, data:{data} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_att_error_resp(self, remote_dev_addr: str, handle: int, opcode: int, err: int,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout=10,
                           ):
        """ Arguments
                   remote_dev_addr - remote device mac address
                   handle          - attribute handle
                   opcode	       - error response opcode
                   err             - specific error related Gatt
        """
        line = f"ble_att_error_resp {mac_address_to_string(remote_dev_addr, ':')} {handle} {opcode} {err}"
        self.logger.info(
            f"**** initiating  ble_att_error_resp Cli command with arguments: remote_dev_Addr:{remote_dev_addr}, handle: {handle}, opcode: {opcode}, err: {err}  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_indicate_value_sync(self, remote_dev_addr: str, handle: int, data_len: int, data: str,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10,
                                ):
        """ Arguments
                            remote_dev_Addr - ex: "0A:11:AK:15:A8:
                        	handle          - local attribute handle
        	                data_len       - attribute value length
                        	p_data         - attribute value
        """
        line = f"ble_indicate_value_sync {mac_address_to_string(remote_dev_addr, ':')} {handle} {data_len} {data}"
        self.logger.info(
            f"**** initiating  ble_indicate_value_sync Cli command with Arguments: {remote_dev_addr}, handle:{handle}, data_len:{data_len}, data:{data}  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_execute_write(self, remote_dev_addr: str, exe_flag: int,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=10,
                          ):
        """ Arguments
                    remote_dev_Addr = ex: "0A:11:AK:15:A8:00"
                    execute flag to write, possible values mentioned below 0 - BLE_ATT_EXECUTE_WRITE_CANCEL 1 - BLE_ATT_EXECUTE_PENDING_WRITES_IMMEDIATELY
        """
        line = f"ble_execute_write {mac_address_to_string(remote_dev_addr, ':')} {exe_flag}"

        self.logger.info(
            f"**** initiating  ble_execute_write Cli command with Arguments: {remote_dev_addr} & {exe_flag} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_smp_passkey(self, remote_dev_addr: str, smp_passkey: int,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout=10,
                            ):
        """ Arguments
                            remote_dev_Addr - ex: "0A:11:AK:15:A8:
                        	smp_passkey          - ble smp passkey
        """
        line = f"ble_set_passkey {mac_address_to_string(remote_dev_addr, ':')} {smp_passkey}"
        self.logger.info(
            f" === enter passkey from cli command for ble connection: {remote_dev_addr}, passkey:{smp_passkey} ===")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_conn_param_resp(self, remote_dev_addr: str, status: int,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout=10,
                            ):
        """ Arguments
                    remote_dev_Addr = ex: "0A:11:AK:15:A8:00"
                    status          =  accept or reject the connection parameters update request 0 - ACCEPT, 1 - REJECT
        """
        line = f"ble_conn_param_resp {mac_address_to_string(remote_dev_addr, ':')} {status}"

        self.logger.info(
            f"**** initiating  ble_conn_param_resp Cli command with Arguments: remote_dev_addr:{remote_dev_addr} & {status} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_prepare_write(self, remote_dev_addr: str, handle: int, index: int, length: int, data: int,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=10,
                          ):
        """ Arguments
                      dev_addr - remote device address
                       handle 	- attribute handle
                       index 	- attribute value offset
                       length   - attribute value length
                       data 	- attribute value
        """
        line = f"ble_prepare_write {mac_address_to_string(remote_dev_addr, ':')} {handle} {index} {length} {data}"

        self.logger.info(
            f"**** initiating  ble_prepare_write Cli command with Arguments: remote_dev_addr:{remote_dev_addr}, handle:{handle}, index:{index}, length:{length}, data:{data} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_set_long_att_value(self, remote_dev_addr: str, handle: int, offset: int, length: int, data: str,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout=10,
                               ):
        """ Arguments
                      dev_addr - remote device address
                     * @param[in]  handle 	- attribute handle
                     * @param[in]  offset 	- attribute value offset
                     * @param[in]  data_len - attribute value length
                     * @param[in]  p_data 	- attribute value
        """
        line = f"ble_set_long_att_value {mac_address_to_string(remote_dev_addr, ':')} {handle} {offset} {length} {data}"

        self.logger.info(
            f"**** initiating  ble_set_long_att_value Cli command with Arguments: remote_dev_addr:{remote_dev_addr}, handle:{handle}  offset:{offset}, length:{length}, data:{data} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_app_set_periodic_ae_params(self, max_interval: int, min_interval: int, properties: int,
                                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                       timeout=10,
                                       ):
        """ Arguments
                     max_interval                     = 0x190;
                     min_interval                     = 0x90;
                     properties                       = 0x40;
        """
        line = f"ble_app_set_periodic_ae_params {max_interval} {min_interval} {properties}"

        self.logger.info(
            f"**** initiating  ble_app_set_periodic_ae_params Cli command with Arguments: {max_interval}  min_interval:{min_interval}, properties:{properties} *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_start(self,
                  capability=3,
                  bond_info=0,
                  set_smp=0,
                  smp_pair=0,
                  timeout=10,
                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                  skip_bt_local_address=False,
                  ):
        line = f"init_ble {capability} {bond_info} {set_smp} {smp_pair}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        if not skip_bt_local_address:
            self.ble_address = self.bt_get_local_address()
            self.verify_status(status, expected_status)
        return self.ble_address

    @defaults("bluetooth")
    def ble_set_smp(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, set_smp: int = 0, timeout=2):
        self.logger.info("set smp")
        line = f"set_smp {set_smp}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_add_hid_service(self,
                            timeout=10,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            ):
        line = f"ble_add_hid_service"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        self.add_hid_service = False

    @defaults("bluetooth")
    def ble_hid_send_interrupt(self,
                               data,
                               timeout=10,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               ):
        line = f"ble_hid_send_interrupt {data}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def set_ble_per_tx_params(self, cmd_ix, transmit_enable,
                              access_addr, phy_rate, rx_chnl_num,
                              tx_chnl_num, scrambler_seed,
                              le_chnl_type, freq_hop_en, ant_sel,
                              pll_mode, rf_type, rf_chain, pkt_len,
                              payload_type, tx_power, transmit_mode,
                              inter_pkt_gap, num_pkts,
                              timeout=10,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK
                              ):
        arg5 = str(rx_chnl_num).zfill(3) + ":" + str(tx_chnl_num).zfill(3) + ":" + str(scrambler_seed).zfill(
            3) + ":" + str(
            le_chnl_type).zfill(3) + ":" + str(freq_hop_en).zfill(3)
        arg6 = str(ant_sel).zfill(3) + ":" + str(pll_mode).zfill(3) + ":" + str(rf_type).zfill(3) + ":" + str(
            rf_chain).zfill(3)
        self.logger.info("======= Set ble PER tx params")
        line = f"ble_per_tx {cmd_ix} {transmit_enable} {access_addr} {phy_rate} {arg5} {arg6} {pkt_len} {payload_type} {tx_power} {transmit_mode} {inter_pkt_gap} {num_pkts}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_per_receive(self,
                        cmd_ix,
                        receive_enable,
                        access_addr,
                        phy_rate,
                        config,
                        ant_sel,
                        pll_mode,
                        rf_type,
                        rf_chain,
                        ext_data_len_indication,
                        loop_back_mode,
                        duty_cycling_en,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=30
                        ):
        self.logger.info("======= start ble PER receive")
        line = f"ble_per_rx {cmd_ix} {receive_enable} {access_addr} {phy_rate} {config} {ant_sel} {pll_mode} {rf_type} {rf_chain} {ext_data_len_indication} {loop_back_mode} {duty_cycling_en}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    def bt_stop(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=2):
        self.logger.info(f"Initiating the BT stop command")
        line = f"bt_deinit"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def get_bt_per_tx_stats(self,
                            cmd_type,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout=30
                            ):
        self.logger.info("======= start bt PER stats")
        line = f"bt_per_stats {cmd_type}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_gatt_start(self,
                       set_smp=1,
                       bond_info=0,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout=30):
        command = f"init_ble_gatt {set_smp} {bond_info}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(command, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                command, timeout=timeout,
                )
        time.sleep(5)
        self.verify_status(status, expected_status)
        self.ble_address = self.bt_get_local_address()

        return self.ble_address

    @defaults("bluetooth")
    def ble_add_service(self, uid: int = 110,
                        service_size=0,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=30,
                        ):
        line = f"ble_add_service {uid} {service_size}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def cleanup_ble(self,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=30,
                        ):
        line = f"ble_cleanup"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_ae_set_periodic_sync(self, remote_dev_addr: str,
                                 adv_addr_type: int = 0,
                                 adv_sid: int = 0,
                                 fil_policy: int = 1,
                                 skip: int = 0,
                                 sync_timeout: int = 48,
                                 BLE_AE_PER_SYNC: int = 0,
                                 sync_create: int = 0,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout=33,
                                 ):
        line = f"ble_ae_set_periodic_sync {remote_dev_addr} {adv_addr_type} {adv_sid} {fil_policy} {skip} {sync_timeout} {BLE_AE_PER_SYNC} {sync_create}"
        self.logger.info(f"**** initiating  ble_ae_set_periodic_sync  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    
    @defaults("bluetooth")
    def ble_connect_cancel(self,remote_dev_addr: str,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout=30):
        command = f"ble_connect_cancel {remote_dev_addr}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(command, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                command, timeout=timeout,
                )
        time.sleep(5)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_ae_dev_to_periodic_list(self, remote_dev_addr: str,
                                    adv_addr_type: int = 1,
                                    adv_sid: int = 11,
                                    type: int = 1,
                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout=3,
                                    ):
        line = f"ble_ae_dev_to_periodic_list {remote_dev_addr} {adv_addr_type} {adv_sid} {type}"
        self.logger.info(f"**** initiating  ble_ae_dev_to_periodic_list  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_ae_read_periodic_adv_list_size(self, size: int = 0,
                                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                           timeout=30,
                                           ):
        line = f"ble_ae_read_periodic_adv_list_size {size}"
        self.logger.info(f"**** initiating  ble_ae_read_periodic_adv_list_size  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_get_max_no_of_supp_adv_sets(self, no_adv_sets: int = 0,
                                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                        timeout=30,
                                        ):
        line = f"ble_get_max_no_of_supp_adv_sets {no_adv_sets}"
        self.logger.info(f"**** initiating  ble_get_max_no_of_supp_adv_sets  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_get_max_adv_data_len(self, max_data_len: int = 0,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout=30,
                                 ):
        line = f"ble_get_max_adv_data_len {max_data_len}"
        self.logger.info(f"**** initiating  ble_get_max_adv_data_len  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_extended_connect_with_params(self, remote_dev_addr: str,
                                         remote_addr_type: int = 0,
                                         initiator_filter_policy: int = 0,
                                         init_phys: int = 7,
                                         ScanInterval: int = 256,
                                         ScanWindow: int = 80,
                                         ConnIntervalMin: int = 160,
                                         ConnIntervalMax: int = 160,
                                         ConnLatency: int = 0,
                                         ConnSTO: int = 2000,
                                         MinCELen: int = 0,
                                         MaxCELen: int = 0,
                                         own_addr_type: int = 0,
                                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                         timeout=3,
                                         ):
        line = f"ble_extended_connect_with_params {own_addr_type} {remote_addr_type} {mac_address_to_string(remote_dev_addr, ':')} " \
               f"{initiator_filter_policy} {init_phys} {ScanInterval} {ScanWindow} " \
               f"{ConnIntervalMin} {ConnIntervalMax} {ConnLatency} {ConnSTO} {MinCELen} {MaxCELen}"
        self.logger.info(f"**** initiating  ble_extended_connect_with_params  *****")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_add_char_serv_att(
            self,
            uid: int = 111,
            permissions: int = BLEPermissions.DEFAULT,
            service_handler_num: int = 1,
            value_handler_num: int = 2,
            service_size=0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ):
        line = f"ble_add_char_serv_att {uid} {permissions} {service_handler_num} {value_handler_num} {service_size}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_att_value_async(
            self,
            ble_remote_dev_address: str,
            char_property,
            expected="rsi_ble_on_read_resp_event_gatt - resolved",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10,
            async_timeout=30
            ):
        line = f"ble_get_att_value_async {mac_address_to_string(ble_remote_dev_address, ':')} {char_property}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[AsyncIdentifiers.GATT_DESC_SERVICES],
                                                        async_timeout=async_timeout,
                                                        event_expected=expected
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        self.logger.info(f"data: {data}")
        values = re.findall(r"- att_value - (\w+)", data.decode("utf-8"))
        return values[0] if len(values) == 1 else data

    @defaults("bluetooth")
    def ble_set_advertise_data(
            self,
            datalen="BLE_SMP_SC",
            data: str = "2,1,6",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=5,
            ):
        line = f"ble_set_adv_data {data} {datalen}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_add_char_val_att(
            self,
            uid: int = 111,
            permissions: int = BLEPermissions.DEFAULT,
            value_handler_num: int = 2,
            data: str = "data",
            enable_custom_feature=0,
            custom_feature=0,
            service_size=0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ):
        line = f"ble_add_char_val_att {uid} {permissions} {value_handler_num} {data} {enable_custom_feature} {custom_feature} {service_size}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_notify_custom_value(self,
                                ble_remote_dev_address: str,
                                data="testdataformaxsizetx",
                                custom_feature=1,
                                data_address=None,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=30):
        """
        Send a custom BLE notification.

        Parameters:
        ble_remote_dev_address (str): The address of the remote BLE device.
        data (str): The data to be sent in the notification. Default is "testdataformaxsizetx".
        custom_feature (int): A custom feature flag. Default is 1.
        expected_status (SLStatus): The expected status after the operation. Default is SLStatus.SL_STATUS_OK.
        timeout (int): The timeout for the operation in seconds. Default is 30.

        Returns:
        None
        """
        with self._lock:
            if data_address is None:
                address = self.allocate_memory(size=len(data))
                self.load_memory(address=address, size=len(data), write_content=data)
            else:
                address = data_address

            line = f"ble_notify_custom_value {ble_remote_dev_address} {address} {custom_feature} {len(data)}"

            if self.test_agent_thread_enabled:
                status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                            async_identifiers=[]
                                                            )
            else:
                status, data = self.issue_command(
                    line, timeout=timeout,
                    )
            if data_address is None:
                self.memory_free(address)
            self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_remove_service(self,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout=2):
        self.logger.info(f"For removing gatt services on dut")
        line = f"ble_remove_service"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_profiles_async(
            self,
            ble_remote_dev_address: str,
            expected="RSI_BLE_GATT_PROFILES - resolved",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=60,
            async_timeout=30
            ):
        line = f"ble_get_profiles_async {mac_address_to_string(ble_remote_dev_address, ':')}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout,
                async_identifiers=[AsyncIdentifiers.GATT_PROFILES],
                event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

        uuids_list = re.findall(r"uuid:(\w+)", data.decode())
        self.logger.info(f"uuids_list:{uuids_list}")
        return uuids_list

    @defaults("bluetooth")
    def ble_get_profile_async(
            self,
            ble_remote_dev_address: str,
            uuid,
            expected="RSI_BLE_GATT_PROFILE - resolved",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            async_timeout=30
            ):
        line = f"ble_get_profile_async {mac_address_to_string(ble_remote_dev_address, ':')} {uuid}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout,
                async_identifiers=[AsyncIdentifiers.GATT_PROFILE],
                event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        start_handle_result = re.findall(r"start_handle:(\w+)", data.decode())
        end_handle_results = re.findall(r"end_handle:(\w+)", data.decode())
        if len(start_handle_result) == 1 and len(end_handle_results) == 1:
            return start_handle_result[0], end_handle_results[0], data.decode()
        return None, None, data.decode()

    @defaults("bluetooth")
    def ble_get_char_services_async(
            self,
            ble_remote_dev_address: str,
            start_handle,
            end_handle,
            expected="RSI_BLE_GATT_CHAR_SERVICES - resolved",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            async_timeout=40
            ):
        line = f"ble_get_char_services_async {mac_address_to_string(ble_remote_dev_address, ':')} {start_handle} {end_handle}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[AsyncIdentifiers.GATT_CHAR_SERV],
                                                        async_timeout=async_timeout,
                                                        event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        char_properties = re.findall(r"char_property:([\d]*)", data.decode())

        uuids = re.findall(r"uuid:([\w]*)", data.decode())

        write_handles = re.findall(
            r"write_handle:([\w]*)", data.decode())
        return uuids, write_handles, char_properties

    @defaults("bluetooth")
    def ble_set_att_value_async(
            self,
            ble_remote_dev_address: str,
            char_property,
            data,
            data_length,
            expected="RSI_BLE_WRITE_EVENT_RESP",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            data_address=None,
            timeout=30,
            ):
        if data_address is None:
            address = self.allocate_memory(size=len(data))
            self.load_memory(address=address, size=len(data), write_content=data)
        else:
            address = data_address
        line = f"ble_set_att_value_async {mac_address_to_string(ble_remote_dev_address, ':')} {char_property} {address} {data_length}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        if data_address is None:
            self.memory_free(address)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_att_value(
            self,
            ble_remote_dev_address: str,
            handle: int,
            enable_notify: int,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            expected="rsi_ble_on_gatt_write_event_gatt - resolved",
            async_timeout: int = 30,
            timeout=30,
            ):
        line = f"ble_set_att_value {mac_address_to_string(ble_remote_dev_address, ':')} {handle} {enable_notify}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[AsyncIdentifiers.GATT_WRITE_EVENT],
                                                        event_expected=expected,
                                                        async_timeout=async_timeout
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.logger.info(f"The data is {data}")
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_notify_value(
            self,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
    ):
        self.logger.info(f"Initiating ble_set_local_att_value ")
        line = f"ble_notify_value"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_local_att_value(
            self,
            notify_data: str = "data",
            val_handle: int = 3,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ):
        self.logger.info(f"Initiating ble_set_local_att_value ")
        line = f"ble_set_local_att_value {notify_data} {val_handle} {len(notify_data)}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[]
                                                        )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_att_cmd(
            self,
            ble_remote_dev_address: str,
            handle: int,
            data: str,
            data_length: int,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            data_address=None,
            timeout=30,
            ):
        if data_address is None:
            address = self.allocate_memory(size=len(data))
            self.load_memory(address=address, size=len(data), write_content=data)
        else:
            address = data_address
        line = f"ble_set_att_cmd {mac_address_to_string(ble_remote_dev_address, ':')} {handle} {address} {data_length}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        if data_address is None:
            self.memory_free(address)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def enable_bt_power_save(
            self,
            psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
            psp_type=Si91xPowerSaveProcedureTypes.FastPowerSave,
            timeout=10,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        psp_type = Si91xPowerSaveProcedureTypes.MaxPowerSave
        self.logger.info("======= enabling BT power save on DUT")
        line = f"bt_power_save_profile {psp_mode} {psp_type}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        if psp_mode == 0:
            self.bt_power_save = False
        else:
            self.bt_power_save = True
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def bt_set_local_name(self, bt_local_name: str, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=2):
        line = f"bt_set_local_name {bt_local_name}"

        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def bt_get_local_name(self, timeout=2):
        return self.__get_bt_local_name(timeout)

    @defaults("bluetooth")
    def __get_bt_local_name(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=2) -> str:
        line = f"bt_get_local_name"

        if self.test_agent_thread_enabled:
            status, result = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, result = self.issue_command(
                line, timeout=timeout,
                )
            self.verify_status(status, expected_status)
        return result.splitlines()[-2].decode()

    @defaults("bluetooth")
    def ble_start_scanning(
            self,
            ble_address: Optional[Union[bytes, str]] = None,
            ble_scan_type: int = 1,
            ble_scan_filter_type: int = 0,
            ble_scan_interval: int = 256,
            ble_scan_window: int = 80,
            ble_address_type: int = 0,
            ble_client_address=None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            expected="rsi_ble_simple_central_on_adv_report_event",
            async_timeout=30
            ):
        self.logger.info("Initiating BLE scanning from dut")
        line = f"ble_start_scanning {ble_client_address} {ble_scan_type} {ble_scan_filter_type}" \
               f" {ble_scan_interval} {ble_scan_window} {ble_address_type}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_timeout=async_timeout,
                                                        async_identifiers=[AsyncIdentifiers.ADVERTISE],
                                                        event_expected=expected
                                                        )

        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.ble_scanning = True
        self.logger.info(f"status : {status}, data :{data}")
        self.verify_status(status, expected_status)
        return data

    def ble_stop_scanning(self, timeout=10, expected_status: SLStatus = SLStatus.SL_STATUS_OK,):
        line = f"ble_stop_scanning"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        self.ble_scanning = False

    @defaults("bluetooth")
    def ble_start_advertising(
            self,
            ble_advertising_data: str = "RS9116_BLE",
            ble_address: Optional[Union[bytes, str]] = None,
            ble_adv_type: int = 128,
            ble_adv_filter_type: int = 0,
            ble_addr_type: int = 0,
            ble_dir_addr: str = "00:15:83:6A:64:17",
            ble_adv_int_min: int = 256,
            ble_adv_int_max: int = 512,
            own_addr_type: int = 0,
            ble_adv_channel_map: int = 7,
            ibeacon_info: int = 0,
            timeout: int = 10,
            test_scenario="positive",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        if test_scenario == "positive":
            if ble_adv_int_min < 32:
                raise Exception(
                    "Invalid Advertising interval is given it must be within a range of 32-16384 ie. 20 ms to 10.24 sec")
            if ble_adv_int_max > 16384:
                raise Exception(
                    "Invalid Advertising interval is given it must be within a range of 32-16384 ie. 20 ms to 10.24 sec")
            if ble_adv_int_min > ble_adv_int_max:
                raise Exception("Advertising min interval should be greater than equal to max interval")
        if ble_address is not None:
            self.issue_command(
                f"ble_set_address {mac_address_to_string(ble_address, ':')}",
                timeout=timeout,
                )
            self.ble_address = mac_address_to_string(ble_address, ':')
        line = f"ble_start_advertising {ble_advertising_data} " \
               f"{ble_adv_type} " \
               f"{ble_adv_filter_type} " \
               f"{ble_addr_type} " \
               f"{ble_dir_addr} " \
               f"{ble_adv_int_min} " \
               f"{ble_adv_int_max} " \
               f"{own_addr_type} " \
               f"{ble_adv_channel_map} " \
               f"{ibeacon_info} "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        self.ble_advertising_data = ble_advertising_data
        self.ble_advertising = True

    @defaults("bluetooth")
    def ble_update_conn_param(
            self,
            ble_remote_dev_address: str,
            ble_conn_interval_min: Si91xBleConnParams.SL_BLE_CONN_INTERVAL_MIN,
            ble_conn_interval_max: Si91xBleConnParams.SL_BLE_CONN_INTERVAL_MAX,
            ble_conn_latency: Si91xBleConnParams.SL_BLE_CONN_LATENCY,
            ble_supervision_timeout: Si91xBleConnParams.SL_BLE_SUPERVISION_TIMEOUT,
            timeout=20,
            async_timeout=30,
            expected="RSI_BLE_CONN_UPDATE_COMPLETE_EVENT",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,

            ):
        line = f"ble_update_conn_params {mac_address_to_string(ble_remote_dev_address, ':')} " \
               f"{ble_conn_interval_min} {ble_conn_interval_max} " \
               f"{ble_conn_latency} {ble_supervision_timeout}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=
                [AsyncEventIdentifiers.BLE_CONNECT], event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
            )
        self.verify_status(status, expected_status)
        return status

    def ble_stop_advertising(self, timeout=10):
        line = f"bt_stop_advertising"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.ble_advertising = False

    @defaults("bluetooth")
    def ble_connect(
            self,
            ble_remote_dev_address: str,
            ble_scan_interval: int = 256,
            ble_scan_window: int = 80,
            ble_conn_interval_min: int = 160,
            ble_conn_interval_max: int = 160,
            ble_conn_latency: int = 0,
            ble_supervision_timeout: int = 2000,
            timeout=20,
            async_timeout=30,
            expected="RSI_BLE_CONN_UPDATE_COMPLETE_EVENT",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,

            ):
        line = f"ble_connect {mac_address_to_string(ble_remote_dev_address, ':')} " \
               f"{ble_scan_interval} {ble_scan_window} {ble_conn_interval_min} {ble_conn_interval_max} " \
               f"{ble_conn_latency} {ble_supervision_timeout}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=
                [AsyncEventIdentifiers.BLE_CONNECT], event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_enhance_connect_with_params(
            self,
            dev_addr_type: int,
            dev_addr: str,
            filter_policy: int,
            own_addr_type: int,
            le_scan_interval: int,
            le_scan_window: int,
            conn_interval_min: int,
            conn_interval_max: int,
            conn_latency: int,
            supervision_tout: int,
            min_ce_length: int,
            max_ce_length: int,
            timeout=20,
            async_timeout=30,
            expected="success",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,

            ):
        """Arguments:
         dev_addr_type - Address type of the device to connect \n
 *                             0 - Public Address \n
 *                             1 - Random Address \n \n
 *             dev_addr - Address of the device to connect \n \n
 *             filter_policy - Initiater filter policy is used to determine whether the Filter Accept List is used. \n
 *                             0 - Filter Accept List is not used to determine which advertiser to connect to. \n
 *                             1 - Filter Accept List is used to determine which advertiser to connect to. \n \n
 *             own_addr_type - own address type \n \n
 *             le_scan_interval - LE Scan Interval : N=0xXXXX \n
 *                             It is defined as the time interval from when the Controller started its last LE scan until it begins the subsequent LE scan. \n
 *                             Range: 0x0004 to 0x4000 \n
 *                             Time = N * 0.625 msec \n
 *                             Time Range: 2.5 msec to 10 . 24 seconds \n \n
 *             le_scan_window - LE Scan Window : N=0xXXXX \n
 *                           Amount of time for the duration of the LE scan. LE_Scan_Window must be less than or equal to LE_Scan_Interval \n
 *                           Range: 0x0004 to 0x4000 \n
 *                           Time = N * 0.625 msec \n
 *                           Time Range: 2.5 msec to 10 . 24 seconds \n \n
 *             conn_interval_min - Min Connection Interval : N=0xXXXX \n
 *                                 Minimum value for the connection event interval, which must be greater than or equal to Conn_Interval_Max. \n
 *                                 Range: 0x0006 to 0x0C80 \n
 *                                 Time = N * 1.25 msec \n
 *                                 Time Range: 7.5 msec to 4 seconds. \n
 *                                 0x0000 - 0x0005 and 0x0C81 - 0xFFFF - Reserved for future use \n \n
 *             conn_interval_max - Max Connection Interval : N=0xXXXX \n
 *                                 Maximum value for the connection event interval, which must be greater than or equal to Conn_Interval_Min. \n
 *                                 Range: 0x0006 to 0x0C80 \n
 *                                 Time = N * 1.25 msec \n
 *                                 Time Range: 7.5 msec to 4 seconds. \n
 *                                 0x0000 - 0x0005 and 0x0C81 - 0xFFFF - Reserved for future use \n \n
 *             conn_latency - Connection Latency : N = 0xXXXX \n
 *                            Slave latency for the connection in number of connection events. \n
 *                            Range: 0x0000 to 0x01F4 \n \n
 *             supervision_tout - Supervision Timeout : N = 0xXXXX \n
 *                                Supervision timeout for the LE Link. \n
 *                                Range: 0x000A to 0x0C80 \n
 *                                Time = N * 10 msec \n
 *                                Time Range: 100 msec to 32 seconds \n
 *                                0x0000 - 0x0009 and 0x0C81 - 0xFFFF - Reserved for future use \n \n
 *             min_ce_length - Min Connection Event Length : N=0xXXXX \n
 *                             The minimum length of connection event recommended for this LE connection. \n
 *                             Range: 0x0000 to 0xFFFF \n
 *                             Time = N * 0.625 msec \n \n
 *             max_ce_length - Max Connection Event Length : N=0xXXXX \n
 *                             The maximum length of connection event recommended for this LE connection. \n
 *                             Range: 0x0000 to 0xFFFF \n
 *                             Time = N * 0.625 msec \n \n

        """
        self.logger.info(
            f"**** Intiating ble_enhance_connect_with_params cli command with arguments dev_addr_type:{dev_addr_type}, dev_addr:{dev_addr}, filter_policy:{filter_policy}, own_addr_type:{own_addr_type}, le_scan_interval:{le_scan_interval}, le_scan_window:{le_scan_window}, conn_interval_min:{conn_interval_min}, conn_interval_max:{conn_interval_max}, conn_latency:{conn_latency}, supervision_tout:{supervision_tout}, min_ce_length:{min_ce_length}, max_ce_length:{max_ce_length}  *****")
        line = f"ble_enhance_connect_with_params {dev_addr_type} {mac_address_to_string(dev_addr, ':')} " \
               f"{filter_policy} {own_addr_type} {le_scan_interval} {le_scan_window} " \
               f"{conn_interval_min} {conn_interval_max} {conn_latency} {supervision_tout} {min_ce_length} {max_ce_length}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=
                [AsyncEventIdentifiers.BLE_CONNECT], event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_get_char_value_by_uuid(
            self,
            ble_remote_dev_address: str,
            start_handle,
            end_handle,
            uuid,
            expected="RSI_BLE_READ_ATT_VALUE_EVT - resolved",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            async_timeout=30
            ):
        line = f"ble_get_char_value_by_uuid {mac_address_to_string(ble_remote_dev_address, ':')} {start_handle} {end_handle} {uuid}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout,
                async_identifiers=[AsyncIdentifiers.GATT_READ_ATT_VALUE],
                event_expected=expected)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_prepare_write_async(
            self,
            ble_remote_dev_address: str,
            handle,
            offset,
            data_len,
            data,
            expected="RSI_BLE_PREPARE_WRITE_RSP_EVENT",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = f"ble_prepare_write_async {mac_address_to_string(ble_remote_dev_address, ':')} {handle} {offset} {data_len} {data}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=15,
                async_identifiers=[AsyncIdentifiers.GATT_WRITE_EVENT],
                event_expected=expected,
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_execute_write_async(self,
                                ble_remote_dev_address: str,
                                exe_flag,
                                expected="success",
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10):
        line = f"ble_execute_write_async {mac_address_to_string(ble_remote_dev_address, ':')} {exe_flag}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=15, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_get_att_descriptor(self,
                               ble_devices_address,
                               start_handle,
                               end_handle,
                               expected="RSI_BLE_GATT_CHAR_DESC_RESP_EVENT",
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout=10
                               ):
        """
            This method is used to get the attribute descriptor of a BLE device.

            Parameters:
            ble_devices_address (str): The address of the BLE device.
            start_handle (int): The starting handle for the attribute descriptor search.
            end_handle (int): The ending handle for the attribute descriptor search.
            expected (str): The expected event to be received. Default is "RSI_BLE_GATT_CHAR_DESC_RESP_EVENT".
            expected_status (SLStatus): The expected status after the operation. Default is SLStatus.SL_STATUS_OK.
            timeout (int): The timeout for the operation in seconds. Default is 10.

            Returns:
            tuple: The status and data received from the device.
            """
        line = f"ble_get_att_desc {ble_devices_address} {start_handle} {end_handle}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=15,
                async_identifiers=[AsyncIdentifiers.GATT_DESC_RESP],
                event_expected=expected,
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        num_of_att = re.findall(r"num_of_att:(\d+)", data.decode())
        pattern = r"Handle: (0x[0-9a-fA-F]+ - 0x[0-9a-fA-F]+)"
        matches = re.findall(pattern, data.decode())
        self.verify_status(status, expected_status)
        values = [num_of_att, matches]
        return matches

    @defaults("bluetooth")
    def ble_set_adv_data(
            self,
            ble_advertising_data: str = "BLE_SET_ADV_DATA",
            timeout: int = 10,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            async_timeout=15,
            ):
        data_len = len(ble_advertising_data)
        line = f"ble_set_adv_data {ble_advertising_data} {data_len}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_device_state(self, timeout=10):
        line = f"ble_get_device_state"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=15, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.logger.info(f"get device state response : ***{data.strip()}****")
        return data.strip()

    @defaults("bluetooth")
    def ble_uuid_32bit_to_128bit(
            self,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10
            ):
        line = f"ble_uuid_32bit_to_128bit"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_scan_response_data(
            self,
            scan_response_data: str = "RS9116_BLE_SRD",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=5,
            ):
        line = f"ble_set_scan_response_data {scan_response_data}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_disconnect(self, ble_remote_dev_address: str, timeout=10,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        line = f"ble_disconnect {mac_address_to_string(ble_remote_dev_address, ':')}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_add_white_list(self,
                           remote_dev_addr: str = None,
                           remote_addr_type=0,
                           async_timeout=15,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout=5):
        line = f"ble_add_white_list {remote_dev_addr} {remote_addr_type}"
        self.logger.info(" ======= add whitelist device")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_deletefrom_white_list(self,
                                  remote_dev_addr: str,
                                  remote_addr_type=0,
                                  async_timeout=15,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout=5):
        line = f"ble_deletefrom_white_list {remote_dev_addr} {remote_addr_type}"
        self.logger.info(f"\n *** Initiating ble_deletefrom_white_list *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_clear_white_list(self,
                             async_timeout=15,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout=5):
        line = f"ble_clear_white_list"
        self.logger.info(f"\n *** Initiating ble_clear_white_list *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_read_phy(self,
                     remote_dev_addr: str,
                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                     timeout=10
                     ):
        line = f"ble_read_phy {remote_dev_addr}"
        self.logger.info("=====Initiating ble_read_phy")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_set_phy(self,
                    remote_dev_addr: str,
                    tx_phy: int = 4,
                    rx_phy: int = 4,
                    coded_phy: int = 1,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout=15
                    ):
        line = f"ble_set_phy {remote_dev_addr} {tx_phy} {rx_phy} {coded_phy}"
        self.logger.info("=====Initiating ble_set_phy")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_add_whitelist_adv_data(self,
                                   enable,
                                   data_compare_index,
                                   compare_data_length,
                                   payload="",
                                   data_list=None,
                                   async_timeout=15,
                                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                   timeout=10):
        if data_list is None:
            data_list = []
        for index in range(len(data_list)):
            if index == (len(data_list) - 1):
                payload = payload + str(ord(data_list[index]))
                break
            payload = payload + str(ord(data_list[index])) + ":"
        self.logger.info(" ======= set whitelist adv data on dut")
        line = f"ble_add_white_list_adv_data {enable} {data_compare_index} {compare_data_length} {payload}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_timeout=async_timeout, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)
        return status

    def set_listen_interval(self,
                            listen_interval: int = Si91xJoinFeatureBitMap.ListenIntervalDefault,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout=10):
        line = f"wifi.set_listen_interval {listen_interval}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_remove_gatt_attribute(
            self,
            service_handler,
            att_handl,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=5
            ):
        line = f"ble_remove_gatt_attribute {service_handler, att_handl}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    def set_join_feature_bitmap(self,
                                interface: str = 'client',
                                join_feature_bitmap: int = Si91xJoinFeatureBitMap.Default,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout=10
                                ):
        line = f"wifi.set_join_feature_bitmap -i {interface} -j {join_feature_bitmap}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_get_long_att_value_async(self,
                                     ble_remote_dev_address: str,
                                     handle,
                                     offset,
                                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                     timeout=10,
                                     ):
        line = f"ble_get_long_att_value_async {mac_address_to_string(ble_remote_dev_address, ':')} {handle} {offset}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_get_multiple_att(self,
                             ble_remote_dev_address: str,
                             no_of_handles: int,
                             handle_1: int,
                             handle_2: int,
                             expected="rsi_ble_on_read_resp_event_gatt - resolved",
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout=10,
                             ):
        """
            Fetches multiple attribute values from a BLE device.

            Args:
                ble_remote_dev_address (str): The MAC address of the remote BLE device.
                no_of_handles (int): The number of attribute handles to fetch.
                handle_1 (int): The first attribute handle.
                handle_2 (int): The second attribute handle.
                expected_status (SLStatus, optional): The expected status of the operation. Defaults to SLStatus.SL_STATUS_OK.
                timeout (int, optional): The timeout for the operation in seconds. Defaults to 10.

            Returns:
                tuple: A tuple containing the status of the operation and the data received.
                :param expected:
        """
        line = f"ble_get_multiple_att {mac_address_to_string(ble_remote_dev_address, ':')} {no_of_handles} {handle_1} {handle_2}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE,
                                                        async_identifiers=[AsyncIdentifiers.GATT_DESC_SERVICES],
                                                        event_expected=expected)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        data = data.decode()
        lines = data.split('\n')
        att_values = []
        for line in lines:
            if line.startswith('att_value:'):
                att_values_str = line.split(':')[1]
                att_values = [int(value.strip()) for value in att_values_str.split(',') if value.strip().isdigit()]
        return att_values

    @defaults("aws_iot")
    def aws_iot_shadow_init(self,
                            hostname,
                            port=8883,
                            thing_name='silicon_labs_thing',
                            client_id='silicon_labs_thing',
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 40):
        line = f"aws_iot_shadow_init {hostname} {port} {thing_name} {client_id}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_shadow_connect(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_connect"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.aws_flags['connected'] = True

    def aws_iot_shadow_register_delta(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_register_delta"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_shadow_yield(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_yield"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_shadow_init_json_document(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_init_json_document"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_shadow_add_reported(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_add_reported"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_finalize_json_document(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_finalize_json_document"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_shadow_update(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_shadow_update"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("aws_iot")
    def aws_iot_mqtt_init(self,
                          hostname,
                          port=8883,
                          client_id='silicon_labs_thing',
                          keep_alive_interval=1200,
                          iscleansession: bool = True,
                          isWillMsgPresent: bool = False,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 40):
        line = f"aws_iot_mqtt_init {hostname} {port} {client_id} {keep_alive_interval} {iscleansession}{f' -i {isWillMsgPresent}' if isWillMsgPresent else ''}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_mqtt_connect(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 60):
        line = f"aws_iot_mqtt_connect"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=60,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.aws_flags['connected'] = True

    def aws_select_socket(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_select_socket"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        result = re.findall(r'Data received on the Subscribed Topic is\s+(\w+)', data.decode())
        return result

    def aws_iot_mqtt_autoreconnect_set_status(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                              timeout: int = 40):
        line = f"aws_iot_mqtt_autoreconnect_set_status"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_mqtt_subscribe(self,
                               qos=1,
                               topic_name='si91x_sdk_automation',
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 40):
        line = f"aws_iot_mqtt_subscribe {qos} {topic_name}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.aws_flags['subscribed'] = True
        self.aws_flags['topic'] = topic_name

    def aws_iot_mqtt_publish(self,
                             topic_name='si91x_sdk_automation',
                             qos=1,
                             payload='Hi_from_SiWx917',
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout: int = 40,
                             negative_case=False):
        line = f"aws_iot_mqtt_publish {topic_name} {qos} {payload}"

        # Determine the command function and issue the command
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Log status and data if this is a negative test case
        if negative_case:
            self.logger.info(f"Data received: {data}, status: {hex(status)}")
            return status

        # Verify status for positive case
        self.verify_status(hex(status), hex(expected_status))

    def aws_iot_mqtt_publish_more(self,
                                  topic_name='si91x_sdk_automation',
                                  qos=1,
                                  payload='Hi_from_SiWx917',
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 40):
        address = self.allocate_memory(size=len(payload))
        self.load_memory(address=address, size=len(payload), write_content=payload)
        line = f"aws_iot_mqtt_publish_more {topic_name} {qos} {address}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aws_iot_mqtt_disconnect(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40):
        line = f"aws_iot_mqtt_disconnect"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.aws_flags['connected'] = False

    def aws_iot_mqtt_unsubscribe(self,
                                 topic_name='si91x_sdk_automation',
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout: int = 40):
        line = f"aws_iot_mqtt_unsubscribe {topic_name}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.aws_flags['subscribed'] = False

    def is_aws_connected(self):
        """
        Returns True if the DUT is connected to AWS, otherwise False.
        """
        return self.aws_flags.get('connected', False)

    def azure_iot_init(self,
                       hostname='silicon_labs_thing',
                       device_id='silicon_labs_thing',
                       port=4001,
                       mode=0,
                       symmetrickey: str = None,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout: int = 40):
        line = f'azure_iot_init {hostname} {device_id} {port} {mode} {f" -s {symmetrickey}" if symmetrickey else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.azure_flags['connected'] = True

    def azure_iot_subscribe(self,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 40):
        line = f"azure_iot_subscribe"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.azure_flags['subscribed'] = True

    def azure_iot_publish(self,
                          payload='silicon_labs_thing',
                          maxcount=10,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 40):
        line = f"azure_iot_publish {payload} {maxcount}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def azure_iot_recv(self,
                       maxcount=5,
                       maxtry=10,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout: int = 40):
        line = f"azure_iot_recv {maxcount} {maxtry}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
            self.logger.info(f"Data received: {data}, status:{status}")
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

        rx_data = re.findall(r'Cloud message payload : (\w+)', data.decode())
        self.logger.info(f"Received data: {rx_data}")
        return rx_data

    def azure_iot_unsubscribe(self,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                              timeout: int = 40):
        line = f"azure_iot_unsubscribe"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.azure_flags['subscribed'] = False

    def azure_iot_disconnect(self,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout: int = 40):
        line = f"azure_iot_disconnect"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        self.azure_flags['connected'] = False

    def sl_net_join_multicast_address(self,
                                      interface=8,
                                      server="239.0.0.1",
                                      expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                      timeout: int = 40):
        line = f"sl_net_join_multicast_address {interface} {server}"
        if self.test_agent_thread_enabled:
            self.logger.info(f"\n *** Initiating join multicast address: {server}*** \n")
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def sl_net_leave_multicast_address(self,
                                       interface=8,
                                       server="239.0.0.1",
                                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                       timeout: int = 40):
        line = f"sl_net_leave_multicast_address {interface} {server}"
        if self.test_agent_thread_enabled:
            self.logger.info(f"\n *** Initiating leave multicast address: {server}*** \n")
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("wifi")
    def firmware_upgrade(self,
                         flags: int = 0,
                         ip_address: str = None,
                         port: int = 80,
                         http_url: str = None,
                         host_name: str = '""',
                         extended_header: str = '""',
                         username: str = 'redpine',
                         password: str = 'redpine',
                         async_timeout: int = 240,
                         url_address: str = None,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=30,
                         ):
        if url_address is None:
            if http_url is not None:
                address = self.allocate_memory(size=len(http_url) + 1)
                self.load_memory(address=address, size=len(http_url), write_content=http_url)
        else:
            address = url_address
        self.logger.info(f"********** Upgrading DUT Firmware **********")
        line = f"otaf {flags} {ip_address} {port} {address} {host_name} {extended_header} {username} {password}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[],
                                                        async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        if url_address is None:
            if http_url is not None:
                self.memory_free(address)
        return status

    def update_firmware_over_tcp(self,
                                 socket=0,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout: int = 10
                                 ):
        line = f'update_firmware_over_tcp {socket}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def set_eap_credentials(
            self,
            username: str = 'user1',
            password: str = '12345678',
            credential_id: int = 1,
            credential_key: str = None,
            eap_flags: int = 0,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        self.logger.info("\n *** Enable set eap credentials *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                f"wifi.set_eap_credentials {username} {password} {credential_id}{f' -e {eap_flags}' if eap_flags else ''}{f' -c {credential_key}' if credential_key is not None else ''}",
                protocol=Protocol.WIFI)
        else:
            status, data = self.issue_command(
                f"wifi.set_eap_credentials {username} {password} {credential_id}{f' -e {eap_flags}' if eap_flags else ''}{f' -c {credential_key}' if credential_key is not None else ''}",
                )
        self.verify_status(status, expected_status)

    def set_rtc(self,
                seconds: int = 50,
                minutes: int = 59,
                hours: int = 18,
                day: int = 3,
                month: int = 9,
                year: int = 2023,
                weekday: int = 4,
                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                timeout: int = 0
                ):
        line = f"time.set {seconds} {minutes} {hours} {day} {month} {weekday} {year}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_rtc(self,
                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                timeout: int = 0
                ):
        time_data = {}
        line = "time.get"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line="time.get", timeout=timeout)
        self.verify_status(status, expected_status)
        time_var = data.split(b"\n")
        time_data['seconds'] = int(time_var[0].split(b":")[1].decode())
        time_data['minutes'] = int(time_var[1].split(b":")[1].decode())
        time_data['hours'] = int(time_var[2].split(b":")[1].decode())
        time_data['day_month'] = int(time_var[3].split(b":")[1].decode())
        time_data['month'] = int(time_var[4].split(b":")[1].decode())
        time_data['year'] = int(time_var[5].split(b":")[1].decode())
        time_data['week_day'] = int(time_var[6].split(b":")[1].decode())
        self.logger.info(
            f"Response received for get rtc-> seconds:{time_data['seconds']}, minutes:{time_data['minutes']}, hours:{time_data['hours']}, "
            f"day_month:{time_data['day_month']}, month:{time_data['month']}, year:{time_data['year']}, week_day:{time_data['week_day']}"
            )
        return time_data


    def mqtt_client_get_received_messages(
            self, since_time=None, allow_duplicates=False
            ) -> List[MqttMessage]:
        if since_time is None:
            since_time = 0
        start_timestamp = self.bus.start_timestamp
        filtered = [
            (timestamp + start_timestamp, record)
            for timestamp, record in self.bus.get_input_log()
            if timestamp + start_timestamp >= since_time
            ]
        raw_messages = self._merge_mqtt_incoming_serial_records(filtered)
        if not allow_duplicates:
            filtered_raw_messages = []
            seen_messages = set()
            for raw_message in raw_messages:
                if raw_message not in seen_messages:
                    filtered_raw_messages.append(raw_message)
                    seen_messages.add(raw_message)
            raw_messages = filtered_raw_messages
        mqtt_messages: List[MqttMessage] = []
        for timestamp, merged in raw_messages:
            parsed = self._parse_merged_mqtt_async_blob(merged)
            if parsed is None:
                continue
            topic_b, mqtt_message_b = parsed
            container_list = [topic_b.decode(), mqtt_message_b.decode()]
            mqtt_messages.extend(container_list)
        return mqtt_messages

    def send_data_pkts(self,
                       socket_id,
                       pkt_length,
                       no_of_pkts,
                       time_interval=480,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout=500,
                       server_ip=None,
                       server_port=0):
        self.logger.info(
            f"Initiate data transfer on socket {socket_id} for {no_of_pkts} number of packets with each "
            f"packet length {pkt_length} bytes"
            )
        line = f"send_data_config_pkts {socket_id} {pkt_length} {no_of_pkts} {time_interval} {server_ip} {server_port}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        async_timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode().split(":")[1].strip()

    def set_tx_on_multiple_sockets(
            self,
            socket_list=0,
            data_len=1300,
            time_interval=120,
            number_of_pkts=1000,
            timeout=300,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            ):
        line = f"tx_data_on_multiple_sockets {socket_list} {data_len} {time_interval} {number_of_pkts}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI, async_timeout=120,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

        socket_list = []
        raw_stats = data.decode().split(":")[1]
        entries = re.findall(r'(?:^|-)(\d+),([-\d]+),(\d+)', raw_stats)
        self.logger.info(f"socket stats info is {entries}")
        for entry in entries:
            sock_stats = int(entry[0])
            time_taken = int(entry[1])
            sock_status = int(entry[2])
            socket_list.append(tuple([sock_stats, time_taken, sock_status]))
        return socket_list

    def switch_host_frequency(self,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                              timeout: int = 2
                              ):
        line = f"switch_m4_freq"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_timeout_config(
            self,
            keep_alive_timeout_value: int = None,
            auth_assoc_timeout_value: int = None,
            active_chan_scan_timeout_value: int = None,
            passive_chan_scan_timeout_value: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            ):
        status, data = self.issue_command(
            f"wifi.set_timeout_config{f' -k {keep_alive_timeout_value}' if keep_alive_timeout_value else ''}{f' -a {auth_assoc_timeout_value}' if auth_assoc_timeout_value else ''}{f' -c {active_chan_scan_timeout_value}' if active_chan_scan_timeout_value else ''}{f' -p {passive_chan_scan_timeout_value}' if passive_chan_scan_timeout_value is not None else ''}"
            )
        self.verify_status(status, expected_status)

    def get_socket_rx_stats(self, socket_id=0, sock_type=0, size=None, ttl=None, no_of_pkts=None,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 40,
                            async_timeout: int = None):
        self.logger.info(
            f"receive {no_of_pkts} no of packets or until {ttl} sec time elapsed on socket {socket_id} if socket type is sync->1")
        line = f'get_socket_rx_stats {socket_id} {sock_type}{f" -b {size}" if size else ""}{f" -t {ttl}" if ttl else ""}{f" -p {no_of_pkts}" if no_of_pkts else ""}'

        if self.test_agent_thread_enabled:
            wait_timeout = async_timeout if async_timeout is not None else ((ttl + 1) if ttl is not None else timeout)
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=wait_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return re.sub(r"\D", "", data.decode())

    def reset_wifi_connection_disconnection_stats(self,
                                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                  timeout: int = 2
                                                  ):
        line = f"wifi.set_default_con_dis_stats"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_set_local_irk_value(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=2):
        line = f"ble_set_local_irk_value"
        self.logger.info(f"\n *** Initiating ble_set_local_irk_value  **** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_add_simple_chat_serv(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=2):
        line = f"ble_add_simple_chat_serv"
        self.logger.info(f"\n *** Initiating ble_add_simple_chat_serv **** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    @defaults("bluetooth")
    def ble_ae_set_scan_params(self,
                               ble_addr_type: int = 0,
                               scanning_filter_policy: int = 0,
                               scanning_phys: int = 5,
                               ScanInterval: int = 256,
                               ScanWindow: int = 80,
                               scan_type: int = 1,
                               remote_addr_type: int = 0,
                               scan_type_sec: int = 1,
                               scan_interval_sec: int = 256,
                               scan_window_sec: int = 80,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout=2):
        line = f"ble_ae_set_scan_params {ble_addr_type} {scanning_filter_policy} {scanning_phys} {ScanInterval} {ScanWindow} {scan_type} {remote_addr_type} {scan_type_sec} {scan_interval_sec} {scan_window_sec}"
        self.logger.info(f"\n *** Initiating ae_set_scan_params **** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status, data = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return data

    def ble_ae_set_scan_enable(self,
                               enable: int = 1,
                               filter_duplicates: int = 0,
                               duration: int = 0,
                               period: int = 256,
                               remote_address: str = "11:33:33:33:33:11",
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout=2,
                               async_timeout=10):
        line = f"ble_ae_set_scan_enable {enable} {filter_duplicates} {duration} {period} {mac_address_to_string(remote_address, ':')}"
        self.logger.info(f"\n *** Initiating ae_set_scan_enable *** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[], async_timeout=async_timeout
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    def ble_set_ae_params(self,
                          remote_dev_addr: str = "00:00:00:00:00:00",
                          adv_handle: int = 0,
                          adv_event_prop: int = 1,
                          primary_adv_intterval_min: int = 256,
                          primary_adv_intterval_max: int = 512,
                          primary_adv_chnl_map: int = 7,
                          own_addr_type: int = 0,
                          peer_addr_type: int = 1,
                          adv_filter_policy: int = 0,
                          adv_tx_power: int = 15,
                          primary_adv_phy: int = 1,
                          sec_adv_max_skip: int = 0,
                          sec_adv_phy: int = 1,
                          adv_sid: int = 0,
                          scan_req_notify_enable: int = 1,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=2):
        line = f"ble_set_ae_params {adv_handle} {adv_event_prop} {primary_adv_intterval_min} {primary_adv_intterval_max} {primary_adv_chnl_map} {own_addr_type} {peer_addr_type} {remote_dev_addr} {adv_filter_policy} {adv_tx_power} {primary_adv_phy} {sec_adv_max_skip} {sec_adv_phy} {adv_sid} {scan_req_notify_enable}"
        self.logger.info(f"\n *** Initiating set_ae_params **** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    def ble_start_ae_advertising(self,
                                 enable: int = 1,
                                 no_of_sets: int = 1,
                                 adv_handle: int = 0,
                                 duration: int = 0,
                                 max_ae_events: int = 0,
                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                 timeout=2,
                                 async_timeout=10):
        line = f"ble_start_ae_advertising {enable} {no_of_sets} {adv_handle} {duration} {max_ae_events}"
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[], async_timeout=async_timeout
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    def ble_set_ae_data(self,
                        type: int = 1,
                        adv_handle: int = 0,
                        operation: int = 0,
                        data_len: int = 25,
                        data: str = "BLE_AE_DATA",
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=2):
        line = f"ble_set_ae_data {type} {adv_handle} {operation} {data_len} {data}"
        self.logger.info(f"\n *** Initiating set_ae_data *** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    def set_ae_set_random_address(self,
                                  random_address: str = "11:22:33:33:22:11",
                                  adv_handle: int = 0,
                                  timeout=10,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK):
        line = f"set_ae_set_random_address {adv_handle} {random_address}"
        self.logger.info(f"\n *** Initiating ae_set_random_addres Cli command *** \n")
        if self.test_agent_thread_enabled:
            status = self.issue_command_in_thread(
                line, timeout=timeout, protocol=Protocol.BLE, async_identifiers=[]
                )
        else:
            status = self.issue_command(line, timeout=timeout)
            self.verify_status(status, expected_status)
        return status

    def sntp_client_start(self,
                          flags: int = 0,
                          server_ip: str = "10.200.110.11",
                          sntp_method: int = 2,
                          sntp_timeout: int = 50,
                          expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                          timeout: int = 30
                          ):
        line = (f'sntp.start {server_ip}{f" -m {sntp_method}" if sntp_method else ""}'
                f'{f" -t {sntp_timeout}" if sntp_timeout else ""}{f" -f {flags}" if flags else ""}')
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], timeout=timeout, async_timeout=60)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def sntp_get_time_data(self,
                           expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                           timeout: int = 30
                           ):
        line = f'sntp.get_time_data'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], timeout=timeout,
                                                        async_timeout=60)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        time = re.search(r"\d{1,2}:\d{1,2}:\d{1,2}\.\d+", data.decode())
        date = re.search(r"[a-zA-Z]+\s[0-9]*\,\s\d+", data.decode())
        self.verify_status(status, expected_status)
        return time.group(0), date.group(0)

    def sntp_get_server_info(self,
                             expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                             timeout: int = 30
                             ):
        line = f'sntp.get_server_info'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], timeout=timeout,
                                                        async_timeout=60)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        ip_version = re.search(r"IP version : (\d)", data.decode())
        sntp_method = re.search(r"Server Method : (\d)", data.decode())
        server_ip = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", data.decode())
        self.verify_status(status, expected_status)
        return ip_version.group(0), sntp_method.group(0), server_ip.group(0)

    def sntp_client_stop(self,
                         expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                         timeout: int = 20
                         ):
        line = f'sntp.stop'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], timeout=timeout,
                                                        async_timeout=40)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_ssl_cipher(self, cipher_list=0, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"Set ssl cipher list to {cipher_list}")
        line = f"wifi_set_ssl_cipher {cipher_list}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_extended_ssl_cipher(self, cipher_list=0, expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout: int = 10):
        self.logger.info(f"Set extended ssl cipher list to {cipher_list}")
        line = f"wifi_set_extended_ssl_cipher {cipher_list}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_default_ssl_cipher(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"Select default ssl cipher list")
        line = f"wifi_set_default_ssl_cipher"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_default_extended_ssl_cipher(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"Select default extended ssl cipher list")
        line = f"wifi_set_extended_default_ssl_cipher"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def aes_encrypt(self,
                    aes_mode=Si91xAesType.SL_SI91X_AES_CBC,
                    enc_mode=Si91xAesOperation.SL_SI91X_AES_ENCRYPT,
                    msg="",
                    key_size=Si91xAesKeySize.SL_SI91X_AES_KEY_SIZE_128,
                    wrap_iv_mode=Si91xWrapIVMode.SL_SI91X_WRAP_IV_ECB_MODE,
                    key_type=Si91xKeyType.SL_SI91X_TRANSPARENT_KEY,
                    key="",
                    use_wrapped_keys=None,
                    wrap_config_key_type=Si91xKeyType.SL_SI91X_TRANSPARENT_KEY,
                    wrap_config_key_size=Si91xAesKeySize.SL_SI91X_AES_KEY_SIZE_128,
                    wrap_config_wrap_iv_mode=Si91xWrapIVMode.SL_SI91X_WRAP_IV_ECB_MODE,
                    pkcs_7_padding=None,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 5
                    ):
        self.logger.info(f"encrypt the message {msg}")
        line = f'crypto.aes.encrypt {aes_mode} {enc_mode} {msg} {key_size} {wrap_iv_mode} {key_type} {key}{f" -w {use_wrapped_keys}" if use_wrapped_keys is not None else ""}{f" -t {wrap_config_key_type}" if wrap_config_key_type is not None else ""}{f" -s {wrap_config_key_size}" if wrap_config_key_size is not None else ""}{f" -i {wrap_config_wrap_iv_mode}" if wrap_config_wrap_iv_mode is not None else ""}{f" -p {pkcs_7_padding}" if pkcs_7_padding is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.logger.info(f"status is {status} and data is {data}")
        self.verify_status(status, expected_status)
        return data

    def aes_decrypt(self,
                    aes_mode=Si91xAesType.SL_SI91X_AES_CBC,
                    enc_mode=Si91xAesOperation.SL_SI91X_AES_DECRYPT,
                    key_size=Si91xAesKeySize.SL_SI91X_AES_KEY_SIZE_128,
                    wrap_iv_mode=Si91xWrapIVMode.SL_SI91X_WRAP_IV_ECB_MODE,
                    key_type=Si91xKeyType.SL_SI91X_TRANSPARENT_KEY,
                    key="",
                    msg_len=16,
                    use_wrapped_keys=None,
                    pkcs_7_padding=None,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 5
                    ):
        line = f'crypto.aes.decrypt {aes_mode} {enc_mode} {key_size} {wrap_iv_mode} {key_type} {key} {msg_len}{f" -w {use_wrapped_keys}" if use_wrapped_keys is not None else ""}{f" -p {pkcs_7_padding}" if pkcs_7_padding is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def compute_sha_digest(self,
                           sha_type=Si91xSHA.SL_SI91X_SHA_512,
                           msg="",
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout: int = 5
                           ):
        self.logger.info(f"compute the digest for {msg} when sha-type selected {sha_type}")
        line = f'crypto.sha {sha_type} {msg}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def compute_hmac_digest(self,
                            hmac_mode=Si91xHMAC.SL_SI91X_HMAC_SHA_256,
                            key_type=Si91xKeyType.SL_SI91X_TRANSPARENT_KEY,
                            msg="",
                            key="",
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 5
                            ):
        address = self.allocate_memory(size=len(key) + 1)
        self.load_memory(address, size=len(key), write_content=key)
        self.logger.info(f"compute the digest for {msg} when hmac algo selected {hmac_mode}")
        line = f'crypto.hmac {hmac_mode} {key_type} {address} {msg}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.memory_free(address)
        self.verify_status(status, expected_status)
        return data

    def ecdh_point_operation(self,
                             ecdh_mode=Si91xECDH.SL_SI91X_ECDH_256,
                             ecdh_operation=Si91xECDHOperation.SL_SI91X_ECDH_ADD,
                             p1_add_subx=None,
                             p1_add_suby=None,
                             p1_add_subz=None,
                             p2_add_subx=None,
                             p2_add_suby=None,
                             p2_add_subz=None,
                             affinity=0,
                             reverse=0,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout: int = 10
                             ):
        if p1_add_subx is not None:
            address1 = self.allocate_memory(size=len(p1_add_subx) + 1)
            self.load_memory(address1, size=len(p1_add_subx), write_content=p1_add_subx)
        if p1_add_suby is not None:
            address2 = self.allocate_memory(size=len(p1_add_suby) + 1)
            self.load_memory(address2, size=len(p1_add_suby), write_content=p1_add_suby)
        if p1_add_subz is not None:
            address3 = self.allocate_memory(size=len(p1_add_subz) + 1)
            self.load_memory(address3, size=len(p1_add_subz), write_content=p1_add_subz)
        if p2_add_subx is not None:
            address4 = self.allocate_memory(size=len(p2_add_subx) + 1)
            self.load_memory(address4, size=len(p2_add_subx), write_content=p2_add_subx)
        if p2_add_suby is not None:
            address5 = self.allocate_memory(size=len(p2_add_suby) + 1)
            self.load_memory(address5, size=len(p2_add_suby), write_content=p2_add_suby)
        if p2_add_subz is not None:
            address6 = self.allocate_memory(size=len(p2_add_subz) + 1)
            self.load_memory(address6, size=len(p2_add_subz), write_content=p2_add_subz)

        line = f'crypto.ecdh {ecdh_mode} {ecdh_operation}{f" -a {address1}" if p1_add_subx else ""}{f" -b {address2}" if p1_add_suby else ""}{f" -c {address3}" if p1_add_subz else ""}{f" -d {address4}" if p2_add_subx else ""}{f" -e {address5}" if p2_add_suby else ""}{f" -f {address6}" if p2_add_subz else ""}{f" -g {affinity}" if affinity else ""}{f" -h {reverse}" if reverse else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if p1_add_subx is not None:
            self.memory_free(address1)
        if p1_add_suby is not None:
            self.memory_free(address2)
        if p1_add_subz is not None:
            self.memory_free(address3)
        if p2_add_subx is not None:
            self.memory_free(address4)
        if p2_add_suby is not None:
            self.memory_free(address5)
        if p2_add_subz is not None:
            self.memory_free(address6)
        self.verify_status(status, expected_status)
        return data

    @defaults("bluetooth")
    def ble_set_resp_notify_buffer(
            self,
            ble_remote_dev_address: str,
            buffer_mode: int,
            buffer_count: int,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=30,
            ):
        line = f"ble_set_resp_notify_buffer {mac_address_to_string(ble_remote_dev_address, ':')} {buffer_mode} {buffer_count}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
                )
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_indicate_value(
            self,
            ble_remote_dev_address: str,
            handle: int,
            data: int,
            data_length: int,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            data_address=None,
            timeout=30,
            async_timeout=30
        ):
        if data_address is None:
            address = self.allocate_memory(size=len(data))
            self.load_memory(address=address, size=len(data), write_content=data)
        else:
            address = data_address
        line = f"ble_indicate_value {mac_address_to_string(ble_remote_dev_address, ':')} {handle} {address} {data_length}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                line, timeout=timeout,
            )
        if data_address is None:
            self.memory_free(address)
        self.verify_status(status, expected_status)

    def sl_wifi_get_sta_tsf(self,
                            interface=None,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 40):
        """ Argument
            Wifi_interface interface=SL_WIFI_2_4GHZ_INTERFACE
        """
        line = f'sl_wifi_get_sta_tsf {f" -i {interface}" if interface else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_si91x_read_common_flash(self,
                                   read_address=None,
                                   length=None,
                                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                   timeout: int = 40):
        """ Argument
            uint32_t read_address=NWP_FLASH_ADDRESS
            size_t length=LENGTH_OF_BUFFER
        """
        self.logger.info("Reading data from common flash")
        line = f'sl_si91x_read_common_flash{f" -i {read_address}" if read_address else ""}{f" -j {length}" if length else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_si91x_bl_upgrade_firmware(self,
                                     firmware_image=0,
                                     fw_image_size=None,
                                     flags=None,
                                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                     timeout: int = 40):
        """ Argument
            uint8_t *firmware_image=firmware_image data address
            uint32_t fw_image_size=SI91X_CHUNK_SIZE
            uint8_t flags=SI91X_START_OF_FILE
        """
        self.logger.info("Init bl firmware upgrade")
        line = f'sl_si91x_bl_upgrade_firmware {firmware_image} {f" -i {fw_image_size}" if fw_image_size else ""} {f" -j {flags}" if flags is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_si91x_set_fast_fw_up(self,
                                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                timeout: int = 40):
        """ Argument
            None
        """
        self.logger.info("Set fast firmware up")
        line = f'sl_si91x_set_fast_fw_up'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def write_nwp_config(self,
                         code: int = None,
                         config_val: int = None,
                         timeout: int = 20,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK
                        ):
        """Set NWP configuration value"""
        # Build command line for writing NWP configuration with code and value parameters
        line = (f"write_nwp_config "
                f"{f' -a {code}' if code is not None else ''}"
                f"{f' -b {config_val}' if config_val is not None else ''}")

        # # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line, timeout=timeout)
        
        # Verify the status against the expected status
        self.verify_status(status, expected_status)

    def sl_wifi_reconfigure_ap(self,
                               interface=None,
                               beacon_stop=None,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface=SL_WIFI_2_4GHZ_INTERFACE
            uint8_t beacon_stop=0
        """
        self.logger.info("Reconfigure sl wifi AP")
        line = f'sl_wifi_reconfigure_ap{f" -i {interface}" if interface else ""}{f" -j {beacon_stop}" if beacon_stop is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_get_wireless_info(self,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 40):
        """ Argument
            None
        """
        self.logger.info(f"Get wireless info")
        line = f'sl_wifi_get_wireless_info '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_get_firmware_size(self,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 40):
        """ Argument
            None
        """
        self.logger.info("Get firmware size")
        line = f'sl_wifi_get_firmware_size '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_transceiver_up(self,
                               interface=None,
                               channel=None,
                               band=None,
                               bandwidth=None,
                               tx_power=None,
                               parameters_set=None,
                               retransmit_count=None,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface    =SL_WIFI_TRANSCEIVER_INTERFACE
            uint16_t channel                 =SL_WIFI_TRANSCEIVER_CHANNEL_NO
            sl_wifi_band_t band              =SL_WIFI_BAND_2_4GHZ, )
            sl_wifi_bandwidth_t bandwidth    =SL_WIFI_BANDWIDTH_20MHz
            uint8_t tx_power                 =SL_WIFI_TRANSCEIVER_TX_POWER
            uint8_t parameters_set           =1
            uint8_t retransmit_count=SL_WIFI_TRANSCEIVER_DEFAULT_RETRANSMIT_COUNT
        """
        self.logger.info("wifi transceiver Interface up")
        line = f'sl_wifi_transceiver_up{f" -i {interface}" if interface else ""}{f" -j {channel}" if channel is not None else ""}{f" -k {band}" if band is not None else ""}{f" -l {bandwidth}" if bandwidth is not None else ""}{f" -m {tx_power}" if tx_power is not None else ""}{f" -n {parameters_set}" if parameters_set is not None else ""}{f" -o {retransmit_count}" if retransmit_count is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_transceiver_set_channel(self,
                                        interface=None,
                                        channel=None,
                                        band=None,
                                        bandwidth=None,
                                        tx_power=None,
                                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                        timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface    =SL_WIFI_TRANSCEIVER_INTERFACE
            uint16_t channel                 =SL_WIFI_TRANSCEIVER_CHANNEL_NO
            sl_wifi_band_t band              =SL_WIFI_BAND_2_4GHZ, )
            sl_wifi_bandwidth_t bandwidth    =SL_WIFI_BANDWIDTH_20MHz
            uint8_t tx_power                 =SL_WIFI_TRANSCEIVER_TX_POWER
        """
        self.logger.info("wifi transceiver set channel")
        line = f'sl_wifi_transceiver_set_channel{f" -i {interface}" if interface else ""}{f" -j {channel}" if channel else ""}{f" -k {band}" if band is not None else ""}{f" -l {bandwidth}" if bandwidth is not None else ""}{f" -m {tx_power}" if tx_power is not None else ""} '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_set_transceiver_parameters(self,
                                           interface=None,
                                           parameters_set=None,
                                           retransmit_count=None,
                                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                           timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface    =SL_WIFI_TRANSCEIVER_INTERFACE
            uint8_t parameters_set           =1
            uint8_t retransmit_count=SL_WIFI_TRANSCEIVER_DEFAULT_RETRANSMIT_COUNT
        """
        self.logger.info("Set wifi transceiver parameters")
        line = f'sl_wifi_set_transceiver_parameters {f" -i {interface}" if interface else ""} {f" -j {parameters_set}" if parameters_set else ""} {f" -k {retransmit_count}" if retransmit_count else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_update_transceiver_peer_list(self,
                                             interface=None,
                                             peer_mac_address=None,
                                             peer_supported_rate_bitmap=None,
                                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                             timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface       =SL_WIFI_TRANSCEIVER_INTERFACE
            string peer_mac_address             ="8.8.8.8.8.8"
            uint32_t peer_supported_rate_bitmap =0
        """
        self.logger.info("Update transceiver peer list")
        line = f'sl_wifi_update_transceiver_peer_list {peer_mac_address}{f" -i {interface}" if interface else ""}{f" -j {peer_supported_rate_bitmap}" if peer_supported_rate_bitmap else ""} '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_set_transceiver_multicast_filter(self,
                                                 interface=None,
                                                 flags=None,
                                                 num_of_mcast_addr=None,
                                                 mac_addr=None,
                                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                 timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface       =SL_WIFI_TRANSCEIVER_INTERFACE
            uint8_t flags                       =0
            uint8_t num_of_mcast_addr           =1
            string mac_addr                     ="8.8.8.8.8.8"
        """
        self.logger.info("Update transceiver multicast filter")
        line = f'sl_wifi_set_transceiver_multicast_filter {mac_addr}{f" -i {interface}" if interface else ""}{f" -j {flags}" if flags else ""}{f" -k {num_of_mcast_addr}" if num_of_mcast_addr else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_send_transceiver_data(self,
                                      interface=None,
                                      flags=None,
                                      priority=None,
                                      rate=None,
                                      addr1_ra_addr=None,
                                      addr3_da_addr=None,
                                      addr4_sa_addr=None,
                                      payload=None,
                                      expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                      timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface       =SL_WIFI_TRANSCEIVER_INTERFACE
            uint8_t flags                       =TX_SAMPLE_PACKET_CTRL_FLAGS
            uint8_t priority                    =TX_SAMPLE_PACKET_PRIORITY_Q
            sl_wifi_data_rate_t rate            =TX_SAMPLE_PACKET_DATA_RATE
            char *addr1_ra_addr                  Receiver MAC address
            char *addr3_da_addr                  Destination MAC address
            char *addr4_sa_addr                  Source MAC address.
            char payload                         llc_header and payload data
        """
        self.logger.info("Transceiver send data")
        line = f'sl_wifi_send_transceiver_data {addr1_ra_addr} {addr3_da_addr} {addr4_sa_addr} {payload}{f" -i {interface}" if interface else ""}{f" -j {flags}" if flags else ""}{f" -k {priority}" if priority else ""}{f" -l {rate}" if rate else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_get_nwp_config(self,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 40):
        """ Argument
            NA
        """
        self.logger.info("Get nwp config")
        line = f'sl_wifi_get_nwp_config '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_flush_transceiver_data(self,
                                       interface=None,
                                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                       timeout: int = 40):
        """ Argument
            sl_wifi_interface_t interface       =SL_WIFI_TRANSCEIVER_INTERFACE
        """
        self.logger.info("Flush transceiver data")
        line = f'sl_wifi_flush_transceiver_data {f" -i {interface}" if interface else ""} '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_wifi_set_transceiver_callback(self,
                                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                         timeout: int = 40):
        """ Argument
            NA
        """
        self.logger.info("Set transceiver callback")
        line = f'sl_wifi_set_transceiver_callback '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def sl_si91x_fwup_abort(self,
                            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                            timeout: int = 40):
        """ Argument
            NA
        """
        self.logger.info("Firmware upgrade abort")
        line = f'wifi.sl_si91x_fwup_abort '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def set_feature_frame_request(self,
                                  pll_mode=None,
                                  rf_type=None,
                                  wireless_mode=None,
                                  enable_ppp=None,
                                  afe_type=None,
                                  features_enable=None,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 40):
        """ Argument
            uint32_t pll_mode        =0
            uint32_t rf_type         =1
            uint32_t wireless_mode   =0
            uint32_t enable_ppp      =0
            uint32_t afe_type        =1
            uint32_t features_enable =43
        """
        self.logger.info("Set feature frame request")
        line = f'set_feature_frame_request{f" -i {pll_mode}" if pll_mode is not None else ""}{f" -j {rf_type}" if rf_type is not None else ""}{f" -k {wireless_mode}" if wireless_mode is not None else ""}{f" -l {enable_ppp}" if enable_ppp is not None else ""}{f" -m {afe_type}" if afe_type is not None else ""}{f" -n {features_enable}" if features_enable is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()

    def m4_ta_secure_handshake(self,
                               sub_cmd_type=5,
                               xtal_enable=1,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 40):
        line = f"m4_ta_secure_handshake {sub_cmd_type} {xtal_enable} "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def m4_powersave(self,
                     expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                     timeout: int = 40):
        line = f"m4_powersave "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_m4_powersave(self,
                         time=30,
                         mode=7,
                         rams_in_use=768,
                         rams_retention_during_sleep=1,
                         sleepType=0,
                         lf_clk_mode=0,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout: int = 40):
        line = f"set_m4_powersave {time} {mode} {rams_in_use} {rams_retention_during_sleep} {sleepType} {lf_clk_mode} "
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def m4_power_manager(self,
                         sleep_time=None,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         issue_in_thread=0,
                         timeout: int = 40):
        line = f"m4_power_manager -t {sleep_time}"
        if self.test_agent_thread_enabled and issue_in_thread:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=40,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def m4_power_manager_deep_sleep(self,
                                    state=7,
                                    sleep_time=None,
                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout: int = 40):
        line = f"m4_power_manager_deep_sleep {state} -t {sleep_time}"
        result = self.bus.write_line_and_expect(line, "Ready", timeout)

        self.logger.info(f"result :{result}")
        assert "Ready" in result.decode("utf-8"), "Ready print not found in the response"

    def set_filter_broadcast(self,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout: int = 5):
        line = f"wifi.filter_broadcast"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    # Configure broadcast/multicast groupcast filtering
    def set_groupcast_filter_config(self,
                                    enable_bcast_filter: int = None,
                                    enable_mcast_filter: int = None,
                                    filter_mode: int = None,
                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout: int = 10,
                                    ):
        """Configure broadcast/multicast filtering enables and filter mode"""

        # Build command line with conditional optional parameters
        line = (f"wifi.set_groupcast_filter_config "
                f"{f' -b {enable_bcast_filter}' if enable_bcast_filter is not None else ''}"
                f"{f' -m {enable_mcast_filter}' if enable_mcast_filter is not None else ''}"
                f"{f' -f {filter_mode}' if filter_mode is not None else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def set_beacon_drop_threshold(self,
                                  interface: str = None,
                                  beacon_drop_threshold: int = None,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 10,
                                  ):
        """Set the beacon drop threshold used for power save"""

        # Build command line with conditional optional parameters
        line = (f"wifi.set_beacon_drop_threshold "
                f"{f' -i {interface}' if interface else ''}"
                f"{f' -t {beacon_drop_threshold}' if beacon_drop_threshold is not None else ''}")

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def allowlist_mcast_add_ip(self,
                               multicast_ip: str,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 10,
                               ):
        """Add an IP multicast address to the NWP allowlist and return the handle"""

        # Build command line for allowlist add
        line = f"wifi.allowlist_mcast_add_ip {multicast_ip}"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def allowlist_mcast_remove_ip(self,
                                  handle: int,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 10,
                                  ):
        """Remove one multicast allowlist entry by handle"""

        # Build command line for allowlist remove by handle
        line = f"wifi.allowlist_mcast_remove_ip {handle}"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def allowlist_mcast_remove_all(self,
                                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                   timeout: int = 10,
                                   ):
        """Clear the multicast IP allowlist"""

        # Build command line for allowlist clear
        line = f"wifi.allowlist_mcast_remove_all"

        # Issue command in thread or directly
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        # Verify the command status
        self.verify_status(status, expected_status)

    def get_saved_firmware_status(self,
                                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                  timeout: int = 5):
        line = f"get_saved_firmware_status"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_twt(self,
                wake_duration=None,
                wake_duration_tol=None,
                wake_int_exp=None,
                wake_int_exp_tol=None,
                wake_int_mantissa=None,
                wake_int_mantissa_tol=None,
                implicit_twt=None,
                un_announced_twt=None,
                triggered_twt=None,
                negotiation_type=None,
                twt_channel=None,
                twt_protection=None,
                twt_flow_id=None,
                restrict_tx_outside_tsp=None,
                twt_retry_limit=None,
                twt_retry_interval=None,
                req_type=None,
                twt_enable=None,
                wake_duration_unit=None,
                expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                timeout: int = 10):
        self.logger.info(
            f"Sending TWT command with parameters:: a:wake_duration->{wake_duration}, b:wake_duration_tol->{wake_duration_tol}, c:wake_int_exp->{wake_int_exp}, d:wake_int_exp_tol->{wake_int_exp_tol}, e:wake_int_mantissa->{wake_int_mantissa}, f:wake_int_mantissa_tol->{wake_int_mantissa_tol}"
            f", g:implicit_twt->{implicit_twt}, h:un_announced_twt->{un_announced_twt}, i:triggered_twt->{triggered_twt}, j:negotiation_type->{negotiation_type}, k:twt_channel->{twt_channel}, l:twt_protection->{twt_protection}, m:twt_flow_id->{twt_flow_id}, n:restrict_tx_outside_tsp->{restrict_tx_outside_tsp}, o:twt_retry_limit->{twt_retry_limit}, p:twt_retry_interval->{twt_retry_interval}, q:req_type->{req_type}, r:twt_enable->{twt_enable}, s:wake_duration_unit->{wake_duration_unit}")
        line = (
            f'wifi.enable_target_wake_time{f" -a {wake_duration}" if wake_duration else ""}'
            f'{f" -b {wake_duration_tol}" if wake_duration_tol else ""}'
            f'{f" -c {wake_int_exp}" if wake_int_exp else ""}'
            f'{f" -d {wake_int_exp_tol}" if wake_int_exp_tol else ""}'
            f'{f" -e {wake_int_mantissa}" if wake_int_mantissa else ""}'
            f'{f" -f {wake_int_mantissa_tol}" if wake_int_mantissa_tol else ""}'
            f'{f" -g {implicit_twt}" if implicit_twt else ""}'
            f'{f" -h {un_announced_twt}" if un_announced_twt else ""}'
            f'{f" -i {triggered_twt}" if triggered_twt else ""}'
            f'{f" -j {negotiation_type}" if negotiation_type else ""}'
            f'{f" -k {twt_channel}" if twt_channel else ""}'
            f'{f" -l {twt_protection}" if twt_protection else ""}'
            f'{f" -m {twt_flow_id}" if twt_flow_id else ""}'
            f'{f" -n {restrict_tx_outside_tsp}" if restrict_tx_outside_tsp else ""}'
            f'{f" -o {twt_retry_limit}" if twt_retry_limit else ""}'
            f'{f" -p {twt_retry_interval}" if twt_retry_interval else ""}'
            f'{f" -q {req_type}" if req_type else ""}'
            f'{f" -r {twt_enable}" if twt_enable else ""}'
            f'{f" -s {wake_duration_unit}" if wake_duration_unit else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=10,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.WIFI_TWT_RESPONSE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_UNSOLICITED_SESSION_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_AP_REJECTED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_OUT_OF_TOLERANCE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_RESPONSE_NOT_MATCHED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_UNSUPPORTED_RESPONSE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_TEARDOWN_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_AP_TEARDOWN_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_FAIL_MAX_RETRIES_REACHED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_DUE_TO_ROAMING_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_DUE_TO_DISCONNECT_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_NO_AP_SUPPORT_EVENT,
                                                                           AsyncIdentifiers.WIFI_RESCHEDULE_TWT_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INFO_FRAME_EXCHANGE_FAILED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_EVENTS_END],
                                                        event_expected="$>")
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if "TWT Setup Failed." not in data.decode():
            self.enabled_twt = True
        return data.decode().strip("$>\r\n")

    def twt_auto_config(self,
                        twt_enable=None,
                        average_tx_throughput=None,
                        tx_latency=None,
                        rx_latency=None,
                        device_average_throughput=None,
                        estimated_extra_wake_duration_percent=None,
                        twt_tolerable_deviation=None,
                        default_wake_interval_ms=None,
                        default_minimum_wake_duration_ms=None,
                        beacon_wake_up_count_after_sp=None,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout: int = 10):
        self.logger.info(
            f"Sending twt auto selection command with parameters::  e:twt_enable->{twt_enable}, a:average_tx_throughput->{average_tx_throughput}, t:tx_latency->{tx_latency}, r:rx_latency->{rx_latency}, d:device_average_throughput->{device_average_throughput}, w:estimated_extra_wake_duration_percent->{estimated_extra_wake_duration_percent}, s:twt_tolerable_deviation->{twt_tolerable_deviation}, m:default_wake_interval_ms->{default_wake_interval_ms}, c:default_minimum_wake_duration_ms->{default_minimum_wake_duration_ms}")
        line = (
            f'wifi.twt_auto_selection{f" -e {twt_enable}"}'
            f'{f" -a {average_tx_throughput}" if average_tx_throughput else ""}'
            f'{f" -t {tx_latency}" if tx_latency else ""}'
            f'{f" -r {rx_latency}" if rx_latency else ""}'
            f'{f" -d {device_average_throughput}" if device_average_throughput else ""}'
            f'{f" -w {estimated_extra_wake_duration_percent}" if estimated_extra_wake_duration_percent else ""}'
            f'{f" -s {twt_tolerable_deviation}" if twt_tolerable_deviation else ""}'
            f'{f" -m {default_wake_interval_ms}" if default_wake_interval_ms else ""}'
            f'{f" -c {default_minimum_wake_duration_ms}" if default_minimum_wake_duration_ms else ""}'
            f'{f" -b {beacon_wake_up_count_after_sp}" if beacon_wake_up_count_after_sp else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=10,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.WIFI_TWT_RESPONSE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_UNSOLICITED_SESSION_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_AP_REJECTED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_OUT_OF_TOLERANCE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_RESPONSE_NOT_MATCHED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_UNSUPPORTED_RESPONSE_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_TEARDOWN_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_AP_TEARDOWN_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_FAIL_MAX_RETRIES_REACHED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_DUE_TO_ROAMING_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_DUE_TO_DISCONNECT_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INACTIVE_NO_AP_SUPPORT_EVENT,
                                                                           AsyncIdentifiers.WIFI_RESCHEDULE_TWT_SUCCESS_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_INFO_FRAME_EXCHANGE_FAILED_EVENT,
                                                                           AsyncIdentifiers.WIFI_TWT_EVENTS_END],
                                                        event_expected="$>"
                                                        )
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if "TWT Setup Failed." not in data.decode():
            self.enable_auto_twt = True if twt_enable == 1 else False
        return data.decode().strip("$>\r\n")

    def disable_twt(self,
                    twt_enable=None,
                    twt_flow_id=None,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 5):
        self.logger.info(f"Disabling target wake time")
        line = f'wifi.disable_target_wake_time{f" -t {twt_enable}" if twt_enable is not None else ""} {f" -f {twt_flow_id}" if twt_flow_id is not None else ""}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.enabled_twt = False
        self.verify_status(status, expected_status)

    def twt_reschedule(self,
                       flow_id=0,
                       twt_reschedule_action=Si91xTWTRescheduleParams.SL_WIFI_SUSPEND_INDEFINITELY,
                       suspend_duration=12000,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout: int = 5):
        self.logger.info(
            f"Sending twt reschedule command with parameters flow_id->{flow_id}, twt_reschedule->{twt_reschedule_action} and suspend_duration->{suspend_duration}")
        line = f"wifi.twt_reschedule {flow_id} {twt_reschedule_action} {suspend_duration}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_socket_config(self,
                          total_sockets=1,
                          total_tcp_sockets=1,
                          total_udp_sockets=0,
                          tcp_tx_only_sockets=0,
                          tcp_rx_only_sockets=1,
                          udp_tx_only_sockets=0,
                          udp_rx_only_sockets=0,
                          tcp_rx_high_performance_sockets=1,
                          tcp_rx_window_size_cap=44,
                          tcp_rx_window_div_factor=44,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout: int = 10
                          ):
        line = f'set_socket_config {total_sockets} {total_tcp_sockets} {total_udp_sockets} {tcp_tx_only_sockets} {tcp_rx_only_sockets} {udp_tx_only_sockets} {udp_rx_only_sockets} {tcp_rx_high_performance_sockets} {tcp_rx_window_size_cap} {tcp_rx_window_div_factor}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def set_remote_terminate_callback(self,
                                      expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                      timeout: int = 10
                                      ):
        line = f'set_remote_terminate_callback'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def config_socket_metadata(self,
                               socket_metadata=0,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 10
                               ):
        line = f'config_socket_metadata {socket_metadata}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def sl_si91x_enable_radio(self,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                              timeout: int = 10
                              ):
        line = f'wifi.sl_si91x_enable_radio'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_wifi_operational_stats(self,
                                   interface=None,
                                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                   timeout: int = 10,
                                   ):
        line = f'wifi.get_operational_statistics{f" -i {interface}" if interface is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        operating_mode = re.findall("Operating mode: (\d+)", data.decode())[0]
        dtim_period = re.findall("Dtim period: (\d+)", data.decode())[0]
        ideal_beacon_info = re.findall("Ideal beacon info: (\d+)", data.decode())[0]
        busy_beacon_info = re.findall("Busy beacon info: (\d+)", data.decode())[0]
        busy_interval = re.findall("Busy interval: (\d+)", data.decode())[0]
        self.verify_status(status, expected_status)
        return operating_mode, dtim_period, ideal_beacon_info, busy_beacon_info, busy_interval

    def set_duty_cycle(self,
                       duty_cycle=0,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout: int = 10
                       ):
        line = f"set_ble_duty_cycle {duty_cycle}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.BLE, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_sockets_info(
            self,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=3,
            ):
        line = f"bsd_socket.get_socket_info"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            socket_info = []
            no_of_sockets = int(data.split(b"\n")[0].split(b":")[1])
            self.logger.info(
                f"------socket info ->  Number of sockets opened in DUT {no_of_sockets}"
                )
            if no_of_sockets:
                for item in range(1, (1 + no_of_sockets)):
                    socket_no = int(
                        data.split(b'\n')[1].split(b',')[0].split(b":")[1]
                        )
                    socket_id = int(data.split(b'\n')[1].split(b',')[1].split(b":")[1])
                    socket_type = int(data.split(b'\n')[1].split(b',')[2].split(b":")[1])
                    source_port = int(data.split(b'\n')[1].split(b',')[3].split(b":")[1])
                    destination_port = int(data.split(b'\n')[1].split(b',')[4].split(b":")[1])
                    server_ip = re.findall(b'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', data)[0]
                    if socket_type == 0:
                        socket_type_str = "TCP"
                    else:
                        socket_type_str = "UDP"
                    self.logger.info(
                        f"socket number {item} details-----> socket id:{socket_id}, socket type:{socket_type_str}, "
                        f"source port:{source_port}, destination port:{destination_port}, server_ip:{server_ip}"
                        )
                    socket_list = tuple(
                        [
                            socket_id,
                            socket_type,
                            source_port,
                            destination_port,
                            server_ip.decode(),
                            ]
                        )
                    socket_info.append(socket_list)
            self.logger.info(socket_info)
        return no_of_sockets, socket_info

    def sl_si91x_disable_radio(self,
                               expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                               timeout: int = 10
                               ):
        line = f'wifi.sl_si91x_disable_radio'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def rsi_bt_deinit(self,
                      expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                      timeout: int = 10
                      ):
        line = f'bt_deinit'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.BLE, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_enable(self,
                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                   timeout: int = 10):
        line = f'ble_enable'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def ble_disable(self,
                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                    timeout: int = 10):
        line = f'ble_disable'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, timeout=timeout, protocol=Protocol.BLE,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def mdns_init(self,
                  ip_version=Si91xMdnsParams.IPV4,
                  protocol=Si91xMdnsParams.PROTO_UDP,
                  host_name="wiseconnect.local",
                  expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                  timeout: int = 5):
        line = (
            f'mdns.init{f" -p {protocol}" if protocol else ""}'
            f'{f" -t {ip_version}" if ip_version else ""}'
            f'{f" -h {host_name}" if host_name else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def mdns_add_interface(self,
                           interface="client",
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout: int = 40):
        line = (
            f'mdns.add_interface{f" -i {interface}" if interface else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,

                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def mdns_register_service(self,
                              interface="client",
                              service_port=Si91xMdnsParams.SERVICE_PORT,
                              ttl=Si91xMdnsParams.TTL,
                              expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                              timeout: int = 40):
        line = (
            f'mdns.register_service{f" -i {interface}" if interface else ""}'
            f'{f" -p {service_port}" if service_port else ""}'
            f'{f" -t {ttl}" if ttl else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_ble_rssi_value(self,
                           device_address: str = None,
                           expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                           timeout: int = 10,
                           ):
        self.logger.info(f"RSSI value of the device {device_address}")
        line = f'ble_get_rssi_value {device_address}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        rssi = re.findall("rssi_value : (-?\d+)", data.decode())[0]
        self.verify_status(status, expected_status)
        return rssi

    def async_sdk_socket(self, domain: str, stream_type: str, protocol: str, expected_status=SLStatus.SL_STATUS_OK,
                         timeout: int = 10):
        """ Arguments
            domain = ["AF_INET"/"AF_INET6"]
            type = ["SOCK_STREAM"/"SOCK_DGRAM"]
            protocol = ["IPPROTO_TCP"/"IPPROTO_UDP"]
        """
        self.logger.info(f"\n *** Create {protocol} BSD Socket  *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"socket_async_create {domain} {stream_type} {protocol}",
                                                        protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'socket_async_create {domain} {stream_type} {protocol}', timeout)

        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id{socket_id}")
        return int(socket_id)

    def mdns_deinit(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=5):
        self.logger.info("\n ** Deinitialize MDNS **\n")
        line = f'mdns.deinit'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def http_server_init(
            self,
            http_port: int = None,
            handlers_count: int = None,
            url1: str = None,
            url2: str = None,
            url3: str = None,
            url4: str = None,
            url5: str = None,
            url6: str = None,
            send_large_data: int = None,
            data: str = None,
            data_address=None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        """
        Arguments:
        http_port:: expected input is 80 or 443. It selects 80 by default in the test agent when not provided
        handlers_count:: expected input is number in integer.  It selects 4 by default in the test agent when not provided
        url1:: expected input is valid url. It selects url /test by default in the test agent when not provided
        url2:: expected input is valid url. It selects url /data by default in the test agent when not provided
        url3:: expected input is valid url. It selects url /cert1.pem by default in the test agent when not provided
        url4:: expected input is valid url. It selects url /cert2.pem by default in the test agent when not provided
        url5:: expected input is valid url. It selects url /login by default in the test agent when not provided
        url6:: expected input is valid url. It selects url /connect by default in the test agent when not provided
        send_large_data:: expected input is 0 or 1. It selects 0 by default in the test agent when not provided
        data:: custom webpage w.r.t URL. It selects default webpage by default in the test agent when not provided w.r.t URL. This needs to be provided when send_large_data is 1
        """
        self.logger.info(f"Sending http server CLI init command with following parameters:\n"
                         f'{f",p::http_port:{http_port}" if http_port is not None else ""}'
                         f'{f",h::handlers_count:{handlers_count}" if handlers_count is not None else ""}'
                         f'{f",u::url1:{url1}" if url1 is not None else ""}'
                         f'{f",v::url2:{url2}" if url2 is not None else ""}'
                         f'{f",b::url3:{url3}" if url3 is not None else ""}'
                         f'{f",c::url4:{url4}" if url4 is not None else ""}'
                         f'{f",l::url5:{url5}" if url5 is not None else ""}'
                         f'{f",o::url6:{url6}" if url6 is not None else ""}'
                         f'{f",d::send_large_data:{send_large_data}" if send_large_data is not None else ""}'
                         f'{f",a::data:{data}" if data is not None else ""}'
                         )

        if send_large_data:
            if data_address is None:
                address = self.allocate_memory(size=len(data) + 1)
                self.dut_http_server_webpage_address = address
                self.load_memory(address=address, size=len(data), write_content=data, timeout=1)

            else:
                address = data_address

        line = (
            f'http_server.init{f" -p {http_port}" if http_port is not None else ""}{f" -h {handlers_count}" if handlers_count is not None else ""}{f" -u {url1}" if url1 is not None else ""}{f" -v {url2}" if url2 is not None else ""}{f" -b {url3}" if url3 is not None else ""}{f" -c {url4}" if url4 is not None else ""}{f" -l {url5}" if url5 is not None else ""}{f" -o {url6}" if url6 is not None else ""}{f" -d {send_large_data}" if send_large_data is not None else ""}{f" -a {address}" if data is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if not (status == expected_status):
            if self.dut_http_server_webpage_address:
                if data_address is None:
                    self.memory_free(self.dut_http_server_webpage_address)
                    self.dut_http_server_webpage_address = 0
        self.verify_status(status, expected_status)

    def http_server_start(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=5):
        self.logger.info("\n ** Start HTTP server **\n")
        line = f'http_server.start'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if not (status == expected_status):
            if self.dut_http_server_webpage_address:
                self.memory_free(self.dut_http_server_webpage_address)
                self.dut_http_server_webpage_address = 0
        self.verify_status(status, expected_status)

    def http_server_stop(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=5):
        self.logger.info("\n ** Stop HTTP server **\n")
        line = f'http_server.stop'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if not (status == expected_status):
            if self.dut_http_server_webpage_address:
                self.memory_free(self.dut_http_server_webpage_address)
                self.dut_http_server_webpage_address = 0
        self.verify_status(status, expected_status)

    def http_server_deinit(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=5):
        self.logger.info("\n ** Deinitialize HTTP server **\n")
        line = f'http_server.deinit'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        if self.dut_http_server_webpage_address:
            self.memory_free(self.dut_http_server_webpage_address)
            self.dut_http_server_webpage_address = 0
        self.verify_status(status, expected_status)

    def http_server_get_credentials_from_webpage(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=5):
        self.logger.info("\n ** Get credentials from webpage **\n")
        line = f'http_server.get_credentials'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data

    def set_rts_threshold(
            self,
            config_rts_threshold: int = None,
            rts_threshold: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        """
        Arguments:
        config_rts_threshold:: expected input is o or 1. It selects 1 by default in the test agent when not provided
        rts_threshold:: expected input range is from 100 to 2346. It selects 2346 by default in the test agent when not provided
        """
        self.logger.info(f"Sending set_rts_threshold CLI command with following parameters:\n"
                         f'{f",e::config_rts_threshold:{config_rts_threshold}" if config_rts_threshold is not None else ""}'
                         f'{f",r::rts_threshold:{rts_threshold}" if rts_threshold is not None else ""}')

        line = f'wifi.set_rts_threshold{f" -e {config_rts_threshold}" if config_rts_threshold is not None else ""}{f" -r {rts_threshold}" if rts_threshold is not None else ""}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI,
                                                        async_identifiers=[], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    def set_ble_address(self, ble_address: str, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 5):
        list_mac_address = ble_address.split(":")
        list_mac_address = list_mac_address[::-1]
        ble_address = ':'.join(list_mac_address)
        self.logger.info(f"Setting BLE address to {ble_address}")
        line = f"ble_set_address {ble_address}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.BLE, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_resolvelist(self,
                        process_type: int = 1,
                        remote_addr_type: int = 0,
                        ble_device_address: str = None,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout: int = 5):
        line = f"ble_resolvelist {process_type} {remote_addr_type} {ble_device_address}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.BLE, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def ble_set_address_resolution_enable(self,
                                          address_resolution_enable: int = 1,
                                          address_resolution_timeout: int = 10,
                                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                          timeout: int = 5):
        line = f"set_address_resolution_enable {address_resolution_enable} {address_resolution_timeout}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.BLE, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_start_encrypt(self,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=10,
                          ):
        line = f"ble_start_encrypt"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    @defaults("bluetooth")
    def ble_ltk_req_reply(self,
                          ble_remote_dev_address: str,
                          reply_type,
                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                          timeout=10,
                          ):
        line = f"ble_ltk_req_reply {mac_address_to_string(ble_remote_dev_address, ':')} {reply_type}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    @defaults("wifi")
    def frequency_offset(self, freq_khz: int, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 5):
        """ Arguments: freq_khz - Frequency offset in KHZ """
        self.logger.info(f"*** Initiating frequency_offset Cli command with Arguments: freq_khz:{freq_khz}")
        line = f"frequency_offset {freq_khz}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_antenna(
            self,
            interface: str = Si91xInterface.SL_WIFI_CLIENT_2_4GHZ_INTERFACE,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            Interface - wifi interface
        """
        self.logger.info(f"\n *** Initiating get_antenna Cli command with Arguments: interface:{interface} *** \n")
        line = f"wifi.get_antenna {interface}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("wifi")
    def ota_fw_upgrade(self,
                       server: str,
                       server_port: int,
                       chunk_number: int,
                       recv_timeout: int,
                       tcp_retry_count: int,
                       ip_type: int,
                       asynchronous: bool = False,
                       expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                       timeout=30,
                       ):
        """Arguments:
            server          -  OTAF server IP address
            server_port     -  OTAF server port number
            chunk_number    -  Firmware content request chunk number
            recv_timeout    -  TCP receive packet timeout
            tcp_retry_count -  TCP retransmissions count
            asynchronous    -  OTAF upgrade done aynchronously when this is set, else synchronous upgrade
        """
        self.logger.info(
            f"********** Upgrading si91x_ota_fw with Arguments: server:{server}, server_port:{server_port}, chunk_number:{chunk_number}, recv_timeout:{recv_timeout}, ip_type:{ip_type}, asynchronous:{asynchronous}  **********")
        line = f"ota_fw_upgrade {server} {server_port} {chunk_number} {recv_timeout} {tcp_retry_count} {ip_type}"
        if asynchronous:
            line += f" -m asynchronous"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[],
                                                        async_timeout=240)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def wifi_set_listen_interval(
            self,
            interface: str = None,
            listen_interval: int = 1000,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            Interface - wifi interface
            listen_interval -  sl_wifi_listen_interval_t object
        """
        self.logger.info(
            f"\n *** Initiating wifi_set_listen_interval Cli command with Arguments: interface:{interface}, listen_interval:{listen_interval} *** \n")
        line = f"wifi.sl_wifi_set_listen_interval {interface} {listen_interval}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def start_p2p_discovery(
            self,
            interface: str = None,
            group_owner_intent: int = None,
            channel: int = None,
            device_name: str = None,
            ssid_suffix: str = None,
            credential_id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            Interface - wifi interface
            group_owner_intent -  Group owner intent of sl_wifi_p2p_configuration_t
            channel      - channel of sl_wifi_p2p_configuration_t
            device_name  - Device name of sl_wifi_p2p_configuration_t
            ssid_suffix  - SSID suffix of sl_wifi_p2p_configuration_t
            credential_id - credential_id of uint32
        """
        self.logger.info(
            f"\n *** Initiating start_p2p_discovery Cli command with Arguments: interface:{interface}, group_owner_intent:{group_owner_intent}, channel:{channel}, device_name:{device_name}, ssid)suffix:{ssid_suffix} credential_id:{credential_id} *** \n")
        line = f"wifi.start_p2p_discovery {interface} {group_owner_intent} {channel} {device_name} {ssid_suffix} {credential_id}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def p2p_connect(
            self,
            interface: str = None,
            group_owner_intent: int = None,
            channel: int = None,
            device_name: str = None,
            ssid_suffix: str = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
           Interface - wifi interface
           group_owner_intent -  Group owner intent of sl_wifi_p2p_configuration_t
           channel      - channel of sl_wifi_p2p_configuration_t
           device_name  - Device name of sl_wifi_p2p_configuration_t
           ssid_suffix  - SSID suffix of sl_wifi_p2p_configuration_t
        """

        self.logger.info(
            f"\n *** Initiating p2p_connect Cli command with Arguments: interface:{interface}, group_owner_intent:{group_owner_intent}, channel:{channel}, device_name:{device_name}, ssid)suffix:{ssid_suffix} *** \n")
        line = f"wifi.p2p_connect {interface} {group_owner_intent} {channel} {device_name} {ssid_suffix}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def get_profile(
            self,
            interface: str = None,
            id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            Interface - sl_net interface
            id -  Profile storage index of sl_net_profile_id_t
        """
        self.logger.info(
            f"\n *** Initiating get_profile Cli command with Arguments: interface:{interface}, id:{id} *** \n")
        line = f"wifi.get_profile {interface} {id}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def nat_enable(
            self,
            interface: str = "client",
            tcp_session_timeout: int = 60,
            non_tcp_session_timeout: int = 60,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,):
        """Arguments:
            Interface - sl_net interface
            tcp_session_timeout - TCP session timeout in seconds
            non_tcp_session_timeout - Non TCP session timeout in seconds
        """
        self.logger.info(
            f"\n *** Initiating nat_enable Cli command with Arguments: interface:{interface}, tcp_session_timeout:{tcp_session_timeout}, non_tcp_session_timeout:{non_tcp_session_timeout} *** \n")
        line = f'wifi.nat_enable{f" -i {interface}" if interface else ""}{f" -t {tcp_session_timeout}" if tcp_session_timeout else ""}{f" -n {non_tcp_session_timeout}" if non_tcp_session_timeout else ""} '
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def nat_disable(
            self,
            interface: str = "client",
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,):
        """Arguments:
            Interface - sl_net interface
        """
        self.logger.info(
            f"\n *** Initiating nat_disable Cli command with Arguments: interface:{interface} *** \n")
        line = f'wifi.nat_disable{f" -i {interface}" if interface else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def delete_profile(
            self,
            interface: str = None,
            id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            Interface - sl_net interface
            id -  Profile storage index of sl_net_profile_id_t
        """
        self.logger.info(
            f"\n *** Initiating delete_profile Cli command with Arguments: interface:{interface}, id:{id}, *** \n")
        line = f"wifi.delete_profile {interface} {id}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def sl_net_delete_credential(
            self,
            cred_id: int = None,
            cred_type: int = None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
    ):
        """
        Delete a stored network credential using the net.delete_credential command.

        Args:
            cred_id: Credential ID (default: SL_NET_DEFAULT_WIFI_CLIENT_CREDENTIAL_ID)
            cred_type: Credential type, e.g. SL_NET_WIFI_PSK (default: SL_NET_WIFI_PSK)
            expected_status: Expected status code
            timeout: Command timeout in seconds
        """
        line = (
            f'net.delete_credential'
            f'{f" -a {cred_id}" if cred_id is not None else ""}'
            f'{f" -b {cred_type}" if cred_type is not None else ""}'
        )

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [],
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(line, timeout=timeout)

        self.verify_status(status, expected_status)

    def bsdSocketSendToAsync(
            self,
            socket_fd: int,
            data: str,
            ip_addr: str,
            ip_len: int,
            port: int,
            flags: int,
            higher_data_len=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
          Socket_fd     - Socket ID
          data          - data send to buffer
          ip_addr       - ip_address
          ip_len        - ip_len
          port          - port number like 5001
          flags         - Controls the transmission of the data
        higher_data_len - length of data to send to buffer
        """

        self.logger.info(
            f"\n *** Initiating bsd_socket.send_to_async Cli command with Arguments: socket_fd:{socket_fd}, flags:{flags},  higher_data_len:{higher_data_len}, data:{data}, ip_addr:{ip_addr}, ip_len:{ip_len}, port:{port} *** \n")
        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        line = (
            f'bsd_socket.send_to_async {socket_fd} {flags} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""} {ip_addr} {ip_len} {port}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                async_identifiers=[AsyncIdentifiers.SOCKET_SEND],
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)
        if higher_data_len:
            self.memory_free(address)

    def bsdSocketSendLargedata(
            self,
            socket_fd: int,
            data: str,
            flags: int,
            higher_data_len=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
              Socket_fd     - Socket ID
              data          - data send to buffer
              flags         - Controls the transmission of the data
            higher_data_len - length of data to send to buffer
            """
        self.logger.info(
            f"\n *** Initiating bsd_socket.send_large_data Cli command with Arguments: socket_fd:{socket_fd}, flags:{flags},  higher_data_len:{higher_data_len}, data:{data} *** \n")

        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        line = (
            f'bsd_socket.send_large_data {socket_fd} {flags} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)
        if higher_data_len:
            self.memory_free(address)

    @defaults("iop_sockets")
    def bsdSocketAcceptAsync(
            self, socket_fd: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 30
            ):
        """Arguments
           socket_fd   - socket file descriptor
        """
        line = f"bsd_socket.accept_async {socket_fd}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI,
                                                        async_identifiers=[AsyncIdentifiers.SOCKET_ACCEPT],
                                                        async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)

    @defaults("iop_sockets")
    def bsdSocketConnectsi91xsoc(self, socket_fd: int, server_ip: str, ip_len: int, server_port: int,
                                 expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10):
        """Arguments:
            socket_fd   - socket file descriptor
            server_ip   - ip_address
              ip_len    - ip_len
          server_port   - port num ex:5001
        """
        self.logger.info(
            f"\n *** Initiate BSD socket connect_si91x_soc for server_ip: {server_ip}, server_port: {server_port} *** \n")
        line = f"bsd_socket.connect_si91x_soc {socket_fd} {server_ip} {ip_len} {server_port}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)
        return data

    @defaults("iop_sockets")
    def bsdSocketRecvfromsi91x(
            self,
            socket_fd: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
              Socket_fd     - Socket ID
            """
        self.logger.info(
            f"\n *** Initiating bsd_socket.receive_from_si91x Cli command with Arguments: socket_fd:{socket_fd} *** \n")
        line = (
            f'bsd_socket.receive_from_si91x {socket_fd}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)

    @defaults("wifi")
    def fwup_load_si91x(self,
                        content: str,
                        length: int,
                        expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                        timeout=30,
                        ):
        """Arguments:
          content : Pointer to the firmware file content
          length  : Length of the content
        """
        self.logger.info(
            f"********* Intiating  fwup_load_si91x Cli command with Arguments: content:{content}, length:{length} **********")
        line = f"fwup_load_si91x {content} {length}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[],
                                                        async_timeout=240)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

    @defaults("wifi")
    def fwup_start_si91x(self,
                         rps_header: str,
                         expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                         timeout=30,
                         ):
        """Arguments:
          rps_header : Pointer to the RPS header content.
        """
        self.logger.info(
            f"********* Intiating  fwup_start_si91x Cli command with Arguments: rps_header:{rps_header} **********")
        line = f"fwup_start_si91x {rps_header}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[],
                                                        async_timeout=240)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    @defaults("wifi")
    def fwup_si91x(self,
                   type: int,
                   content: str,
                   length: int,
                   expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                   timeout=30,
                   ):
        """Arguments:
          type    : Firmware upgrade chunk type
          content : Firmware content
          length  : Length of the content
        """
        self.logger.info(
            f"********* Intiating  fwup_si91x Cli command with Arguments: type:{type}, content:{content} length:{length}**********")
        line = f"fwup_si91x {type} {content} {length}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line,
                                                        timeout=timeout,
                                                        protocol=Protocol.WIFI,
                                                        async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id{socket_id}")
        return int(socket_id)

    @defaults("wifi")
    def writecalibrationdatasi91x(self, burn_target: int, flags: int, gain_offset: int, xo_ctune: int,
                                  expected_status=SLStatus.SL_STATUS_OK,
                                  timeout: int = 10):
        """ Arguments
            burn_target = Burn into efuse or flash, @ref SI91X_BURN_TARGET_OPTIONS
            flags = Calibration Flags, @ref SI91X_CALIBRATION_FLAGS
            gain_offset = gain offset
            xo_ctune  =  xo ctune
        """
        self.logger.info(
            f"\n *** Initiating write_calibration_data Cli command with Arguments: burn_target:{burn_target}, flags:{flags}, gain_offset:{gain_offset}, xo_ctune:{xo_ctune}  *** \n")
        line = f"write_calibration_data {burn_target} {flags} {gain_offset} {xo_ctune}"
        if self.test_agent_thread_enabled:
            status, send_data = self.issue_command_in_thread(line=line,
                                                             protocol=Protocol.WIFI,
                                                             timeout=timeout, async_timeout=120)
        else:
            status, send_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, send_data)

    @defaults("iop_sockets")
    def bsdSocketSendSi91x(
            self,
            socket_fd: int,
            buffer: str,
            flags: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            socket_fd   - socket file descriptor
            buffer      - Pointer to the buffer containing data to send to the remote peer
            flags       - Controls the transmission of the data
        """
        self.logger.info(
            f"*** Initiating bsd_socket.send_si91x Cli command with Arguments: socket_fd:{socket_fd}, buffer:{buffer}, flags:{flags} ***")
        line = (
            f'bsd_socket.send_si91x {socket_fd} {buffer} {flags}'
        )
        if self.test_agent_thread_enabled:
            status, send_data = self.issue_command_in_thread(line=line,
                                                             protocol=Protocol.WIFI,
                                                             timeout=timeout, async_timeout=120)
        else:
            status, send_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, send_data)

    @defaults("iop_sockets")
    def bsdSocketRecvSi91x(
            self,
            socket_fd: int,
            flags: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
            socket_fd   - socket file descriptor
            flags       - Controls the transmission of the data
        """
        self.logger.info(
            f"*** Initiating bsd_socket.recev_si91x Cli command with Arguments: socket_fd:{socket_fd}, flags:{flags} ***")
        line = (
            f'bsd_socket.recev_si91x {socket_fd} {flags}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)

    @defaults("iop_sockets")
    def bsdSocketSendTosi91x(
            self,
            socket_fd: int,
            data: str,
            ip_addr: str,
            ip_len: int,
            port: int,
            higher_data_len=0,
            flags=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        """Arguments:
                  Socket_fd     - Socket ID
                  data          - data send to buffer
                  ip_addr       - ip_address
                  ip_len        - ip_len
                  port          - port number like 5001
                  flags         - Controls the transmission of the data
                higher_data_len - length of data to send to buffer
                """

        self.logger.info(
            f"\n *** Initiating bsd_socket.send_to_si91x Cli command with Arguments: socket_fd:{socket_fd}, flags:{flags},  higher_data_len:{higher_data_len}, data:{data}, ip_addr:{ip_addr}, ip_len:{ip_len}, port:{port} *** \n")
        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        line = (
            f'bsd_socket.send_to_si91x {socket_fd} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""} {ip_addr} {ip_len} {port}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(
                line=line,
                timeout=timeout,
                )
        self.verify_status(status, expected_status, receive_data)
        if higher_data_len:
            self.memory_free(address)

    def ble_get_multiple_att_values_asynchronous(self,
                                                 ble_remote_dev_address: str,
                                                 no_of_handlers,
                                                 handle1,
                                                 handle2,
                                                 expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                                 timeout=10,
                                                 ):
        """
        Arguments:
        ble_remote_dev_address: remote BLE address
        no_of_handlers: no_of_handlers
        handle1
        handle2
        """
        line = f"ble_get_multiple_att_values_async {mac_address_to_string(ble_remote_dev_address, ':')} {no_of_handlers} {handle1} {handle2}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return data

    def ble_get_char_by_uuid(self,
                             ble_remote_dev_address: str,
                             start_handle,
                             end_handle,
                             uuid_size,
                             val_val128_data1,
                             val_val128_data2,
                             val_val128_data3,
                             val_val128_data4_sub1,
                             val_val128_data4_sub2,
                             val_val128_data4_sub3,
                             val_val128_data4_sub4,
                             val_val128_data4_sub5,
                             val_val128_data4_sub6,
                             val_val128_data4_sub7,
                             val_val128_data4_sub8,
                             val_val32,
                             val_val16,
                             expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                             timeout=10,
                             ):
        """
        Arguments:
        ble_remote_dev_address: remote BLE address
        start_handle
        end_handle
        uuid_size
        """
        line = f"ble_get_multiple_att_values_async {mac_address_to_string(ble_remote_dev_address, ':')} {start_handle} {end_handle} {uuid_size} {val_val128_data1} {val_val128_data2} {val_val128_data3} {val_val128_data4_sub1} {val_val128_data4_sub2} {val_val128_data4_sub3} {val_val128_data4_sub4} {val_val128_data4_sub5} {val_val128_data4_sub6} {val_val128_data4_sub7} {val_val128_data4_sub8} {val_val32} {val_val16}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return data

    def ble_get_attribute_descriptor_sync(self,
                                          ble_remote_dev_address: str,
                                          start_handle,
                                          end_handle,
                                          expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                          timeout=10,
                                          ):
        line = f"ble_get_att_desc_sync {mac_address_to_string(ble_remote_dev_address, ':')} {start_handle} {end_handle}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.BLE, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)
        return data

    def sl_net_configure_multicast_filter(self, filter_type: int, multicast_address: str,
                                          expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 10):
        """
        Arguments:
        filter_type: Type of filter to configure
        multicast_address: Multicast address to configure
        """
        self.logger.info(
            f"Configuring multicast filter with filter_type: {filter_type} and multicast_address: {multicast_address}")
        line = f"sl_net_configure_multicast_filter {filter_type} {multicast_address}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def websocket_init(
            self,
            server: WebServerInterface,
            host_name=None,
            resource_name=None,
            server_port=None,
            client_port=None,
            server_ip=None,
            enable_tls=0,
            tls_version=None,
            instance=0,
            host_name_null=0,
            resource_name_null=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        """
        Arguments:
        host_name: host_name in string
        resource_name: resource_name in string
        server_port: server_port
        client_port: client_port
        server_ipserver_ip: Server ip in string
        enable_tls: enable ssl
        tls_version: optional TLS version enum string (e.g. tls_default, tls_v_1_2)
        instance: websocket instance number
        host_name_null: Set this argument to 1 when host_name needs to be set to NULL
        resource_name_null: Set this argument to 1 when resource_name_null needs to be set to NULL
        """
        if server_ip:
            ip_addr = server_ip
        else:
            ip_addr = gethostbyname(server.hostname_or_ip_address)
        self.logger.info(f"Sending websocket init  CLI command with following parameters:\n"
                         f'websocket instance:{instance},'
                         f'websocket server ip address: {ip_addr},'
                         f'websocket server port: {server_port},'
                         f'client port: {client_port},'
                         f'host_name_null: {host_name_null},'
                         f'resource_name_null: {resource_name_null},'
                         f'{f",s::enable_tls:{enable_tls}" if enable_tls else ""}'
                         f'{f",h::host_name:{host_name}" if host_name else ""}'
                         f'{f",r::resource_name:{resource_name}" if resource_name else ""}'
                         f'{f",t::tls_version:{tls_version}" if tls_version is not None else ""}'
                         )
        line = (
            f'websocket.init {instance} {ip_addr} {server_port} {client_port} {host_name_null} {resource_name_null}'
            f'{f" -s true" if enable_tls else ""}{f" -h {host_name}" if host_name is not None else ""}'
            f'{f" -r {resource_name}" if resource_name is not None else ""}'
            f'{f" -t {tls_version}" if tls_version is not None else ""}')

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def websocket_set_origin(
            self,
            instance=0,
            origin=None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = f'websocket.set_origin {instance}{f" -o {origin}" if origin is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def websocket_set_tcp_tls_advanced_config(
            self,
            instance=0,
            tcp_keepalive_initial_time_sec=None,
            tcp_max_retry_count=None,
            max_retransmission_timeout_value=None,
            ssl_ciphers_bitmap=None,
            ssl_ext_ciphers_bitmap=None,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = (
            f'websocket.set_tcp_tls_advanced_config {instance}'
            f'{f" -a {tcp_keepalive_initial_time_sec}" if tcp_keepalive_initial_time_sec is not None else ""}'
            f'{f" -b {tcp_max_retry_count}" if tcp_max_retry_count is not None else ""}'
            f'{f" -c {max_retransmission_timeout_value}" if max_retransmission_timeout_value is not None else ""}'
            f'{f" -d {ssl_ciphers_bitmap}" if ssl_ciphers_bitmap is not None else ""}'
            f'{f" -e {ssl_ext_ciphers_bitmap}" if ssl_ext_ciphers_bitmap is not None else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def websocket_send(
            self,
            opcode=None,
            higher_data_len=0,
            address=None,
            data="hello",
            instance=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        self.logger.info(f"Send websocket data with opcode {opcode}")
        if higher_data_len:
            if address is None:
                self.logger.info(f"address is not sent from the test case when data length is more than 100 bytes")
        line = (
            f'websocket.send {instance} {opcode} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""}'
        )
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def websocket_connect(
            self,
            instance=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = f"websocket.connect {instance}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=timeout, timeout=timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def websocket_close(
            self,
            instance=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = f"websocket.close {instance}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def websocket_deinit(
            self,
            instance=0,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout=10,
            ):
        line = f"websocket.deinit {instance}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def start_ip_lwip(self, static_ip: str = None, ip_version: str = 'ipv4', static_subnet: str = None,
                      static_gateway: str = None,
                      expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=10):
        line = None
        self.logger.info(f"\n *** Initiating start_ip_lwip *** \n")
        if not [x for x in (static_ip, static_subnet, static_gateway) if x is None]:
            line = f"lwip.configure_ip {ip_version} -i {static_ip} -n {static_subnet} -g {static_gateway}"
        else:
            line = f"lwip.configure_ip {ip_version}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=50,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)

        self.verify_status(status, expected_status)

#######################################################################################################################################
    def lwip_start_ip(self, static_ip: str = None, ip_version: str = 'ipv4', static_subnet: str = None,
                 static_gateway: str = None, vid: int = None,
                 static_ipv6_address: str = None,
                 ipv6_gw_address: str = None,
                 expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout=30):
        self.logger.info(f"\n *** Initiating lwip_start_ip *** \n")

        if not [x for x in (static_ip, static_subnet, static_gateway) if x is None]:
            line = f"net.configure_ip {ip_version} -i {static_ip} -n {static_subnet} -g {static_gateway} -v {vid}"
        elif not [x for x in (static_ipv6_address, ipv6_gw_address) if x is None]:
            line = f"net.configure_ip {ip_version} -a {static_ipv6_address} -w {ipv6_gw_address} -v {vid}"
        else:
            line = f"net.configure_ip {ip_version}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.networked = True
            ip_info = self.get_command_data(data)
            if ip_version == 'ipv4':
                matches = re.findall(b"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info)
                assert (
                        len(matches) == 3
                ), f"Error parsing IP, netmask and gateway from {ip_info}"
                ip, netmask, gateway = [match.strip() for match in matches]
                self.ip = self.IPConfig(ip=ip, netmask=netmask, gateway=gateway)
                self.logger.info(f"********ip*******:*******{self.ip}****{type(self.ip)}*")
                return self.ip
            else:
                linklocaladdr = ip_info.split(b",")[0].strip().decode()
                global_addr = ip_info.split(b",")[1].strip().decode()
                gateway_addr = ip_info.split(b",")[2].strip().decode()
                return linklocaladdr, global_addr, gateway_addr

#######################################################################################################################################
    def display_device_ip_lwip(
            self,
            mode: str = "client",
            profile_id: int = None,
            ip_version: str = 'ipv4',
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            ):
        line = f'lwip.print_device_ip {mode}{f" -i {profile_id} " if profile_id else ""}{f" -p {ip_version} " if ip_version else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout,
                                                        protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status == SLStatus.SL_STATUS_OK:
            self.networked = True
            ip_info = self.get_command_data(data)
            if ip_version == 'ipv4':
                matches = re.findall(b"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip_info)
                assert (
                        len(matches) == 3
                ), f"Error parsing IP, netmask and gateway from {ip_info}"
                ip, netmask, gateway = [match.strip() for match in matches]
                self.ip = self.IPConfig(ip=ip, netmask=netmask, gateway=gateway)
                self.logger.info(f"********ip*******:*******{self.ip}****{type(self.ip)}*")
                return self.ip
            else:
                linklocaladdr = ip_info.split(b",")[0].strip().decode()
                global_addr = ip_info.split(b",")[1].strip().decode()
                gateway_addr = ip_info.split(b",")[2].strip().decode()
                return linklocaladdr, global_addr, gateway_addr

    @defaults("iop_sockets")
    def set_attenuator(self, rf_attenuator, att_channel, db_value, att_enable=True):
        if att_enable:
            self.logger.info("******** Adding attenuator ***********")
            self.logger.info(f"Setting attenuator level to {db_value}db")
            rf_attenuator.interfaces.attenuator.reset()
            rf_attenuator.interfaces.attenuator.set_attenuator(att_channel, db_value)
            attn = rf_attenuator.interfaces.attenuator.get_attenuator(att_channel)
            self.logger.info(f"Readback of attenuator level: {attn}db")
            assert attn == db_value
        else:
            self.logger.info("******** Attenuator Disable ***********")

    def add_vendor_ie(
            self,
            ie_buffer: str = None,
            ie_buffer_length: int = None,
            unique_id: int = None,
            mgmt_frame_bitmap: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
    ):
        """Arguments:
            ie_buffer - Vendor IE buffer as hex string (e.g., "dd 05 aa bb cc 01 ee") or memory address
            ie_buffer_length - Length of the IE buffer
            unique_id - Unique identifier for the vendor IE (default: 0)
            mgmt_frame_bitmap - Management frame bitmap flags (optional)
        """
        self.logger.info(
            f"\n *** Initiating add_vendor_ie Cli command with Arguments: ie_buffer:{ie_buffer}, ie_buffer_length:{ie_buffer_length}, unique_id:{unique_id}, mgmt_frame_bitmap:{mgmt_frame_bitmap} *** \n")

        # Parse hex string and allocate memory if needed
        # Check if it's a hex string (contains spaces or is a hex string without 0x prefix)
        # vs a memory address (numeric string or hex with 0x prefix)
        if ie_buffer:
            ie_buffer_str = str(ie_buffer).strip()
            # Check if it looks like a hex data string (contains spaces or is hex without 0x)
            # Examples: "dd 05 aa bb cc 01 ee" or "dd05aabbcc01ee"
            is_hex_data_string = (' ' in ie_buffer_str or 
                                 (len(ie_buffer_str) > 2 and not ie_buffer_str.startswith('0x') and 
                                  all(c in '0123456789abcdefABCDEF ' for c in ie_buffer_str)))
            
            if is_hex_data_string:
                # Parse hex string (handles formats like "dd 05 aa bb cc 01 ee" or "dd05aabbcc01ee")
                hex_bytes = ''.join(ie_buffer.split())  # Remove spaces
                try:
                    binary_data = bytes.fromhex(hex_bytes)
                except ValueError as e:
                    raise ValueError(f"Invalid hex string format in ie_buffer: {ie_buffer}. Error: {e}")

                # Validate length matches
                if ie_buffer_length is None:
                    ie_buffer_length = len(binary_data)
                elif ie_buffer_length != len(binary_data):
                    raise ValueError(
                        f"ie_buffer_length ({ie_buffer_length}) doesn't match parsed hex data length ({len(binary_data)})")

                # Allocate memory on DUT
                buffer_address = self.allocate_memory(size=ie_buffer_length, timeout=timeout)

                # Load binary data into allocated memory
                self.load_memory(
                    address=buffer_address,
                    size=ie_buffer_length,
                    write_content=binary_data,
                    timeout=timeout
                )

                # Use the address instead of the hex string
                ie_buffer = buffer_address

        # Format the command line - ensure address is passed as hex number
        # The console parser for 'hex' type handles both "0x1234" and "1234" formats
        # The address from allocate_memory should already be in a format the parser can handle
        line = f'wifi.add_vendor_ie {ie_buffer} {ie_buffer_length} {f" -u {unique_id}" if unique_id is not None else ""} {f" -b {mgmt_frame_bitmap}" if mgmt_frame_bitmap is not None else ""}'

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        if status != SLStatus.SL_STATUS_OK:
            return
        pattern = r'Vendor-specific IE added with unique ID:\s*(\d+)'
        match = re.search(pattern, data.decode())
        if match:
            unique_id = int(match.group(1))
            self.logger.info(f"Unique ID: {unique_id}")
            return unique_id
        else:
            raise ValueError(f"Failed to parse unique ID from response: {data}")

    def remove_vendor_ie(
            self,
            unique_id: int = None,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
    ):
        """Arguments:
            unique_id - Unique identifier for the vendor IE to remove (default: 0)
        """
        self.logger.info(
            f"\n *** Initiating remove_vendor_ie Cli command with Arguments: unique_id:{unique_id} *** \n")
        line = f'wifi.remove_vendor_ie{f" -u {unique_id}" if unique_id is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

    def remove_all_vendor_ie(
            self,
            expected_status: SLStatus = SLStatus.SL_STATUS_OK,
            timeout: int = 10,
    ):
        """Arguments:
            None - Removes all vendor-specific IEs
        """
        self.logger.info(
            f"\n *** Initiating remove_all_vendor_ie Cli command *** \n")
        line = 'wifi.remove_all_vendor_ie'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
    
#######################################################################################################################################
    def config_modular_stats(self, stats_arg=0, timeout=10, expected_status=SLStatus.SL_STATUS_OK):
        if self.test_agent_thread_enabled and self.inited_test_agent_threads:
            status, data = self.issue_command_in_thread(f'wifi.config_stats -s {stats_arg}', protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(f'wifi.config_stats -s {stats_arg}', timeout)
        self.verify_status(status, expected_status)
        return status
    
#######################################################################################################################################
    def lwipSocketCreate(self, domain: str, stream_type: str, protocol: str, expected_status=SLStatus.SL_STATUS_OK,
                         timeout: int = 10):
        """ Arguments
            domain = ["AF_INET"/"AF_INET6"]
            type = ["SOCK_STREAM"/"SOCK_DGRAM"]
            protocol = ["IPPROTO_TCP"/"IPPROTO_UDP"]
        """
        self.logger.info(f"\n *** Create {protocol} BSD Socket  *** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"lwip.socket_create {domain} {stream_type} {protocol}",
                                                        protocol=Protocol.WIFI, timeout=timeout)
        else:
            status, data = self.issue_command(f'lwip.socket_create {domain} {stream_type} {protocol}', timeout)

        self.verify_status(status, expected_status, data)
        self.logger.info(f'\n\n STATUS = {status}, DATA = {data}')
        output = data.decode()
        socket_id = output.replace("\n", "")
        self.logger.info(f"Socket id = {socket_id}")
        self.lwip_socket_info["sockets"].append(socket_id)
        self.logger.info(f'\n\n *** LWIP Socket id list = {self.lwip_socket_info["sockets"]}')
        return int(socket_id)

#######################################################################################################################################
    def lwipSocketBind(self, socket_fd: int = None, device_ip: str = None, ip_len: int = None, server_port: int = None,
                       asynch: int = None,
                       ip_version=Si91xIpVersion.SL_IPV4_VERSION,
                       expected_status=SLStatus.SL_STATUS_OK,
                       timeout: int = 10):
        self.logger.info(f"\n *** Bind LWIP Socket on {device_ip} *** \n")
        line = f'lwip.bind {socket_fd} {device_ip} {ip_len} {server_port}{f" -j {asynch}" if asynch else ""}{f" -v {ip_version}" if ip_version is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line, protocol=Protocol.WIFI,
                timeout=timeout)
        else:
            status, data = self.issue_command(
                line,
                timeout)
        self.verify_status(status, expected_status, data)

#######################################################################################################################################
    def lwipSocketListen(
            self,
            socket_fd: int,
            backlog: int,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 30
    ):
        line = f"lwip.listen {socket_fd} {backlog}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)

#######################################################################################################################################
    def lwipSocketAccept(
            self, socket_fd: int,
            ip_version=Si91xIpVersion.SL_IPV4_VERSION,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
            async_timeout: int = 30
    ):
        line = f"lwip.accept {socket_fd}"
        # line = f"lwip.accept {socket_fd}{f' -v {ip_version}' if ip_version is not None else ''}"

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [], async_timeout=async_timeout)
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, data)
        return data

#######################################################################################################################################
    def lwipSocketConnect(self, socket_fd: int, server_ip: str, server_port: int,
                          expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, ip_len: int = 4):
        self.logger.info(
            f"\n *** Initiate BSD socket connect for server_ip: {server_ip}, server_port: {server_port} *** \n")

        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f'lwip.connect {socket_fd} {server_ip} {ip_len} '
                                                        f'{server_port}', protocol=Protocol.WIFI, timeout=timeout,
                                                        async_timeout=60)
        else:
            status, data = self.issue_command(f'lwip.connect {socket_fd} {server_ip} {ip_len} {server_port}',
                                              timeout)
        self.verify_status(status, expected_status, data)
        return data

#######################################################################################################################################
    def lwipSocketSend(self, socket_fd: int, data: str, higher_data_len=0, expected_status=SLStatus.SL_STATUS_OK,
                       timeout: int = 10):
        if higher_data_len:
            address = self.allocate_memory(size=len(data) + 1)
            self.load_memory(address=address, size=len(data), write_content=data, timeout=1)
        self.logger.info(
            f"\n *** Initiate LWIP socket data transfer *** \n")
        line = (
            f'lwip.send {socket_fd} {higher_data_len}{f" -a {address}" if higher_data_len else ""}{f" -d {data}" if not higher_data_len else ""}'
        )
        if self.test_agent_thread_enabled:
            status, receive_data = self.issue_command_in_thread(line=line,
                                                                protocol=Protocol.WIFI,
                                                                timeout=timeout, async_timeout=120)
        else:
            status, receive_data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status, receive_data)
        if status != SLStatus.SL_STATUS_OK:
            return status, receive_data.decode()
        output = receive_data.decode()
        send_no_of_bytes = re.search(r'\d+ bytes sent', output)
        if higher_data_len:
            self.memory_free(address)
        return send_no_of_bytes.group(0).split()[0]

#######################################################################################################################################
    def lwipSocketReceive(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10, async_timeout: int = 40
    ):
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"lwip.receive {socket_fd}", protocol=Protocol.WIFI,
                                                        timeout=timeout, async_timeout=async_timeout)
        else:
            status, data = self.issue_command(
                f"lwip.receive {socket_fd}", timeout
            )
        self.verify_status(status, expected_status, data)
        rx_data = re.findall(r'Received:(\w+)', data.decode())[-1]
        self.logger.info(f"rx_data :{rx_data}")

        return rx_data

#######################################################################################################################################
    def lwipSetSocketOpt(
            self,
            socket_fd: int,
            option_val: str,
            option_level: str,
            option_name: str,
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 10,
    ):
        line = f"lwip.set_opt {socket_fd} {option_level} {option_name} {option_val}"
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line, Protocol.WIFI, [])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def lwipSockClose(
            self, socket_fd: int, expected_status=SLStatus.SL_STATUS_OK, timeout: int = 10):
        self.logger.info(f"\n *** Close LWIP Socket {socket_fd}*** \n")
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(f"lwip.close {socket_fd}", protocol=Protocol.WIFI,
                                                        timeout=timeout)
        else:
            status, data = self.issue_command(
                f"lwip.close {socket_fd} ", timeout
            )
        if self.lwip_socket_info["sockets"]:
            self.lwip_socket_info["sockets"].remove(str(socket_fd))
        self.logger.info(f'current LWIP socket id list = {self.lwip_socket_info["sockets"]}')
        self.verify_status(status, expected_status, data)

#######################################################################################################################################
    def lwip_close_sockets(self) -> None:
        if len(self.lwip_socket_info["sockets"]):
            self.logger.info(
                f'Closing all the sockets {self.lwip_socket_info["sockets"]} before disconnection')
            while len(self.lwip_socket_info["sockets"]) > 0:
                socket_id = self.lwip_socket_info["sockets"][-1]
                self.logger.info(f"passing socket ID: {socket_id} from the list to close the socket")
                self.lwipSockClose(socket_fd=socket_id)
        self.lwip_socket_info["sockets"] = []

#######################################################################################################################################
    def mdns_service_discovery_start(self,
                                     interface: str = None,
                                     service_type: str = None,
                                     query_type: int = None,
                                     timeout_ms: int = None,
                                     expected_status: SLStatus = SLStatus.SL_STATUS_IN_PROGRESS,
                                     timeout: int = 20
                                    ):
        """ Start mDNS service discovery
        Args:
            interface: Network interface for discovery (e.g., SL_NET_WIFI_CLIENT_INTERFACE)
            service_type: Service type string to discover (e.g., "NB0018908.local.")
            query_type: mDNS service query types (see sl_mdns_query_type_t)
            timeout_ms: Discovery timeout in milliseconds (default: 5000)
        """

        self.logger.info("\n ** Start mDNS Service Discovery **\n")

        # Build command line for mDNS service discovery with optional parameters
        line = (
            f'mdns.start_discovery{f" -i {interface}" if interface else ""}'
            f'{f" -s {service_type}" if service_type else ""}'
            f'{f" -p {query_type}" if query_type is not None else ""}'
            f'{f" -t {timeout_ms}" if timeout_ms is not None else ""}'
        )
        
        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5, protocol=Protocol.WIFI, async_identifiers=[AsyncEventIdentifiers.MDNS_SD])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        return data.decode()

#######################################################################################################################################
    def mdns_service_discovery_stop(self,
                                    interface: str = None,
                                    expected_status: SLStatus = SLStatus.SL_STATUS_OK,
                                    timeout: int = 20
                                  ):
        """ Stop mDNS service discovery
        Args:
            interface: Network interface to stop discovery on (e.g., SL_NET_WIFI_CLIENT_INTERFACE)
        """
        
        self.logger.info("\n ** Stop mDNS Service Discovery **\n")

        # Build command line for stopping mDNS service discovery with optional interface parameter
        line = f'mdns.stop_discovery{f" -i {interface}" if interface else ""}'
        
        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, async_timeout=5, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)

#######################################################################################################################################
    def _merge_mqtt_incoming_serial_records(
            self, filtered: List[Tuple[int, bytes]]
            ) -> List[Tuple[int, bytes]]:
        """Merge UART reads that belong to one Fxxxx\\\\topic\\\\n<payload> MQTT async notification."""
        merged: List[Tuple[int, bytes]] = []
        i = 0
        while i < len(filtered):
            ts, record = filtered[i]
            if not _MQTT_ASYNC_UART_HEADER_RE.search(record):
                i += 1
                continue
            parts = [record]
            j = i + 1
            while j < len(filtered):
                nxt = filtered[j][1]
                st = nxt.lstrip(b"> \t\r\n")
                if j > i and _MQTT_ASYNC_UART_HEADER_RE.match(st):
                    break
                if len(st) >= 6 and st[0:1] == b"F" and st[5:6] == b"<":
                    break
                if (
                        st.startswith(b"t ")
                        or st.startswith(b"mem.")
                        or st.startswith(b"0x")
                        or st.startswith(b"wifi.")
                        or st.startswith(b"mqtt.")
                        or st.startswith(b"thread ")
                        or st.startswith(b"terminate ")
                        ):
                    break
                parts.append(nxt)
                j += 1
            merged.append((ts, b"".join(parts)))
            i = j
        return merged
    def _parse_merged_mqtt_async_blob(self, blob: bytes) -> Optional[Tuple[bytes, bytes]]:
        blob = blob.lstrip(b"> \t\r\n")
        m = _MQTT_ASYNC_UART_HEADER_RE.search(blob)
        if not m:
            return None
        blob = blob[m.start():]
        # Byte after "Fxxxx\" is start of topic; topic may contain \\r\\n and F+4hex continuation
        # lines before the single \\n that separates topic from payload.
        pos = m.end()
        topic = bytearray()
        n = len(blob)
        while pos < n:
            if blob[pos : pos + 2] == b"\r\n":
                pos += 2
                if pos >= n:
                    break
                cont = re.match(rb"F[0-9A-Fa-f]{4}", blob[pos:])
                if cont and (pos + 5 >= n or blob[pos + 5 : pos + 6] != b"\\"):
                    pos += 5
                    continue
                break
            if blob[pos] == ord("\n"):
                pos += 1
                break
            topic.append(blob[pos])
            pos += 1
        body = blob[pos:]
        lines = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        payload = bytearray()
        for idx, line in enumerate(lines):
            if not line:
                continue
            if idx > 0:
                cont = _MQTT_UART_PAYLOAD_CONT_RE.match(line)
                if cont:
                    line = line[cont.end() :]
            payload.extend(line)
        return bytes(topic), bytes(payload)

#######################################################################################################################################
    def get_log_level(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, timeout: int = 5):
        """Get the current log level"""
        
        # Build command line for getting the log level
        line = f"get_log_level"
        
        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)
        
#######################################################################################################################################
    def set_log_level(self, expected_status: SLStatus = SLStatus.SL_STATUS_OK, log_level: int = None, timeout: int = 5):
        """Set the log level"""
        
        # Build command line for setting the log level
        line = (f"set_log_level "
                f"{f' -a {log_level}' if log_level is not None else ''}")

        # Issue command in thread or directly based on configuration
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(line=line, timeout=timeout, protocol=Protocol.WIFI, async_identifiers=[])
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        
        # Verify the command status
        self.verify_status(status, expected_status)



    def sl_net_get_interface_info(
            self,
            interface: str = "client",
            expected_status=SLStatus.SL_STATUS_OK,
            timeout: int = 40,
            ):
        """Query sl_net_get_interface_info for client or AP interface.

        Args:
            interface: net_interface enum value (e.g. client, ap).
            expected_status: Expected SL status or list of accepted statuses.
            timeout: Command timeout in seconds.
        """
        self.logger.info("Get net interface info for interface=%s", interface)
        line = f'net.get_interface_info{f" -a {interface}" if interface is not None else ""}'
        if self.test_agent_thread_enabled:
            status, data = self.issue_command_in_thread(
                line=line,
                timeout=timeout,
                async_timeout=40,
                protocol=Protocol.WIFI,
                async_identifiers=[],
            )
        else:
            status, data = self.issue_command(line=line, timeout=timeout)
        self.verify_status(status, expected_status)
        return data.decode()