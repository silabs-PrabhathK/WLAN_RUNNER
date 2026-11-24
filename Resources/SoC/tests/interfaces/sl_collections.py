from typing import Dict
from utf.utils.logger import get_logger
import time
from utf.utils.iperf.iperf_utils import ping
from retry import retry
from copy import deepcopy
from utf.utf_config import UtfConfig
from utf.utils.defaults import defaults
import subprocess
import re
import uuid
from utf_wiseconnect_3.tests.devices.si91x import Si91xPowerSaveModes, Si91xPowerSaveProcedureTypes, \
    Si91xExtCustomFeatureBitMap, Si91xCryptoKeyType, \
    Si91xCryptoWrapMode, Si91xCertificateType, Si91xCertIdentifier
from datetime import datetime
from utf.interfaces.bluetooth import BLEDeviceState
from threading import Thread
from utf.utils.time_measurer import TimeMeasurer
import os
from utf_wiseconnect_3.tests.interfaces import AsyncEventIdentifiers
from utf.utils.stopwatch import Stopwatch
import threading
from utf.utils import get_tls_certificate_dir


def logger():
    return get_logger(__name__)


class SLCollections:
    instance = None

    def __init__(self):
        self.address_type_list = {
            0: "Public Device Address", 1: "Random Device Address",
            2: "Resolvable Private Address with public address", 3: "Resolvable Private Address with random address"
            }

        self.phy_channel = {
            1: "1M", 2: "2M", 3: "LE Coded"
            }

        self.ae_data_type = {
            1: "BLE_AE_ADV_DATA_TYPE",
            2: "BLE_AE_PERIODIC_ADV_DATA_TYPE",
            3: "BLE_AE_SCAN_RSP_DATA_TYPE"
            }

    @classmethod
    def create_instance(cls) -> "SLCollections":
        cls.instance = SLCollections()
        return cls.instance

    @classmethod
    def get_instance(cls) -> "Optional[SLCollections]":
        if cls.instance is not None:
            return cls.instance
        return None

    def scan(self, wifi_dut, scan_status=False, retry_count=1, channel=0):
        scan_resp = ""
        for count in range(0, retry_count):
            try:
                scan_status = False
                logger().info(f"....Scanning for AP nearby.....")
                scan_resp = wifi_dut.interfaces.wifi.scan(channel=channel, ssid=None)
                scan_status = True
                break
            except Exception as e:
                logger().info(f"....Scanning for AP unsuccessfull....retrying for the {count + 1} iteration")
                logger().info(f"ERROR FOUND -> {str(e)}")
                scan_resp = str(e)
        return scan_status, scan_resp

    def connect(self, wifi_dut, wifi_access_point, join_status=False, retry_count=1, pmk_enable=False, enc="ccmp",
                expected_negative_status=None, channel_bitmap_2_4: int = None,
                channel_bitmap_5: int = None, mac=None):
        reason = ""
        for count in range(0, retry_count):
            try:
                join_status = False
                logger().info(".... Connecting to Wi-Fi AP....")

                if enc == "tkip":
                    wifi_dut.interfaces.wifi.join(ssid=wifi_access_point.interfaces.wifi.ssid,
                                                  security=wifi_access_point.interfaces.wifi.security.name.lower(),
                                                  passphrase=wifi_access_point.interfaces.wifi.passphrase,
                                                  channel=wifi_access_point.interfaces.wifi.channel,
                                                  pmk_enable=pmk_enable,
                                                  enc=enc,
                                                  channel_bitmap_2_4=channel_bitmap_2_4,
                                                  channel_bitmap_5=channel_bitmap_5,
                                                  expected_negative_status=expected_negative_status,
                                                  mac=mac,
                                                  timeout=60,
                                                  )
                else:
                    wifi_dut.interfaces.wifi.join_ap(wifi_access_point, pmk_enable=pmk_enable,
                                                     channel_bitmap_2_4=channel_bitmap_2_4,
                                                     expected_negative_status=expected_negative_status, mac=mac)
                join_status = True
                break
            except Exception as e:
                logger().info(
                    f"\n\n **** Connection to Wi-Fi AP Failed....retrying for the {count + 1} iteration ****\n\n")
                logger().info(f"ERROR FOUND -> {str(e)}")
                reason = str(e)
        return join_status, reason

    def configure_ip(self, wifi_dut, ip_status=False, retry_count=1, ip_version='ipv4', timeout=60):
        ip_config = ""
        for count in range(0, retry_count):
            try:
                ip_status = False
                # DUT GETS IP ADDRESS THROUGH prescribed mode static/dhcp
                logger().info("....DUT configures the IP Address....")
                ip_config = wifi_dut.interfaces.wifi.start_ip(timeout=timeout, ip_version=ip_version)
                ip_status = True
                break
            except Exception as e:
                logger().info(f"....IP ADDRESS through DHCP failed!.....retrying for the {count + 1} time....")
                time.sleep(10)
                logger().info(f"ERROR FOUND -> {str(e)}")
                ip_config = str(e)
        return ip_status, ip_config

    def ping(self, device_ip=None, ping_count=0, retry_count=1):
        status = None
        for retry_count in range(0, retry_count):
            try:
                logger().info(f'DUT IP : {device_ip}')
                logger().info("....Pinging to DUT.....")
                status = ping(device_ip, ping_count)
                assert status, "DUT ISN'T RESPONDING FOR PING REQUEST......"
                logger().info("PING TO DUT IS SUCCESSFULLY DONE....")
                break
            except Exception as err:
                logger().warning(f"Failed to ping DUT...RETRY COUNT IS {retry_count + 1}\nWarning:{err}")
                time.sleep(15)
        return status

    @retry(Exception, delay=15, tries=5)
    def ping_with_custom_size(self, device_ip, ping_counts=10, byte_size=64, negative_test=False):
        command = ["ping", "-c", str(ping_counts), "-s", str(byte_size), device_ip]
        result = subprocess.run(command, capture_output=True)
        rc = result.returncode
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
        if negative_test:
            if rc != 0:
                logger().info(f"{command} command exited with code {rc} with output:\n{stdout}\n{stderr}")
                logger().info(f"Ping command failed as expected for negative test case")
            return rc != 0
        if rc != 0 or stderr:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}\n{stderr}")
        else:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}")
        assert rc == 0 and stderr == "", "Failed to ping to DUT"
        return rc == 0 and stderr == ""

    def check_device_active(self, device_ip, timeout=30, interval=5, ping_count=5):
        """
           Check if a device is in an active state by pinging it for a specified duration.

            Args:
                device_ip (str): The IP address of the device to ping.
                timeout (int): The total duration (in seconds) to check the device's state. Default is 180 seconds.
                interval (int): The interval (in seconds) between each ping attempt. Default is 5 seconds.

            Returns:
                bool: True if the device responds to ping within the timeout period, False otherwise.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if ping(device_ip, ping_count):
                return True
            logger().info(f"Device {device_ip} is not active. Retrying in {interval} seconds...")
            time.sleep(interval)
        return False

    def ping_with_custom_interval(self, device_ip, ping_count=10, interval=1):
        command = ["ping", "-c", str(ping_count), "-i", str(interval), device_ip]
        result = subprocess.run(command, capture_output=True)
        rc = result.returncode
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
        if rc != 0 or stderr:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}\n{stderr}")
        else:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}")

    def join_to_wifi_network(self, wifi_dut=None, wifi_access_point=None, power_save=True,
                             mode='power_save_low_latency', channel=0,
                             ping_count=10, retry_count=1, ping_after_power_save=False, ping_before_power_save=True,
                             associated=None,
                             dtim_aligned_type=0, num_of_dtim_skip=0, listen_interval=0, monitor_interval=0,
                             pmk_enable=False,
                             ip_version='ipv4', tcp_ip_bypass=False, ip_config_disable=False, enc="ccmp",
                             expected_negative_status=None,
                             ipv6_type='global', skip_connect=False, skip_scan=False, channel_bitmap_2_4: int = None,
                             channel_bitmap_5: int = None,
                             mac=None):
        """
        This function is responsible to connect DUT with AP and return dictionary which contain dut-ip-add & mac address
        :param enc:
        :param ping_before_power_save:
        :param tcp_ip_bypass:
        :param monitor_interval:
        :param ip_version:
        :param listen_interval:
        :param num_of_dtim_skip:
        :param dtim_aligned_type:
        :param ssid:
        :param channel:
        :param wifi_dut:
        :param wifi_access_point:
        :param power_save:
        :param mode: Default-"power_save_low_latency" | power_save_low_latency|power_save|deep_sleep_without_ram_retention
                            |deep_sleep_with_ram_retention
        :param ping_count:
        :param retry_count: User can increase retry count for scan|connect|configure_ip|ping via Harness file
        :param ping_after_power_save: Depend on test case requirement
        :param associated: User can add input from test program like "wifi_dut.interfaces.wifi.associated"
        :param pmk_enable: User can enable PMK validation from Test Case
        :param expected_negative_status: User expects some negative status from join API
        :param skip_scan: User can bypass the scan function assigning False value
        :param skip_connect: User can bypass the connect function assigning False value
        :return: dut_add_dict['device_ip', 'dut_mac_address']
        """
        dut_add_dict = {}

        if associated is False:
            # scan method tries to scan for nearby Access Points
            if skip_scan is False:
                scan_status, reason = self.scan(wifi_dut, scan_status=False, retry_count=retry_count, channel=channel)
                assert scan_status, f"....Scanning for AP failed..with reason: {reason}...."

            dut_add_dict['dut_mac_address'] = wifi_dut.interfaces.wifi.get_mac_address()

            # join method tries to connect to AP
            if skip_connect is False:
                join_status, reason = self.connect(wifi_dut=wifi_dut, wifi_access_point=wifi_access_point,
                                                   join_status=False, retry_count=retry_count, pmk_enable=pmk_enable,
                                                   enc=enc, channel_bitmap_2_4=channel_bitmap_2_4,
                                                   channel_bitmap_5=channel_bitmap_5,
                                                   expected_negative_status=expected_negative_status,
                                                   mac=mac)
                assert join_status, f"....Connection to the AP failed with reason: {reason}...."
                logger().info("....Successfully connected to the AP....")

            if not (tcp_ip_bypass or ip_config_disable):
                # configure_ip tries to assign IP ADDRESS through DHCP
                ip_status, ip_config = self.configure_ip(wifi_dut, ip_status=False, retry_count=retry_count,
                                                         ip_version=ip_version)
                assert ip_status, f"....Unable to assign IP ADDRESS through DHCP with reason: {ip_config}...."

                if ip_version == 'ipv4':
                    device_ip = wifi_dut.interfaces.wifi.get_device_ip(ip_config)
                else:
                    if ipv6_type == 'global':
                        device_ip = ip_config[1]
                    else:
                        device_ip = ip_config[0]

                logger().info(f"DUT ip: {device_ip}")

                # we fetch the ip address and mac_address
                dut_add_dict['device_ip'] = device_ip

                logger().info(
                    f"DUT MAC ADDRESS :  {dut_add_dict['dut_mac_address']} DUT IP ADDRESS : {dut_add_dict['device_ip']}")

                # ping to DUT before power_save
                if ping_before_power_save:
                    status = self.ping(device_ip=dut_add_dict['device_ip'], ping_count=ping_count)
                    assert status, "DUT NOT RESPONDING FOR PING REQUEST......"

            if power_save:
                logger().info(f"....Applying performance profile mode : {mode}")
                wifi_dut.interfaces.wifi.set_performance_profile(mode, dtim_aligned_type, num_of_dtim_skip,
                                                                 listen_interval, monitor_interval)
                wifi_dut.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                              psp_type=Si91xPowerSaveProcedureTypes.FastPowerSave)
                if not tcp_ip_bypass:
                    if ping_after_power_save:
                        logger().info("....Pinging DUT after power-save....")
                        status = self.ping(device_ip=dut_add_dict['device_ip'], ping_count=ping_count)
                        assert status, "DUT NOT RESPONDING FOR PING REQUEST......"

            return dut_add_dict
        else:
            logger().info(f'\n\n *** Device is already connected with AP *** \n\n')

    def join_to_wifi_network_at_cmd(
            self, wifi_dut=None, wifi_access_point=None, power_save=True,
            mode='power_save_low_latency', channel=0, ping_count=10,
            retry_count=1, ping_after_power_save=False,
            ping_before_power_save=True, associated=None,
            dtim_aligned_type=0, num_of_dtim_skip=0, listen_interval=0,
            monitor_interval=0, ip_version='ipv4', ip_config_disable=False,
            skip_connect=False, skip_scan=False, security=None, **join_kwargs):
        """
        Join an AP through the SDK3 raw AT interface and return DUT addresses.

        The workflow intentionally reuses the collection retry helpers while
        omitting test-agent-only Bluetooth power-save commands.
        """
        wifi = wifi_dut.interfaces.wifi
        if associated is None:
            associated = wifi.associated
        if associated:
            logger().info("Device is already connected with AP")
            result = {'dut_mac_address': wifi.get_mac_address()}
            if wifi.networked:
                result['device_ip'] = wifi.get_ip_address()
            return result

        if not skip_scan:
            scan_status, reason = self.scan(
                wifi_dut, scan_status=False, retry_count=retry_count,
                channel=channel)
            assert scan_status, \
                f"....Scanning for AP failed..with reason: {reason}...."

        dut_add_dict = {'dut_mac_address': wifi.get_mac_address()}
        if not skip_connect:
            if security is not None:
                join_kwargs['security'] = security
            reason = ""
            join_status = False
            for count in range(retry_count):
                try:
                    logger().info(".... Connecting to Wi-Fi AP through AT....")
                    wifi.join_ap(wifi_access_point, **join_kwargs)
                    join_status = True
                    break
                except Exception as error:
                    reason = str(error)
                    logger().warning(
                        "AT connection failed on attempt %d: %s",
                        count + 1, reason)
            assert join_status, \
                f"....Connection to the AP failed with reason: {reason}...."

        if not ip_config_disable:
            ip_status, ip_config = self.configure_ip(
                wifi_dut, ip_status=False, retry_count=retry_count,
                ip_version=ip_version)
            assert ip_status, \
                f"....Unable to assign IP ADDRESS through DHCP with reason: {ip_config}...."
            device_ip = wifi.get_device_ip(ip_config)
            dut_add_dict['device_ip'] = device_ip
            if ping_before_power_save:
                assert self.ping(
                    device_ip=device_ip, ping_count=ping_count,
                    retry_count=retry_count), \
                    "DUT NOT RESPONDING FOR PING REQUEST......"

        if power_save:
            wifi.set_performance_profile(
                mode, dtim_aligned_type, num_of_dtim_skip,
                listen_interval, monitor_interval)
            if ping_after_power_save and not ip_config_disable:
                assert self.ping(
                    device_ip=dut_add_dict['device_ip'],
                    ping_count=ping_count, retry_count=retry_count), \
                    "DUT NOT RESPONDING FOR PING REQUEST AFTER POWER SAVE......"

        return dut_add_dict

    def configure_dut_in_static_ip(self, wifi_dut, static_ip=None, static_subnet=None, static_gateway=None, vap_id=1):
        logger().info(f"********* configuring static ip {static_ip} to DUT *********")
        Ipconfig = wifi_dut.interfaces.wifi.start_ip(static_ip=static_ip, static_subnet=static_subnet,
                                                     static_gateway=static_gateway, vid=vap_id)
        return Ipconfig

    def ap_mode_clients_connection(self, wifi_dut, wifi_clients, channel=None, ssid=None, security=None, password=None,
                                   dtim_count=None, beacon_interval=None, ping_count=None, leave=True,
                                   no_of_clients=None, enable_data_rate=False, ht_caps=0, data_rate="54Mbps", max_clients=None):
        """This function is responsible for start the dut in ap mode and Initiating the connection from the raspberry
        :param wifi_dut:
        :param wifi_clients:
        :param channel:
        :param ssid:
        :param security:
        :param password:
        :param dtim_count
        :param beacon_interval
        :param ping_count
        :param leave
        :param no_of_clients
        :param enable_data_rate"""
        dut_add_dict = {}
        if enable_data_rate:
            logger().info(f" ********** data rate is {data_rate} ********* ")
            wifi_dut.interfaces.wifi.set_transmit_rate(rate_protocol="802.11g", data_rate=data_rate, interface="ap")
        time.sleep(2)

        logger().info(" ********** Starting DUT as an AP ********* ")
        wifi_dut.interfaces.wifi.start_ap(ssid=ssid, security=security, psk=password, channel=channel,
                                          dtim_beacon_count=dtim_count,
                                          beacon_interval=beacon_interval,
                                          ht_caps=ht_caps, max_clients=max_clients)

        for i in range(0, no_of_clients):
            connected = False
            logger().info(f"RASPI-STA{i + 1}:'{wifi_clients[i].name}' is joining to DUT-AP")
            wifi_clients[i].interfaces.wifi.join()
            time.sleep(5)
            dut_add_dict['dut_ip'] = wifi_dut.interfaces.wifi.ip.ip.decode('utf-8')
            logger().info(f"********* Dut IP **********: {dut_add_dict['dut_ip']}")
            for count in range(3):
                try:
                    logger().info(f"RASPI-STA{i + 1}:'{wifi_clients[i].name}' is successfully connected to DUT-AP")
                    logger().info(f"Initiating wlan ping from client '{wifi_clients[i].name}' to DUT")
                    dut_add_dict['rasp_mac_address'] = wifi_clients[i].interfaces.wifi.get_mac_address()
                    logger().info(f"raspi_mac: {dut_add_dict['rasp_mac_address']}")
                    dut_add_dict['client_ip'] = wifi_clients[i].interfaces.wifi.get_ip_address()
                    logger().info(f"Client_ip: {dut_add_dict['client_ip']}")
                    rc, stdout, stderr = wifi_clients[i].interfaces.wifi.shell.execute(
                        f"sudo ping -c {ping_count} {dut_add_dict['dut_ip']}")
                    assert rc == 0, f"RASPI-STA{i + 1} failed to ping DUT"
                    logger().info(f"\n{stdout.decode() if isinstance(stdout, bytes) else stdout}\n")
                    connected = True
                    break
                except:
                    logger().info(f"RASPI-STA{i + 1} failed to ping DUT...retry count -> {count + 1}")
                    time.sleep(10)
            assert connected, f"RASPI-STA{i + 1} is disconnected from DUT-AP"
        logger().info("Waiting 30 seconds to check connection stability")
        time.sleep(30)
        logger().info("Checking the connection stability after 30 seconds")
        for i in range(0, no_of_clients):
            for count in range(3):
                try:
                    logger().info(f"Initiating wlan ping from RASPI_STA{i + 1} for ping_count:{ping_count}")
                    rc, stdout, stderr = wifi_clients[i].interfaces.wifi.shell.execute(
                        f"sudo ping -c {ping_count} {dut_add_dict['dut_ip']}")
                    assert rc == 0, f"RASPI-STA{i + 1} failed to ping DUT"
                    logger().info(f"\n{stdout.decode() if isinstance(stdout, bytes) else stdout}\n")
                    logger().info(f"RASPI_STA{i + 1} is still connected to DUT-AP")
                    break
                except:
                    logger().info(f"RASPI-STA{i + 1} failed to ping DUT...retry count -> {count + 1}")
                    time.sleep(10)
        dut_mac_address = wifi_dut.interfaces.wifi.get_mac_address(2)
        logger().info(f"*********{dut_mac_address}**********")
        dut_add_dict['dut_mac_address'] = dut_mac_address
        logger().info(
            f"DUT MAC ADDRESS :  {dut_add_dict['dut_mac_address']}")
        if leave:
            for i in range(0, no_of_clients):
                logger().info(f'RASPI-STA{i + 1} Disconnecting from DUT-AP')
                wifi_clients[i].interfaces.wifi.leave()
        return dut_add_dict

    def join_sniffer_validation(self, wifi_access_point, wifi_sniffer, dut_mac_address, ap_mac_address, sniffer_filter,
                                power_save=True):
        """
        This function is responsible to validate Probe req, association, eapol, powermgmt bit packets in sniffer
        :param wifi_access_point:
        :param wifi_sniffer:
        :param dut_mac_address:
        :param ap_mac_address:
        :param sniffer_filter:
        :param power_save:
        :return:
        """
        self.basic_sniffer_validation_11ax(wifi_access_point, wifi_sniffer, dut_mac_address, ap_mac_address,
                                           sniffer_filter)

        packet_filter1 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(sa_addr=dut_mac_address,
                                                                                        da_addr=ap_mac_address,
                                                                                        filter_name='probe_req_response')
        packet_filter2 = sniffer_filter.interfaces.ws_sniffer_filter. \
            get_sniffer_filter(sa_addr=dut_mac_address, da_addr=ap_mac_address,
                               filter_name='assoc_req_resp_eapol_4_way_handshake')
        packet_filter3 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(sa_addr=dut_mac_address,
                                                                                        da_addr=ap_mac_address,
                                                                                        filter_name='power_mgmt_bit')

        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter1)['packet_count'], \
            'Sniffer: Unable to find probe_req_response packet in sniffer'
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter2)['packet_count'], \
            'Sniffer: Unable to find assoc_req_resp_eapol_4_way_handshake packet in sniffer'
        if power_save:
            assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter3)['packet_count'], \
                'Sniffer: Unable to find power management bit 1 in sniffer '

    def basic_sniffer_validation_11ax(self, wifi_access_point, wifi_sniffer, dut_mac_address, ap_mac_address,
                                      sniffer_filter):
        """
        This function is responsible for verification of basic 11ax packets.
        :param wifi_access_point:
        :param wifi_sniffer:
        :param dut_mac_address:
        :param ap_mac_address:
        :param sniffer_filter:
        :return:
        """
        if "11ax" not in str(wifi_access_point.interfaces.wifi.standard):
            return

        packet_filter1 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(sa_addr={ap_mac_address},
                                                                                        filter_name='beacon_HE_capability')
        packet_filter2 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(sa_addr={dut_mac_address},
                                                                                        da_addr={ap_mac_address},
                                                                                        filter_name='probe_request_HE')
        packet_filter3 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(sa_addr={dut_mac_address},
                                                                                        da_addr={ap_mac_address},
                                                                                        filter_name='association_request_HE')
        packet_filter4 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(ta_addr={dut_mac_address},
                                                                                        ra_addr={ap_mac_address},
                                                                                        filter_name='data_packets_HE')

        logger().info("Validating beacon with HE information")
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter1)[
            'packet_count'], 'Unable to find beacon with HE capability in sniffer'

        logger().info("Validating Probe Req with HE information")
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter2)[
            'packet_count'], 'Unable to find Probe Req with HE capability in sniffer'

        logger().info("Validating Assoc Req with HE information")
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter3)[
            'packet_count'], 'Unable to find Assoc Req  with HE capability in sniffer'

        logger().info("Validating data packet with PHY type as 11ax")
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter4)[
            'packet_count'], 'Unable to find data packet with PHY type as 11ax in sniffer'

    def get_pkt_list_ipv6(self, wifi_sniffer, dut_mac_address, decryption_key: str, print_layers: list,
                          capture_filename,
                          ap_bssid, expected_filter="ipv6_state") -> Dict[
        str, int]:
        capture_list = []
        current_time = time.time()
        updated_capture_file = 'filter_' + capture_filename + '_' + str(
            datetime.fromtimestamp(current_time).strftime('%H_%M_%S'))
        file_name = f'./reports/{updated_capture_file}.pcap'
        local_capture_file = file_name
        wlan_filter_file = f"/tmp/{str(uuid.uuid4())[:8]}.pcap"
        packet_filter1 = f'(wlan.addr == {dut_mac_address}) || (wlan.addr == {ap_bssid})'
        logger().info(f"packet_filter1 : {packet_filter1}")
        wifi_sniffer.interfaces.capture.shell(
            f"tshark -nr {wifi_sniffer.interfaces.capture.remote_capture_file} -Y '{packet_filter1}' -T fields -e "
            f"frame.number -w "
            f"{wlan_filter_file}")

        result = {'ipv6': [], 'icmpv6': [], 'dhcpv6': [], 'ipv6_state': ""}
        with wifi_sniffer.interfaces.capture.shell.client.open_sftp() as sftp:
            sftp.get(wlan_filter_file, local_capture_file)
        for packet in wifi_sniffer.interfaces.capture.iter_packets(
                decrypt_packets=True,
                encryption_type="WPA-PWD",
                decryption_key=decryption_key,
                capture_file_filter=local_capture_file
                ):
            for layer in packet.layers:
                layer_name = str(layer.layer_name.lower())
                logger().info(f"layer_name : {layer_name}")

                if expected_filter == "ipv6_state":
                    if layer_name == "icmpv6" and layer_name in print_layers:
                        icmpv6_layer = str(layer)
                        logger().info(f"icmpv6_layer:{icmpv6_layer}")
                        result['icmpv6'].append(icmpv6_layer)

                        if re.search(".*Neighbor Solicitation", icmpv6_layer):
                            logger().info(f"Neighbor Solicitation {icmpv6_layer}")

                        if re.search(".*Router Advertisement", icmpv6_layer):
                            logger().info(f"Router Advertisement {icmpv6_layer}")
                            x = re.findall(r"Managed address configuration: (.*)", icmpv6_layer)
                            logger().info(f"Managed Address configuration: {x}")
                            if x and x[0] == "Set":
                                logger().info(f"Managed Address configuration set")
                                result['ipv6_state'] = 1
                            else:
                                logger().info(f"Managed Address configuration not set")
                                result['ipv6_state'] = 0
                            return result

    def ssl_packet_decryption(self, wifi_sniffer, decryption_key, dut_mac_address, decrypt_layers: list,
                              capture_filename, ap_bssid=None, mode=0, handshake_pkt=False, get_cipher=False) -> Dict:
        """
        This function is responsible to decrypt and validate ssl, dtls, and related packets in sniffer.
        :param wifi_sniffer: Sniffer fixture to access the sniffer device.
        :param decryption_key: Decryption key value which is required to decrypt packets, ex: passphrase_value:ssid_name
        :param dut_mac_address: Mac address of the DUT.
        :param decrypt_layers: List of layer name that needs to be decrypted, ex: ['ntp', 'tls', 'tcp', 'http', 'websocket','dtls'].
        :param capture_filename: Name of the sniffer capture file.
        :param ap_bssid: BSSID of wifi_access_point used in test.
        :param mode: Depend on test case requirement, value can be 0 or 1.
        :param handshake_pkt: Depend on test case requirement, Boolean value to display handshake packet captures.
        :param get_cipher: Depend on test case requirement, Boolean value to get cipher list if required.
        :return: result{'ntp': List, 'tls': List, 'tcp': List, 'http': List, 'websocket': List, 'cipher': List, 'dtls': List,}.
        """
        logger().info("\n\n ***** SSL Packet decryption start ***** \n\n")
        current_time = time.time()
        updated_capture_file = 'filter_' + capture_filename + '_' + str(
            datetime.fromtimestamp(current_time).strftime('%H_%M_%S'))
        file_name = f'./reports/{updated_capture_file}.pcap'
        local_capture_file = file_name
        wlan_filter_file = f"/tmp/{str(uuid.uuid4())[:8]}.pcap"
        packet_filter1 = f'(wlan.addr == {dut_mac_address}) && (wlan.addr == {ap_bssid})'
        wifi_sniffer.interfaces.capture.shell(
            f"tshark -nr {wifi_sniffer.interfaces.capture.remote_capture_file} -Y '{packet_filter1}' -T fields -e "
            f"frame.number -w "
            f"{wlan_filter_file}")
        with wifi_sniffer.interfaces.capture.shell.client.open_sftp() as sftp:
            sftp.get(wlan_filter_file, local_capture_file)
        cipher_count = 0
        source_ip = ""
        destination_ip = ""
        ta_address = ""
        result = {'ntp': [], 'tls': [], 'tcp': [], 'cipher': [], 'ftp': [], 'igmp': [], 'websocket': [], 'dtls': []}
        for packet in wifi_sniffer.interfaces.capture.iter_packets(
                decrypt_packets=True,
                encryption_type="WPA-PWD",
                decryption_key=decryption_key,
                capture_file_filter=local_capture_file):
            for layer in packet.layers:
                layer_name = str(layer.layer_name.lower())

                # To get http related packets
                if layer_name == "http" and layer_name in decrypt_layers:
                    http_layer = str(layer)
                    logger().info(f"http layer {http_layer}")

                # To get websocket related packets
                # if layer_name == "websocket" and layer_name in decrypt_layers:
                #     http_layer = str(layer)
                #     if re.search(".*Opcode: Ping", http_layer):
                #         logger().info(f"PING PACKET {http_layer}")
                #     elif re.search(".*Opcode: Pong", http_layer):
                #         logger().info(f"PONG PACKET {http_layer}")
                if "websocket" in decrypt_layers and layer_name == "ip":
                    ip_layer = str(layer)
                    layer_ip = ip_layer.split("\n")
                    for count in layer_ip:
                        if "Source" in count:
                            source_ip = count.split(":")[1].strip()
                        if "Destination" in count:
                            destination_ip = count.split(":")[1].strip()
                if layer_name == "websocket" and layer_name in decrypt_layers:
                    websocket_layer = str(layer)
                    result['websocket'].append(
                        tuple([websocket_layer, packet.sniff_timestamp, source_ip, destination_ip]))

                # To get tls related packets
                if layer_name == "wlan":
                    mac_layer = str(layer)
                    for count in mac_layer.split("\n"):
                        if "Transmitter address" in count:
                            ta_address = count.split(": ")[1].strip()
                if layer_name == "tls" and layer_name in decrypt_layers:
                    tls_layer = str(layer)
                    filtered_packet = str(packet)
                    filtered_packet = filtered_packet.split("Layer ")
                    tls_layer_pkt = ""
                    ra_address = ""
                    ta_address = ""
                    if handshake_pkt:
                        for layerp in filtered_packet:
                            if ((re.search(".*Receiver address:", layerp) and re.search(".*Transmitter address:",
                                                                                        layerp))
                                    or (re.search(".*TLS:", layerp))):
                                if re.search(".*TLS:", layerp):
                                    tls_layer_pkt = layerp
                                if (re.search(".*Receiver address:", layerp) and re.search(".*Transmitter address:",
                                                                                           layerp)):
                                    received = re.compile(r'Receiver address: (([0-9a-fA-F]:?){12})')
                                    receiver_address = re.search(received, layerp).group()
                                    ra_address = (re.search(received, layerp).group(1)).lower()
                                    transmit = re.compile(r'transmitter address: (([0-9a-fA-F]:?){12})')
                                    transmitter_address = re.search(transmit, layerp).group()
                                    ta_address = (re.search(transmit, layerp).group(1)).lower()
                                    dut_mac_address_mod = dut_mac_address.lower()
                                    ap_bssid_mod = ap_bssid.lower()
                                if ((ra_address == dut_mac_address_mod or ra_address == ap_bssid_mod) and (
                                        ta_address == dut_mac_address_mod or ta_address == ap_bssid_mod)) and tls_layer_pkt:
                                    logger().info(f">>>>>>{receiver_address}>>>>>>{transmitter_address}")
                                    logger().info(f"TLS HANDSHAKE PACKET{tls_layer_pkt}")
                                    result['tls'].append(tls_layer_pkt)
                    else:
                        tls_layer = str(layer)
                        if not ((re.search(".*Application Data Protocol:", tls_layer)) or (
                                re.search(".*Ignored Unknown Record", tls_layer))):
                            if (re.search(".*Receiver address:", mac_layer) and re.search(".*Transmitter address:",
                                                                                          mac_layer)):
                                received = re.compile(r'Receiver address: (([0-9a-fA-F]:?){12})')
                                receiver_address = re.search(received, mac_layer).group()
                                transmit = re.compile(r'Transmitter address: (([0-9a-fA-F]:?){12})')
                                transmitter_address = re.search(transmit, mac_layer).group()
                                logger().info(f">>>>>>{receiver_address}>>>>>>{transmitter_address}")
                            result['tls'].append(tls_layer)
                            logger().info(f"******************{tls_layer}")

                    if get_cipher:
                        if "Client Hello" not in tls_layer:
                            if mode == 0:
                                break
                        else:
                            for mac_addr in mac_layer.split("\n"):
                                if "Transmitter address" in mac_addr:
                                    ta_address = mac_addr.split(": ")[1].strip()
                            if ta_address == dut_mac_address:
                                logger().info(f"Cleint hello pkt sent by DUT {dut_mac_address}-> {tls_layer}")
                                cipher_suite_temp = []
                                tls_layer = tls_layer.split("\n")
                                for line in tls_layer:
                                    if "Cipher Suite:" in line:
                                        cipher_suite_temp.append(
                                            line.split("Cipher Suite:")[1].strip().split("(")[0].strip())
                                cipher_count = cipher_count + 1
                                result['cipher'].append(tuple([cipher_count, cipher_suite_temp]))
                                if mode == 0:
                                    break

                # To get tcp related packets
                if layer_name == "tcp" and layer_name in decrypt_layers:
                    tcp_layer = str(layer)
                    if (re.search(".*Receiver address:", mac_layer) and re.search(".*Transmitter address:",
                                                                                  mac_layer)):
                        receiver_address = re.search(r'Receiver address: (([0-9a-fA-F]:?){12})', mac_layer).group()
                        transmitter_address = re.search(r'Transmitter address: (([0-9a-fA-F]:?){12})',
                                                        mac_layer).group()
                        logger().info(f">>>>>>{receiver_address}>>>>>>{transmitter_address}")
                        logger().info(tcp_layer)
                        result['tcp'].append(tuple([tcp_layer, ta_address, packet.sniff_timestamp]))

                # To get ntp related packets
                if "ntp" in decrypt_layers and layer_name == "ip":
                    ip_layer = str(layer)
                    layer_ip = ip_layer.split("\n")
                    for count in layer_ip:
                        if "Source" in count:
                            source_ip = count.split(":")[1].strip()
                        if "Destination" in count:
                            destination_ip = count.split(":")[1].strip()
                if layer_name == "ntp" and layer_name in decrypt_layers:
                    ntp_layer = str(layer)
                    result['ntp'].append(tuple([ntp_layer, packet.sniff_timestamp, source_ip, destination_ip]))

                # To get igmp packets
                if layer_name == "igmp" and layer_name in decrypt_layers:
                    if ta_address == dut_mac_address:
                        igmp_layer = str(layer)
                        logger().info(
                            f"As per sniffer capture IGMP packets sent by DUT..{ta_address}  ->  {igmp_layer}")
                        result['igmp'].append(tuple([igmp_layer, packet.sniff_timestamp]))

                # To get ftp packets
                if layer_name == "ftp" and layer_name in decrypt_layers:
                    if ta_address == dut_mac_address:
                        ftp_layer = str(layer)
                        result['ftp'].append(tuple([ftp_layer, packet.sniff_timestamp]))

                # DTLS decryption (added logic)
                if layer_name == "dtls" and layer_name in decrypt_layers:
                    dtls_layer = str(layer)
                    result['dtls'].append(dtls_layer)
                    logger().info(f"******************DTLS: {dtls_layer}")

        return result

    def join_to_eap_network(self, wifi_dut, wifi_access_point, eap_type="tls", power_save=True, okc_value=0,
                            mode='power_save_low_latency', ping_count=10, retry_count=1, security="wpa2_enterprise",
                            ping_after_power_save=False, tcp_ip_bypass=False, channel=0, set_eap_cred=True):
        """This function is used to join to EAP network """

        dut_add_dict = {}

        logger().info("\n\n ***** Start check EAP connectivity ***** \n\n")

        scan_status, reason = self.scan(wifi_dut, scan_status=False, retry_count=retry_count, channel=channel)
        assert scan_status, f"....Scanning for AP failed..with reason: {reason}...."

        dut_add_dict['dut_mac_address'] = wifi_dut.interfaces.wifi.get_mac_address()
        logger().info(
            f"DUT MAC ADDRESS :  {dut_add_dict['dut_mac_address']}")

        if set_eap_cred:
            wifi_dut.interfaces.wifi.set_eap_credentials()

        # join method tries to connect to AP
        wifi_dut.interfaces.wifi.join(ssid=wifi_access_point.interfaces.wifi.ssid,
                                      passphrase=wifi_access_point.interfaces.wifi.passphrase,
                                      security=security, uid="user1", enc=eap_type)
        if not tcp_ip_bypass:
            # configure_ip tries to assign IP ADDRESS through DHCP
            ip_status, ip_config = self.configure_ip(wifi_dut, ip_status=False, retry_count=retry_count)
            assert ip_status, f"....Unable to assign IP ADDRESS through DHCP with reason: {ip_config}...."
            device_ip = wifi_dut.interfaces.wifi.get_device_ip(ip_config)
            logger().info(f"DUT ip: {device_ip}")
            # we fetch the ip address and mac_address
            dut_add_dict['device_ip'] = device_ip
            logger().info(
                f"DUT MAC ADDRESS :  {dut_add_dict['dut_mac_address']} DUT IP ADDRESS : {dut_add_dict['device_ip']}")
            # ping to DUT before power_save
            status = self.ping(device_ip=dut_add_dict['device_ip'], ping_count=ping_count)
            assert status, "DUT NOT RESPONDING FOR PING REQUEST......"

        if power_save:
            logger().info(f"....Applying performance profile mode : {mode}")
            wifi_dut.interfaces.wifi.set_performance_profile(mode)
            wifi_dut.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                          psp_type=Si91xPowerSaveProcedureTypes.FastPowerSave)

            if ping_after_power_save:
                logger().info("....Pinging DUT after power-save....")
                status = self.ping(device_ip=dut_add_dict['device_ip'], ping_count=ping_count)
                assert status, "DUT NOT RESPONDING FOR PING REQUEST......"
        return dut_add_dict

    def join_to_wifi_network_with_rejoin(self, wifi_dut, wifi_access_point, rejoin_params: list, power_save=True,
                                         mode='power_save_low_latency', ping_count=10, retry_count=3,
                                         ping_after_ps=False, associated=False, listen_interval=0):
        """
        This function is used to join DUT to wifi_access_point along with rejoin parameter configurations
        param rejoin_params : List[max_retry_attempts, scan_interval, beacon_missed_count, first_time_retry_enable]
        """
        logger().info("Enabling rejoin parameters")
        wifi_dut.interfaces.wifi.wifi_set_advanced_client_config(max_retry_attempts=rejoin_params[0],
                                                                 scan_interval=rejoin_params[1],
                                                                 beacon_missed_count=rejoin_params[2],
                                                                 first_time_retry_enable=rejoin_params[3])
        return self.join_to_wifi_network(wifi_dut=wifi_dut, wifi_access_point=wifi_access_point, power_save=power_save,
                                         mode=mode, ping_count=ping_count, ping_after_power_save=ping_after_ps,
                                         retry_count=retry_count, associated=associated,
                                         listen_interval=listen_interval)

    @staticmethod
    def _net_perf_port_kwargs(port):
        """Return init_server/init_client kwargs with iperf host port override."""
        if port is None:
            return {}
        defaults = UtfConfig.instance().defaults.get("net_perf", {})
        host = deepcopy(defaults.get("host", {"TCP": {}, "UDP": {}}))
        for proto in host:
            host[proto]["port"] = port
        return {"host": host}

    @defaults("net_perf")
    def _run_nwp_traffic(
            self,
            wifi_dut=None,
            net_perf_client=None,
            protocol=None,
            device_ip=None,
            host_ip=None,
            timeout=30,
            traffic_type="TX",
            port=None,
            buffer_size_tcp=1024,
            buffer_size_udp=512,
            ip_version=6,
    ):
        """NWP/offload traffic via dual_stack.offload_iperf (local, not sl_collections)."""
        traffic_type = traffic_type
        protocol = protocol
        wifi = wifi_dut.interfaces.wifi
        net_perf = net_perf_client.interfaces.net_perf
        iperf_kwargs = self._net_perf_port_kwargs(port)
        if ip_version == 6:
            protocol_family = 10
        else:
            protocol_family = 2
        saved = wifi.is_external_stack_enabled
        wifi.is_external_stack_enabled = False
        try:
            if traffic_type == "TX":
                logger().info(
                    "starting the server from Remote device (NWP offload stack)"
                )
                net_perf.init_server(
                    host_ip=host_ip,
                    device_ip=device_ip,
                    protocol=protocol,
                    time_out=timeout,
                    version=ip_version,
                    **iperf_kwargs,
                )
                net_perf.start()
                time.sleep(2)
                iperf_port = port or net_perf.server_port
                if protocol == "TCP":
                    logger().info("sending data from DUT over NWP offload stack")
                    wifi.dual_stack_offload_iperf_command_handler(
                        family=protocol_family,
                        transfer_type=1,
                        protocol=6,
                        port=iperf_port,
                        remote_ip=host_ip,
                        size=buffer_size_tcp,
                        ttl=timeout,
                        throughput_type=1,
                        timeout=timeout + 20,
                    )
                elif protocol == "UDP":
                    logger().info("sending data from DUT over NWP offload stack")
                    wifi.dual_stack_offload_iperf_command_handler(
                        family=protocol_family,
                        transfer_type=2,
                        protocol=17,
                        port=iperf_port,
                        remote_ip=host_ip,
                        size=buffer_size_udp,
                        ttl=timeout,
                        throughput_type=2,
                        timeout=timeout + 20,
                    )
                tp = net_perf.process_output()
                assert tp is not None, "NWP offload throughput not found"
                logger().info("NWP offload data transfer is successful")
                net_perf.iperf_process.stop(5)
            else:
                net_perf.init_client(
                    host_ip=host_ip,
                    device_ip=device_ip,
                    protocol=protocol,
                    time_out=timeout,
                    version=ip_version,
                    bandwidth="60M",
                    **iperf_kwargs,
                )
                iperf_port = port or net_perf.client_port

                def start_client():
                    time.sleep(3)
                    net_perf.start()

                rx_thread = Thread(target=start_client, args=())
                rx_thread.start()
                if protocol == "TCP":
                    wifi.dual_stack_offload_iperf_command_handler(
                        family=protocol_family,
                        transfer_type=1,
                        protocol=6,
                        port=iperf_port,
                        remote_ip=host_ip,
                        size=buffer_size_tcp,
                        ttl=timeout,
                        throughput_type=3,
                        timeout=timeout + 20,
                    )
                elif protocol == "UDP":
                    wifi.dual_stack_offload_iperf_command_handler(
                        family=protocol_family,
                        transfer_type=2,
                        protocol=17,
                        port=iperf_port,
                        remote_ip=host_ip,
                        size=buffer_size_udp,
                        ttl=timeout,
                        throughput_type=4,
                        timeout=timeout + 20,
                    )
                rx_thread.join()
                logger().info("NWP offload data transfer is successful")
                net_perf.iperf_process.stop(5)
                time.sleep(5)
        finally:
            wifi.is_external_stack_enabled = saved

    @defaults("net_perf")
    def run_traffic(self, wifi_dut=None, net_perf_client=None, protocol=None, device_ip=None, host_ip=None,
                    timeout=60, traffic_type="TX", device=None, buffer_size_tcp=1460, buffer_size_udp=1470,
                    ip_version=4, async_socket=0, bandwidth="60M", ipv6_addr_type="global",
                    link_interface=None):

        if ip_version == 6:
            protocol_family = 24
        else:
            protocol_family = 2

        if traffic_type == "TX":
            logger().info("starting the server from Remote device")
            # starting iperf
            net_perf_client.interfaces.net_perf.init_server(host_ip=host_ip, device_ip=device_ip,
                                                            protocol=protocol, time_out=timeout, version=ip_version)
            net_perf_client.interfaces.net_perf.start()

            if protocol == "TCP":
                logger().info("sending data from DUT")
                wifi_dut.interfaces.wifi.iperf(family=protocol_family, transfer_type=1, protocol=6,
                                               local_port=net_perf_client.interfaces.net_perf.server_port,
                                               local_ip=device_ip, remote_ip=host_ip,
                                               remote_port=net_perf_client.interfaces.net_perf.server_port,
                                               size=buffer_size_tcp,
                                               ttl=timeout,
                                               throughput_type=1, qos=0,
                                               timeout=timeout + 20, ip_version=ip_version,
                                               async_socket=async_socket)
            elif protocol == "UDP":
                logger().info("sending data from DUT")
                wifi_dut.interfaces.wifi.iperf(family=protocol_family, transfer_type=2, protocol=17,
                                               local_port=net_perf_client.interfaces.net_perf.server_port,
                                               local_ip=device_ip, remote_ip=host_ip,
                                               remote_port=net_perf_client.interfaces.net_perf.server_port,
                                               size=buffer_size_udp,
                                               ttl=timeout,
                                               throughput_type=2, qos=0,
                                               timeout=timeout + 20, ip_version=ip_version,
                                               async_socket=async_socket)

            # # get and print throughput
            tp = net_perf_client.interfaces.net_perf.process_output()
            assert tp is not None, "Throughput not found"
            logger().info("data transfer is successful")
            net_perf_client.interfaces.net_perf.iperf_process.stop(5)

        if traffic_type == "RX":

            if ipv6_addr_type == "link":
                link_device_ip = device_ip + "%" + str(link_interface)
                logger().info(f"device_ip_link inside sl_collections {device_ip}")
            else:
                link_device_ip = device_ip

            net_perf_client.interfaces.net_perf.init_client(host_ip=host_ip, device_ip=link_device_ip,
                                                            protocol=protocol, time_out=timeout,
                                                            version=ip_version,
                                                            bandwidth=bandwidth)
            logger().info(f"Host IP: {host_ip}, Dut IP: {device_ip}, Protocol: {protocol}")
            logger().info(f"***** starting iperf ******")

            def start_client():
                time.sleep(3)
                logger().info(f"***** start listening  ******")
                net_perf_client.interfaces.net_perf.start()

            if protocol == "TCP":
                client_thread1 = Thread(target=start_client, args=(),)
                client_thread1.start()
                wifi_dut.interfaces.wifi.iperf(family=protocol_family, transfer_type=1, protocol=6,
                                               local_port=net_perf_client.interfaces.net_perf.client_port,
                                               local_ip=device_ip, remote_ip=host_ip,
                                               remote_port=net_perf_client.interfaces.net_perf.client_port,
                                               size=buffer_size_tcp, ttl=timeout, throughput_type=3, qos=0,
                                               timeout=timeout + 20, ip_version=ip_version, async_socket=async_socket)

                client_thread1.join()

            elif protocol == "UDP":
                client_thread2 = Thread(target=start_client, args=(), )
                client_thread2.start()
                wifi_dut.interfaces.wifi.iperf(family=protocol_family, transfer_type=2, protocol=17,
                                               local_port=net_perf_client.interfaces.net_perf.client_port,
                                               local_ip=device_ip, remote_ip=host_ip,
                                               remote_port=net_perf_client.interfaces.net_perf.client_port,
                                               size=buffer_size_udp, ttl=timeout, throughput_type=4, qos=0,
                                               timeout=timeout + 20, ip_version=ip_version, async_socket=async_socket)

                client_thread2.join()

            logger().info("data transfer is successful")
            net_perf_client.interfaces.net_perf.iperf_process.stop(5)
            time.sleep(5)

    def http_file_download(self, wifi_dut=None, http_server=None, device_ip=None, index_path=None, ping_count=10,
                           https=None, server_port=5001, retries=3):

        for retry in range(0, retries):
            try:
                wifi_dut.interfaces["http"] = wifi_dut.interfaces.wifi

                logger().info("checking weather server is running....")
                server_stat = http_server.interfaces.http.started
                if not server_stat:
                    http_server.interfaces.http.start_server()
                logger().info(f'http server state is {http_server.interfaces.http.started}')

                logger().info("fetching server ip....")
                host_ip = http_server.interfaces.http.hostname_or_ip_address
                logger().info(f"http_server_ip: {host_ip}")

                logger().info("pinging to http_server_ip....")
                status = ping(host_ip, ping_count)
                assert status, "unable to ping to http_server, please check test line connection and interface in harness"

                tcp_socket_id = wifi_dut.interfaces.wifi.socket()
                logger().info(f"Socket open successfully : {tcp_socket_id}")
                logger().info(
                    f"Successfully opened tcp client socket and socket id received is {tcp_socket_id} which is expected")
                bind_response = wifi_dut.interfaces.wifi.bind(socket_fd=tcp_socket_id,
                                                              device_ip=device_ip,
                                                              server_port=server_port,
                                                              asynch=0,
                                                              timeout=5)

                logger().info(f"Bind socket successfully: {bind_response}")

                time.sleep(5)
                if https:
                    wifi_dut.interfaces.wifi.bsdSetSocketOpt(socket_fd=tcp_socket_id, option_level='SOL_TCP',
                                                             option_name='TCP_ULP', option_val="tls")
                logger().info("DUT is connecting to server socket")
                wifi_dut.interfaces.wifi.bsdSocketConnect(socket_fd=tcp_socket_id, server_ip=host_ip,
                                                          server_port=http_server.interfaces.http.port)
                time.sleep(5)
                status = False
                data_downloaded = 0
                file_size_bytes = 0
                with TimeMeasurer() as t:
                    result = wifi_dut.interfaces.wifi.http_client_download(socket_id=tcp_socket_id,
                                                                           file_name=index_path,
                                                                           ip_address=host_ip,
                                                                           mode=https, timeout=1000, async_timeout=2000)
                logger().info(f"time taken for file download {t.duration}seconds")
                logger().info(f"result:{result}")
                data = re.findall(r"total received bytes: ([\d]*)", result.decode())
                if data and len(data) > 0:
                    data_downloaded = data[0]
                    logger().info(f"data_downloaded:{data_downloaded}")
                if t.duration and data_downloaded:
                    throughput_mbps = (int(data_downloaded) * 8) / (1000 * 1000 * t.duration)
                    logger().info(f"HTTP download throughput -> {throughput_mbps} Mbps")
                file_size = index_path.split(".htm")[0]
                logger().info(f"file_size :{file_size}")
                if "MB" in str(file_size):
                    file_size_bytes = int(file_size.split("MB")[0]) * 1024 * 1024
                if "KB" in str(file_size):
                    file_size_bytes = int(file_size.split("KB")[0]) * 1024
                logger().info(f"file_size_bytes:{file_size_bytes}")
                assert int(data_downloaded) >= file_size_bytes, "data downloaded and file size is not matching"
                logger().info(f"data downloaded is greater than or equal to file size")
                status = True
                logger().info(f"Http download is successful")
                break
            except:
                logger().info(f"http download failed retrying for {retry}")
                if retry == retries - 1:
                    assert status, f"Http download failed after {retries} times retry"
                logger().info(f"Http download is successful")
            finally:
                http_server.interfaces.http.stop_server()
                wifi_dut.interfaces.wifi.bsdSockClose(socket_fd=tcp_socket_id)


    def exception_handling(self, wifi_dut=None, exception=None):
        """
        Is to handle exception raised in testcase
        args:
        wifi_dut: dut
        EX: exception
        """
        recovery_error_codes = ['0xffffffe2', '0xffffffd5', '0xffffffeb', '0xffffffff', "0xfffffffd", "0xfffffff3", "-0x1"]
        automation_errors = ["IndexError", "AttributeError", "FileNotFoundError", "TypeError"]
        setup_errors = ["ConnectTimeoutError", "MaxRetryError", "DockerException", "SetupLevelError", "SerialException"]
        ex_type = exception.__class__.__name__
        logger().info(f"{ex_type} type occured")

        if ex_type == "AssertionError":
            error_match = re.search("status:(.*)", str(exception))
            if error_match:
                error_code = error_match.group(1)
                logger().info(f"error_code: {error_code}")
                logger().info(f"FW_FAILURE: Potential Firmware Failure")

                if error_code in recovery_error_codes:
                    logger().info("Need to perform device recovery when this type of exception raised")
                    wifi_dut.interfaces.wifi.reset()

                elif (("0x10025") in str(exception)) or (("0x10002") in str(exception)):
                    logger().info("DUT in associated/rejoin state,need to perform disconnect")
                    wifi_dut.interfaces.wifi.leave()


        elif ex_type in automation_errors:
            logger().info(f"AUTO_FAILURE: Potential Automation Failure")

        elif ex_type in setup_errors:
            logger().info(f"SETUP_FAILURE: Please fix the setup issues")

        raise exception

    def ap_sniffer_validation(self, wifi_sniffer=None, sniffer_filter=None, dut_mac_address=None,
                              rasp_mac_address=None):
        packet_filter1 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(
            sa_addr=dut_mac_address,
            filter_name='beacon')
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter1)['packet_count'], \
            'Unable to find  beacon in Sniffer'
        packet_filter2 = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter(
            sa_addr=dut_mac_address, da_addr=rasp_mac_address,
            filter_name='apmode_eapol')
        assert wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=packet_filter2)['packet_count'], \
            'Unable to find  apmode eapol in Sniffer'

    def scan_from_remote_device(self, wifi_dut=None, ble_client=None, ble_dut_address=None, services=None,
                                client_capability="NoInputNoOutput", pin_code="4321"):
        """
        This function is responsible for scanning from remote device
        """
        logger().info("Initiating scan from Remote device")
        # Begin Scanning for BLE devices
        ble_client_address = ble_client.interfaces.bluetooth.start_smp_scan(bt_dut_address=ble_dut_address,
                                                                            service_classes=services,
                                                                            capability=client_capability,
                                                                            pin_code=pin_code)
        assert ble_client_address is not None, "Unable to fetch bluetooth address from Remote device"
        logger().info(f"Started scan from remote BLE device")
        logger().info("\n***********{}**********\n".format(ble_client_address))
        found_devices = []
        for i in range(0, 5):
            found_devices = ble_client.interfaces.bluetooth.get_devices()
            logger().info("\n***scan results:{}**********\n".format(found_devices))
            time.sleep(5)
            if wifi_dut.interfaces.wifi.ble_address in found_devices:
                logger().info("DUT BLE address found in scan results")
                break
        assert wifi_dut.interfaces.wifi.ble_address in found_devices, "DUT not found in scan results"
        logger().info(f"DUT BLE address:'{ble_dut_address}' found in raspi scan results")
        ble_client.interfaces.bluetooth.stop_scanning()
        return ble_client_address

    def pair_and_connect(self, ble_client, ble_dut_address, timeout=10):
        logger().info("Connecting to the DUT with MAC address...")
        ble_client.interfaces.bluetooth.pair_and_connect(ble_dut_address, timeout=timeout)

    def read_passkey(self, wifi_dut, ble_client):
        pass_key_found = False
        passkey_event = None
        tw = Stopwatch()
        while tw.elapsed_sec < 60:
            events = wifi_dut.interfaces.wifi.get_async_events() #since_time=0
            logger().info(f"events : {events}")
            if not len(events):
                continue
            for event in events:
                logger().info(f"event.event_data : {event.event_data}")
                # if event.event_type == AsyncEventIdentifiers.BLE_SC_PASSKEY:
                if "passkey" in event.event_data:
                    passkey_event = event.event_data
                    logger().info(f"******SMP passkey event found: {passkey_event}*************")
                    break
            if passkey_event:
                break
        assert passkey_event, f"SMP passkey_event not found"
        passkey = re.findall(r"(?<=passkey: )\d*", passkey_event)
        assert passkey[0], f"passkey not found in the event data"
        pass_key_value = str(passkey[0])
        logger().info(f"passkey : {pass_key_value}")
        ble_client.interfaces.bluetooth.set_pin(pass_key_value)

    def connect_as_slave(self, wifi_dut, ble_client, ble_dut_address,
                         capablity=3, pin_code=4321, timeout=10):
        if capablity == 1:
            connect_thread = threading.Thread(target=self.pair_and_connect, args=(ble_client, ble_dut_address, timeout))
            connect_thread.start()
            time.sleep(3)
            passkey_thread = threading.Thread(target=self.read_passkey, args=(wifi_dut, ble_client))
            passkey_thread.start()
            passkey_thread.join()
            connect_thread.join()
        elif capablity == 3:
            self.pair_and_connect(ble_client, ble_dut_address, timeout=10)
        logger().info("Pairing and connection successful")

    def connect_as_master(self, wifi_dut, ble_client, ble_client_address, min_conn_interval,
                          max_conn_interval, conn_latency, supervision_timeout,
                          dev_state=8, capability=3,
                          client_capability="NoInputNoOutput", pin_code=4321,
                          timeout=120, ble_scan_interval=256, ble_scan_window=80,
                          ):
        def connect():
            wifi_dut.interfaces.wifi.ble_connect(ble_remote_dev_address=ble_client_address,
                                                 ble_conn_interval_min=int(int(min_conn_interval) / 1.25),
                                                 ble_conn_interval_max=int(int(max_conn_interval) / 1.25),
                                                 ble_conn_latency=conn_latency,
                                                 ble_supervision_timeout=supervision_timeout,
                                                 timeout=timeout,
                                                 async_timeout=timeout,
                                                 ble_scan_window=ble_scan_window,
                                                 ble_scan_interval=ble_scan_interval,)

        if (capability == 1) or (capability == 0):
            connect_thread = threading.Thread(target=connect)
            connect_thread.start()
            time.sleep(3)
            passkey_thread = threading.Thread(target=self.read_passkey, args=(wifi_dut, ble_client))
            passkey_thread.start()
            passkey_thread.join()
            connect_thread.join()

        elif capability == 3:
            connect()

        logger().info("Pairing and connection successful")

    def wait_for_event(self, wifi_dut=None, expected_event="RSI_BLE_ENCRYPT_STARTED_EVENT", timeout=160):
        """
        This function waits for a specific BLE event to occur within a timeout period.
        :param wifi_dut:
        :param expected_event:
        :param timeout: Maximum time to wait for the event in seconds.
        :return:
        """
        tw = Stopwatch()
        event_found = False
        while tw.elapsed_sec < timeout:
            events = wifi_dut.interfaces.wifi.get_async_events()
            for event in events:
                if expected_event in event.event_data:
                    logger().info(f"---------------->Event Data: {event.event_data}")
                    event_data = event.event_data
                    event_found = True
                    logger().info(f"Event found: {event_data}")
                    break
                else:
                    continue
            if event_found:
                break
        return event_found



    def connect_ble(self, wifi_dut=None, ble_client=None, ble_dut_address=None,
                    ble_client_address=None, mode="slave", retries=3, ble_pairing=0,
                    min_conn_interval=160, max_conn_interval=160,
                    conn_latency=0, supervision_timeout=3200, dev_state=8, capability=3,
                    client_capability="NoInputNoOutput", pin_code="4321",
                    timeout=5, ble_scan_interval=50, ble_scan_window=50):
        """
                This function will verifies the BLE connection API as mater/slave
                :param wifi_dut:  BLE DUT
                :param ble_client:  Remote Raspi BLE device
                :param ble_dut_address:   DUT BLE addr
                :param ble_client_address:  Remote BLE addr
                :param mode:  master/slave
                :param retries:  connection retries
                :param timeout:  timeout
                :return:
        """
        conn_status = False
        logger().info(f"Connecting ble_client to DUT with connection interval:{min_conn_interval}")

        if mode == "slave":
            if not ble_pairing:
                wifi_dut.interfaces.wifi.ble_advertising = False
                ble_client.interfaces.bluetooth.connect(dev_addr=ble_dut_address,
                                                        min_conn_interval=int(int(min_conn_interval) / 1.25),
                                                        max_conn_interval=int(int(max_conn_interval) / 1.25),
                                                        conn_latency=conn_latency,
                                                        supervision_timeout=supervision_timeout)
            else:
                self.connect_as_slave(wifi_dut, ble_client, ble_dut_address,
                                      capablity=capability, pin_code=pin_code, timeout=10
                                      )

                status = self.wait_for_event(wifi_dut=wifi_dut, expected_event="link_key")
                assert status, f"Expected event link_key not found in the events"
                logger().info("updating connection params")
                ble_client.interfaces.bluetooth.hci_tool_manager.update_conn(dev_addr=ble_dut_address,
                                                                             min_conn_interval=int(
                                                                                 int(min_conn_interval) / 1.25),
                                                                             max_conn_interval=int(
                                                                                 int(max_conn_interval) / 1.25),
                                                                             conn_latency=conn_latency,
                                                                             supervision_timeout=supervision_timeout)

        if mode == "master":
            wifi_dut.interfaces.wifi.ble_scanning = False
            self.connect_as_master(wifi_dut, ble_client, ble_client_address,
                                   min_conn_interval,
                                   max_conn_interval,
                                   conn_latency,
                                   supervision_timeout,
                                   dev_state, capability,
                                   client_capability, pin_code,
                                   timeout, ble_scan_interval, ble_scan_window)
            if ble_pairing:
                logger().info("Waiting for link key event")
                # Wait for the link key event to be received
                status = self.wait_for_event(wifi_dut=wifi_dut, expected_event="link_key")
                logger().info(f"Expected event link_key found status:{status}")

        time.sleep(timeout)
        logger().info("Checking connection status of BLE")
        state = wifi_dut.interfaces.wifi.ble_get_device_state()
        state_int = int(state) if state.isdigit() else -1
        assert state_int == dev_state, "DUT BLE device is not in connected state"


    def scan_and_connect_from_remote(self, wifi_dut=None, ble_client=None,
                                     ble_dut_address=None, ble_pairing=0, services=None, dev_state=8,
                                     max_conn_interval=160,
                                     min_conn_interval=160,
                                     timeout=10,
                                     capability=3,
                                     client_capability="NoInputNoOutput",
                                     pin_code="4321"
                                     ):
        """
        This function is responsible for scanning from remote device and connect to DUT
        """

        ble_client_address = self.scan_from_remote_device(wifi_dut=wifi_dut, ble_client=ble_client,
                                                          ble_dut_address=ble_dut_address,
                                                          services=services,
                                                          client_capability=client_capability,
                                                          pin_code=pin_code)
        self.connect_ble(wifi_dut=wifi_dut, ble_client=ble_client, ble_dut_address=ble_dut_address,
                         mode="slave", retries=3, ble_pairing=ble_pairing, dev_state=dev_state,
                         max_conn_interval=max_conn_interval,
                         min_conn_interval=min_conn_interval,
                         timeout=timeout, capability=capability,
                         client_capability=client_capability, pin_code=pin_code)
        logger().info("BLE Connection success")
        return ble_client_address

    def advertise_remote_device(self, wifi_dut=None, ble_client=None, ble_dut_address=None, services=None,
                                pin_code="4321",
                                client_capability="NoInputNoOutput",
                                adv_int_min="0x20 0x00", adv_int_max="0x20 0x00",
                                ):
        logger().info(f"Advertising the Remote BLE device")
        ble_client_address = ble_client.interfaces.bluetooth.start_smp_adv_with_hci_tool(
            bt_dut_address=ble_dut_address,
            hci_adv_params=f"{adv_int_min} "  # Advertising_Interval_Min
                           f"{adv_int_max} "  # Advertising_Interval_Max
                           "0x00 "  # Advertising_Type 0x00-ADV_IND, 1-ADV_DIRECT_IND, 2-ADV_SCAN_IND, 3-ADV_NONCONN_IND
                           "0x00 "  # Own_Address_Type
                           "0x00 "  # Peer_Address_Type
                           "0x00 0x00 0x00 0x00 0x00 0x00 "  # Peer_Address
                           "0x07 "  # Advertising_Channel_Map
                           "0x00"  # Advertising_Filter_Policy
            ,
            service_classes=services,
            pin_code=pin_code,
            capability=client_capability
            )
        logger().info(f"Remote BLE device advertised with address: {ble_client_address}")
        assert ble_client_address is not None, "Unable to fetch bluetooth address from Remote device"
        logger().info(f"advertised remote BLE device")
        return ble_client_address

    def scan_and_connect_from_dut(self, wifi_dut=None, ble_client=None, ble_client_address=None,
                                  dev_state=8,
                                  max_conn_interval=160,
                                  min_conn_interval=160,
                                  ble_pairing=0,
                                  capability=3,
                                  client_capability="NoInputNoOutput",
                                  pin_code="4321"
                                  ):
        """
        This function is responsible for scanning from DUT and connect to remote device
        """
        wifi_dut.interfaces.wifi.ble_start_scanning(ble_client_address=ble_client_address, timeout=120)
        logger().info(f"Remote device found in scan results ,BLE scanning is successful")
        wifi_dut.interfaces.wifi.ble_stop_scanning()
        self.connect_ble(wifi_dut=wifi_dut, ble_client=ble_client,
                         ble_client_address=ble_client_address, mode="master",
                         dev_state=dev_state, max_conn_interval=max_conn_interval,
                         min_conn_interval=min_conn_interval, ble_pairing=ble_pairing,
                         capability=capability,
                         client_capability=client_capability,
                         pin_code=pin_code
                         )
        logger().info("BLE Connection success")

    def check_ble_advertise_functionality(self, wifi_dut=None, ble_client=None,
                                          ble_dut_address=None, ble_advertising_data="RS_HELPER_BLE_DUT",
                                          ble_address=None,
                                          ble_adv_type=128, ble_adv_filter_type=0,
                                          ble_addr_type=0, ble_dir_addr=None, ble_adv_int_min=256, ble_adv_int_max=512,
                                          own_addr_type=0, ble_adv_channel_map=7, timeout=10,
                                          capability=3,
                                          client_capability="NoInputNoOutput",
                                          pin_code="4321",
                                          services=None
                                          ):
        """
        This function is responsible for checking the advertise functionality of DUT
        :param wifi_dut: DUT
        :param ble_client: remote Raspi BLE device
        :param ble_dut_address: DUT BLE address
        :param ble_advertising_data: Adverstising data
        :param ble_address: Raspi ble address
        :param ble_adv_type: advertising type
        :param ble_adv_filter_type: advertising filter type
        :param ble_addr_type: address type
        :param ble_dir_addr: direct addr
        :param ble_adv_int_min: min advertising interval
        :param ble_adv_int_max:  max advertising interval
        :param own_addr_type: address type
        :param ble_adv_channel_map:
        :param timeout: timeout
        :return:
        """
        logger().info(f"Advertising the DUT")

        wifi_dut.interfaces.wifi.ble_start_advertising(ble_advertising_data=ble_advertising_data,
                                                       ble_address=ble_address, ble_adv_type=ble_adv_type,
                                                       ble_dir_addr=ble_dir_addr,
                                                       ble_adv_filter_type=ble_adv_filter_type,
                                                       ble_addr_type=ble_addr_type,
                                                       ble_adv_int_min=ble_adv_int_min,
                                                       ble_adv_int_max=ble_adv_int_max, own_addr_type=own_addr_type,
                                                       ble_adv_channel_map=ble_adv_channel_map, timeout=timeout)

        # Begin Scanning for BLE devices
        bt_client_address = self.scan_from_remote_device(wifi_dut=wifi_dut, ble_client=ble_client,
                                                         ble_dut_address=ble_dut_address,
                                                         client_capability=client_capability,
                                                         pin_code=pin_code,
                                                         services=services)
        return bt_client_address

    def check_ble_scan_functionality(self, wifi_dut=None, ble_client=None, ble_address=None, ble_client_address=None,
                                     ble_scan_type=1, ble_scan_filter_type=0, ble_scan_interval=256, ble_scan_window=80,
                                     ble_public_address="0", timeout=10, services=None,
                                     capability=3,
                                     client_capability="NoInputNoOutput",
                                     pin_code="4321",
                                     remote_adv_int_min="0xA0 0x00", remote_adv_int_max="0xA0 0x00"
                                     ):
        """
        :param wifi_dut: BLE DUT
        :param ble_client: Remote RASPI BLE client
        :param ble_address: DUT BLE addr
        :param ble_client_address: Remote RASPI BLE client addr
        :param ble_scan_type: BLE scan type
        :param ble_scan_filter_type: BLE scan filter type
        :param ble_scan_interval: BLE scan interval
        :param ble_scan_window:  BLE scan window
        :param ble_public_address: BLE public addr
        :param timeout: timeout
        :return:
        """
        # Advertise the remote device
        ble_client_address = self.advertise_remote_device(wifi_dut=wifi_dut, ble_client=ble_client,
                                                          ble_dut_address=ble_address, services=services,
                                                          client_capability=client_capability,
                                                          pin_code=pin_code,
                                                          adv_int_min=remote_adv_int_min,
                                                          adv_int_max=remote_adv_int_max
                                                          )
        # Start scanning
        wifi_dut.interfaces.wifi.ble_start_scanning(ble_address=ble_client_address,
                                                    ble_scan_type=ble_scan_type,
                                                    ble_scan_filter_type=ble_scan_filter_type,
                                                    ble_scan_interval=ble_scan_interval,
                                                    ble_scan_window=ble_scan_window,
                                                    ble_address_type=ble_public_address,
                                                    ble_client_address=ble_client_address,
                                                    timeout=timeout)
        logger().info(f"Remote device found in scan results ,BLE scanning is successful")
        return ble_client_address


    def ble_connection(self, wifi_dut=None, ble_client=None, ble_dut_address=None,
                       ble_client_address=None, mode="slave", retries=3, ble_pairing=0,
                       min_conn_interval=200, max_conn_interval=200,
                       conn_latency=0, supervision_timeout=3200, dev_state=8, timeout=10,
                       capability=3,
                       client_capability="NoInputNoOutput",
                       pin_code="4321",
                       services=None,  # services to be advertised
                       ):
        """
        This function will verifies the BLE connection functionality as mater/slave
        :param wifi_dut:  BLE DUT
        :param ble_client:  Remote Raspi BLE device
        :param ble_dut_address:   DUT BLE addr
        :param ble_client_address:  Remote BLE addr
        :param mode:  master/slave
        :param retries:  connection retries
        :param timeout:  timeout
        :return:
        """

        if mode == "slave":
            ble_client_address = self.check_ble_advertise_functionality(wifi_dut=wifi_dut, ble_client=ble_client,
                                                                        ble_dut_address=ble_dut_address, timeout=20,
                                                                        client_capability=client_capability,
                                                                        pin_code=pin_code,
                                                                        capability=capability,
                                                                        services=services,
                                                                        )
            ble_client.interfaces.bluetooth.stop_scanning()
            wifi_dut.interfaces.wifi.ble_scanning = False
            wifi_dut.interfaces.wifi.ble_advertising = False
            self.connect_ble(wifi_dut=wifi_dut, ble_client=ble_client, ble_dut_address=ble_dut_address,
                             ble_client_address=ble_client_address, mode=mode, retries=retries, ble_pairing=ble_pairing,
                             min_conn_interval=min_conn_interval, max_conn_interval=max_conn_interval,
                             conn_latency=conn_latency, supervision_timeout=supervision_timeout,
                             dev_state=dev_state, timeout=timeout, capability=capability,
                             pin_code=pin_code, client_capability=client_capability)
            logger().info("BLE Connection success")

        if mode == "master":
            ble_client_address = self.check_ble_scan_functionality(wifi_dut=wifi_dut, ble_client=ble_client,
                                                                   ble_address=ble_dut_address, timeout=60,
                                                                   capability=capability,
                                                                   pin_code=pin_code,
                                                                   client_capability=client_capability,
                                                                   services=services,
                                                                   )

            wifi_dut.interfaces.wifi.ble_stop_scanning()
            time.sleep(5)
            self.connect_ble(wifi_dut=wifi_dut, ble_client=ble_client, ble_dut_address=ble_dut_address,
                             ble_client_address=ble_client_address, mode=mode, retries=retries, ble_pairing=ble_pairing,
                             min_conn_interval=min_conn_interval, max_conn_interval=max_conn_interval,
                             conn_latency=conn_latency, supervision_timeout=supervision_timeout,
                             dev_state=dev_state, timeout=timeout,
                             capability=capability, pin_code=pin_code, client_capability=client_capability)
            logger().info("BLE Connection success")

        return ble_client_address

    def ble_disconnect(self, wifi_dut=None, ble_client=None, disconnect_from="remote", ble_dut_address=None,
                       ble_client_address=None):
        """
        This function is responsible for disconnecting the BLE connection
        """
        logger().info("Checking connection status of BLE")
        state = wifi_dut.interfaces.wifi.ble_get_device_state()
        state_int = int(state) if state.isdigit() else -1
        assert state_int == BLEDeviceState.Connected, "DUT BLE device is not in connected state"

        if disconnect_from == "remote":
            logger().info(f"Initiating BLE disconnection from raspi")
            ble_client.interfaces.bluetooth.disconnect(ble_dut_address)
        else:
            logger().info(f"Initiating BLE disconnection from DUT")
            wifi_dut.interfaces.wifi.ble_disconnect(ble_remote_dev_address=ble_client_address)
        ble_client.interfaces.bluetooth.close()


    def cleanup_ble(self, ble_dut=None, ble_client=None, ble_client_address=None, ble_dut_address=None):
        """
        Cleanup BLE connections and states for both single and multiple clients
        Args:
            ble_dut: BLE device under test
            ble_client: Single BLE client or list of BLE clients
            ble_client_address: Single client address or list of client addresses
            ble_dut_address: DUT address
        """
        logger().info("Checking connection status of BLE")
        state = ble_dut.interfaces.wifi.ble_get_device_state()
        state_int = int(state) if state.isdigit() else -1

        # Convert single client/address to list for uniform handling
        if ble_client is not None and not isinstance(ble_client, list):
            ble_client = [ble_client]
        if ble_client_address is not None and not isinstance(ble_client_address, list):
            ble_client_address = [ble_client_address]

        if state_int == 8:  # Connected state
            logger().info("Device is in connected status, trying to disconnect")
            if ble_client_address:
                for addr in ble_client_address:
                    ble_dut.interfaces.wifi.ble_disconnect(ble_remote_dev_address=addr)
        elif state_int == 2:  # Scanning state
            logger().info("Device is in scanning status, trying to stop scanning")
            ble_dut.interfaces.wifi.ble_stop_scanning()
        elif state_int == 1:  # Advertising state
            logger().info("Device is in advertising status, trying to stop advertising")
            ble_dut.interfaces.wifi.ble_stop_advertising()
        elif state_int == 3:  # Both scanning and advertising
            logger().info("Device is in scanning status, trying to stop scanning")
            ble_dut.interfaces.wifi.ble_stop_scanning()
            logger().info("Device is in advertising status, trying to stop advertising")
            ble_dut.interfaces.wifi.ble_stop_advertising()
        elif state_int == 9:  # Connected state
            logger().info("Device is in connected status, trying to disconnect")
            if ble_client_address:
                for addr in ble_client_address:
                    ble_dut.interfaces.wifi.ble_disconnect(ble_remote_dev_address=addr)
        elif state_int == 0:
            logger().info("Device is in disconnected status, no action needed")
            ble_dut.interfaces.wifi.ble_advertising = False
            ble_dut.interfaces.wifi.ble_scanning = False
            ble_dut.interfaces.wifi.ble_connected = False

        else:
            logger().info("Device is in unknown state")
            ble_dut.interfaces.wifi.is_dut_bad_state = True
        # Close all client connections
        if ble_client:
            dut_addresses = (
                ble_dut_address
                if isinstance(ble_dut_address, list)
                else [ble_dut_address]
            )
            for client in ble_client:
                for dut_address in dut_addresses:
                    if not dut_address:
                        continue
                    try:
                        # BlueZ keeps a paired/cached peer after disconnect.
                        # Remove the DUT before closing the client so every
                        # testcase begins with a fresh BLE-device state.
                        client.interfaces.bluetooth.remove_device(dut_address)
                        logger().info(f"Removed BLE device from client: {dut_address}")
                    except Exception as e:
                        logger().warning(
                            f"Failed to remove BLE device {dut_address}: {str(e)}"
                        )
                try:
                    client.interfaces.bluetooth.close()
                except Exception as e:
                    logger().warning(f"Failed to close client connection: {str(e)}")


        logger().info(" *************DUT Cleanup Success *******************")

    def service_discovery_on_remote(self, ble_client, service_uid=None, char_uid=None):
        time.sleep(3)
        servs, chars = ble_client.interfaces.bluetooth.gatt_adapter.resolve_all_services_characteristics()
        time.sleep(5)
        logger().info(f"{servs} {chars}")
        assert len(servs) > 0, "no services fetched"
        assert len(chars) > 0, "fetched characters are empty"

        char_path, char_props = ble_client.interfaces.bluetooth.gatt_adapter.resolve_characteristic(
            services=servs,
            service_uid=service_uid,
            char_uid=char_uid)
        time.sleep(5)
        logger().info(f"{char_props}")
        assert char_path, "characters are empty"
        assert len(char_props) > 0, "length of characters is 0"
        return char_path

    def service_discovery_on_dut(self, ble_dut=None, ble_client_address=None, service_uuid=None,
                                 char_uuid=None, characteristic=None):
        logger().info("\n\n ***** Performing GATT profile discovery on Remote (raspi)  ***** \n\n\n")
        # get all profiles
        uuids = ble_dut.interfaces.wifi.ble_get_profiles_async(ble_remote_dev_address=ble_client_address,
                                                               async_timeout=60)
        logger().info(f"UUIds {uuids}")
        assert len(uuids) > 0, "uuids are empty"
        #  resolve profile
        start_handle, end_handle, data = ble_dut.interfaces.wifi.ble_get_profile_async(
            ble_remote_dev_address=ble_client_address,
            uuid=int(service_uuid, 16),
            async_timeout=60)
        logger().info(f"start_handle:{start_handle}, end_handle:{end_handle}")
        assert start_handle is not None
        assert end_handle is not None
        #
        char_uuids, write_handles, char_properties = ble_dut.interfaces.wifi.ble_get_char_services_async(
            ble_remote_dev_address=ble_client_address,
            start_handle=int(start_handle, 16),
            end_handle=int(end_handle, 16),
            async_timeout=60)
        logger().info(
            f"characteristics uuids :{char_uuids}  write_handles{write_handles} : Characteristics_properties"
            f"{char_properties}")

        assert char_uuid in char_uuids, "Unable to find {} uuid".format(char_uuid)
        index = char_uuids.index(char_uuid)
        logger().info(f"UUID's are:{char_uuids}")
        logger().info(f"write_handles:{write_handles}")
        logger().info(f"index:{index}")
        assert char_properties[index].isdigit(), "Character property found is not an integer"
        assert characteristic.prop_int == int(char_properties[index]), "Invalid character property found"

        write_handle = int(write_handles[index], 16)
        logger().info(f"write_handle:{write_handle}")
        assert write_handle > 0, "Unable to get write handle for configured service"

        return write_handle

    def sniffer_validation_for_packet_filters(self, wifi_sniffer, sniffer_filter, *device_address,
                                              packet_filter2=False, **filter_name):
        """
        This function is responsible to validate single/multiple sniffer filter in single execution
        :param wifi_sniffer:
        :param sniffer_filter:
        :param device_address: dict = This dictionary contains all required device address information
                device_address = {'sa_addr': dut_mac_address, 'da_addr': ap_mac_address}
		:packet_filter2: Boolean
        :param filter_name: dict = This dictionary contains user specific multiple/single sniffer filter info.
                filters_name = {1: 'probe_request', 2: 'association_request'}
        :return: dict = contains all results in boolean form
        """
        packet_filter_dict = {}
        result = {}
        da_addr = None,
        ta_addr = None,
        ra_addr = None,
        sa_addr = None
        wlan_addr = None,
        radio_ch = None,
        wlan_ssid = None,

        address_list = list(device_address[0].keys())
        logger().info(address_list)
        if 'sa_addr' in address_list:
            sa_addr = device_address[0]['sa_addr']
        if 'da_addr' in address_list:
            da_addr = device_address[0]['da_addr']
        if 'ta_addr' in address_list:
            ta_addr = device_address[0]['ta_addr']
        if 'ra_addr' in address_list:
            ra_addr = device_address[0]['ra_addr']
        if 'wlan_addr' in address_list:
            wlan_addr = device_address[0]['wlan_addr']
        if 'radio_ch' in address_list:
            radio_ch = device_address[0]['radio_ch']
        if 'wlan_ssid' in address_list:
            wlan_ssid = device_address[0]['wlan_ssid']

        filter_dict = dict(list(filter_name.values())[0])
        if len(filter_dict.keys()) == 0 or len(filter_dict.values()) == 0:
            assert False, "No filter is provided thru program, Please check..."

        for i in range(1, len(filter_dict.keys()) + 1):
            packet_filter = 'packet_filter' + str(i)
            packet_filter_dict[packet_filter] = sniffer_filter.interfaces.ws_sniffer_filter.get_sniffer_filter \
                (sa_addr=sa_addr, da_addr=da_addr, ta_addr=ta_addr, ra_addr=ra_addr, wlan_addr=wlan_addr,
                 radio_ch=radio_ch, wlan_ssid=wlan_ssid, filter_name=filter_dict[i])
            logger().info(f'\n\n *** Packet Filter: {packet_filter_dict[packet_filter]} ***\n\n')

            result[i] = wifi_sniffer.interfaces.capture.sniffer_validation(packet_filter1=
                                                                           packet_filter_dict[packet_filter],
                                                                           packet_filter2=packet_filter2)[
                'packet_count']
            if not result[i]:
                logger().info(f"\n *** Unable to find {filter_dict[i]} packet in sniffer capture ***\n")
            else:
                logger().info(f"\n *** Expected packet {filter_dict[i]} found in sniffer capture ***\n")

        logger().info(packet_filter_dict)
        return result

    def reset_USB_Device(self):
        USB_DEV_NAME = "1915:522a"
        # Same as _IO('U', 20) constant in the linux kernel.
        CONST_USB_DEV_FS_RESET_CODE = ord('U') << (4 * 2) | 20
        # usb_dev_path = ""

        # Based on 'lsusb' command, get the usb device path in the following format -
        # /dev/bus/usb/<busnum>/<devnum>
        proc = subprocess.Popen(['lsusb'], stdout=subprocess.PIPE)
        cmd_output = proc.communicate()[0]
        usb_device_list = cmd_output.decode('utf8').split('\n')
        for device in usb_device_list:
            if USB_DEV_NAME in device:
                logger().info("device: ".format(device))
                usb_dev_details = device.split()
                usb_bus = usb_dev_details[1]
                usb_dev = usb_dev_details[3][:3]
                usb_dev_path = '/dev/bus/usb/%s/%s' % (usb_bus, usb_dev)
        try:
            if usb_dev_path != "":
                logger().info("Trying to reset USB Device: " + usb_dev_path)
                device_file = os.open(usb_dev_path, os.O_WRONLY)
                fcntl.ioctl(device_file, CONST_USB_DEV_FS_RESET_CODE, 0)
                logger().info("USB Device reset successful.")
            else:
                logger().info("Device not found.")
        except:
            assert False, '\n\n ***Setup Issue*** Unable to detect Sweyntooth (NRF) Board.. Please reconnect the Board..!!\n\n'
        finally:
            if device_file:
                os.close(device_file)

    # helper api for congfiguring AE advertising parameters
    def ble_ae_set_params(self, pheripheral_dev, adv_handle=0, adv_event_prop=1, adv_min_interval=32,
                          adv_max_interval=32,
                          own_address_type=0, peer_addr_type=0, peer_address="00:00:00:00:00:00", pri_adv_phy=1,
                          sec_adv_max_skip=1, sec_adv_phy=1, scan_req_notify_enable=1, adv_filter_policy=0, timeout=30):
        logger().info("\n\n ***** Configuring AE advertising parameters ***** \n\n")
        pheripheral_dev.interfaces.bluetooth.ble_set_ae_params(adv_handle=adv_handle, adv_event_prop=adv_event_prop,
                                                               primary_adv_intterval_min=adv_min_interval,
                                                               primary_adv_intterval_max=adv_max_interval,
                                                               own_addr_type=own_address_type,
                                                               peer_addr_type=peer_addr_type,
                                                               remote_dev_addr=peer_address,
                                                               primary_adv_phy=pri_adv_phy,
                                                               sec_adv_max_skip=sec_adv_max_skip,
                                                               sec_adv_phy=sec_adv_phy,
                                                               scan_req_notify_enable=scan_req_notify_enable,
                                                               adv_filter_policy=adv_filter_policy,
                                                               timeout=timeout)
        logger().info(f"\n\n _______________________________________________________________\n\
                    ***** Successfully Configured below AE advertising parameters ***** \n\
                    adv_handle                  : {hex(adv_handle)}  \n\
                    adv_event_prop              : {hex(adv_event_prop)} \n\
                    min interval                : {adv_min_interval * 0.625}ms \n\
                    max interval                : {adv_max_interval * 0.625}ms \n\
                    own_address_type            : {self.address_type_list[own_address_type]} \n\
                    peer_addr_type              : {self.address_type_list[peer_addr_type]} \n\
                    peer_address                : {peer_address}  \n\
                    filter_policy               : {adv_filter_policy} \n\
                    Primary_Advertising_PHY     : {self.phy_channel[pri_adv_phy]}\n\
                    Sec_adv_max_skip            : {hex(sec_adv_max_skip)}\n\
                    Secondary_Advertising_PHY   : {self.phy_channel[sec_adv_phy]}\n\
                    Scan_req_notify_enable      : {scan_req_notify_enable}\n\
                    adv_tx_power                : 15\n\
                    primary_adv_chnl_map        : 7\n\
                    adv_sid                     : 0\n\
                      _______________________________________________________________\n")

    def ble_ae_start_advertising(self, ble_dut, dut_address, adv_enable=1, no_of_sets=1, adv_handle=0,
                                 duration=0, max_ae_events=0, adv_async_required=0):
        ble_dut.interfaces.bluetooth.ble_start_ae_advertising(adv_enable, no_of_sets, adv_handle, duration,
                                                              max_ae_events,
                                                              )
        time.sleep(2)
        if adv_enable == 1:
            logger().info(f"\n\n ***** AE advertising started successfully on {dut_address} ***** \n\n")
        else:
            logger().info(f"\n\n ***** AE advertising Stopped successfully on {dut_address} ***** \n\n")

    def start_periodic_adv(self, peripheral, adv_type, ble_dut_address,
                           central=None, data_len=0, data_len_s2=None,
                           pri_adv_phy=1, sec_adv_phy=1, adv_data="", adv_handle=0, duration=0, max_ae_events=0,
                           sec_adv_max_skip=1,
                           adv_async_required=0, peer_addr_type=0, random_address=None,
                           random_address_s2=None,
                           scan_req_notify_enable=1, scan_resp_len=0, whitelist=None, scanning_whitelist=None,
                           adv_filter_policy=0, powersave_p=None, adv_handle_s2=None, adv_type_s2=None, loop_count=0,
                           adv_data_type=None,
                           periodic_data_len=None,
                           invalid_data_hdl=None,
                           test_case_id=None, 
                           ble_sniffer=None,
                           ble_client_address=None):
        try:
 
            local_address = random_address if random_address and adv_handle == 0 else random_address_s2 if random_address_s2 and adv_handle == 1 else ble_dut_address
            logger().info(f"Local Device Address: {local_address}")
 
            if central:
                logger().info(f"BLE Client address: {ble_client_address}")
                assert ble_client_address, "failed to initiate ble in remote device"
            else:
                ble_client_address = "11:44:33:AA:BB:CC"#"D4:48:67:DD:CD:B1"
            adv_set = 2 if adv_handle_s2 else 1
           
            for i in range(adv_set):
                logger().info(f"\n\n ** ADV Set : {i } **\n\n")
                handle = adv_handle_s2 if i == 1 else adv_handle  # configuring handle as per adv_sets, 0=set1 and 1=set2
                adv_event_prop = adv_type_s2 if i == 1 else adv_type  # configuring adv_type as per adv sets
                data_len = data_len_s2 if i == 1 else data_len  # configuring data len as per adv set
                max_interval=512
                min_interval=256
                own_address_type = 0 #0 for public, 1 for randum
 
                if whitelist:
                    peripheral.interfaces.bluetooth.ble_add_white_list(remote_dev_addr=ble_dut_address,                                                remote_addr_type=0)
                if scanning_whitelist:
                    central.interfaces.wifi.ble_add_white_list(remote_dev_addr=ble_dut_address, remote_addr_type=0)
                if (random_address and i == 0) or (random_address_s2 and i == 1):
                    own_address_type = 1
 
                time.sleep(2)
                self.ble_ae_set_params(pheripheral_dev=peripheral, adv_event_prop=adv_event_prop,
                                       own_address_type=own_address_type,
                                       peer_addr_type=peer_addr_type, peer_address=ble_dut_address,
                                       adv_handle=handle,
                                       pri_adv_phy=pri_adv_phy, sec_adv_phy=sec_adv_phy,
                                       scan_req_notify_enable=scan_req_notify_enable,
                                       adv_filter_policy=adv_filter_policy,
                                       adv_min_interval=min_interval,
                                       adv_max_interval=max_interval,
                                       sec_adv_max_skip=sec_adv_max_skip)
                if adv_data_type == 2:
                    peripheral.interfaces.bluetooth.ble_app_set_periodic_ae_params(max_interval=max_interval,
                                                                                   min_interval=min_interval,
                                                                                   properties=64)
                if (random_address and i == 0) or (random_address_s2 and i == 1):
                    peripheral.interfaces.bluetooth.set_ae_set_random_address(
                        adv_handle=adv_handle if i == 0 else adv_handle_s2,
                        random_address=random_address if random_address else random_address_s2)
                    ble_dut_address = random_address if random_address else random_address_s2
                if adv_data:
                    if invalid_data_hdl:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=invalid_data_hdl)
                    if adv_data_type == 2:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle)
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=2,
                                             data_len=periodic_data_len, adv_data=adv_data, operation=3,
                                             adv_handle=handle)
                    else:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle)
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=3,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle,
                                             scan_resp_len=scan_resp_len)
                peripheral.interfaces.wifi.ble_get_max_adv_data_len(max_data_len=data_len)
                if not loop_count:
                    self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address, duration=duration,
                                                  max_ae_events=max_ae_events,
                                                  adv_handle=handle, adv_async_required=adv_async_required)
 
 
                    peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=1, handle=0)
                    time.sleep(15)
                    logger().info(f'started adveretise{ble_dut_address}')
 
            if powersave_p:
                logger().info("\n\nenable power save in ble dut")
                peripheral.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                            psp_type=Si91xPowerSaveProcedureTypes.MaxPowerSave)
                peripheral.interfaces.wifi.set_performance_profile(mode='power_save_low_latency')
                time.sleep(30)
 
        except Exception as e:
            logger().info(f'***********->{e}')

    def ble_set_ae_data(self, ble_dut, dut_address, adv_data_type=1, adv_handle=0, operation=0, data_len=0,
                        adv_data="AE", scan_resp_len=0):
        if scan_resp_len:
            data_len = scan_resp_len

        ble_dut.interfaces.bluetooth.ble_set_ae_data(type=adv_data_type, adv_handle=adv_handle, operation=operation,
                                                     data_len=data_len, data=adv_data)
        logger().info(
            f"\n\n ***** AE advertising Data configured successfully on {dut_address} with data type: {self.ae_data_type[adv_data_type]}***** \n\n")

    def AE_clean_up(self, ble_dut, ble_dut_address, adv_handle, le_remote_name, ae_adv_type, adv_data_type):
        logger().info("\n\n **** Performing clean up by Stopping Advertisement and Scanning..! ****\n\n")
        self.ble_ae_start_advertising(ble_dut=ble_dut, dut_address=ble_dut_address, adv_enable=0, adv_handle=adv_handle)
        if adv_data_type == 2:
            peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=0, handle=0)

    def verify_ae_scan(self, central, filter_duplicates=0, duration=0, period=0,
                       own_addr_type=0, random_address=None, interval=48, window=48,
                       error_expected=None, dont_cleanup=False):
        try:
            ble_dut_address = central.interfaces.bluetooth.ble_start(set_smp=1)
            logger().info("\n\n *** Setting AE scan parameters... ***\n\n")
            central.interfaces.bluetooth.ble_ae_set_scan_params(ble_addr_type=own_addr_type, ScanInterval=interval,
                                                                ScanWindow=window)
            if random_address:
                central.interfaces.bluetooth.set_ae_set_random_address()
            logger().info("\n\n *** Enabling AE scan... ***\n\n")
            central.interfaces.bluetooth.ble_ae_set_scan_enable(enable=1, filter_duplicates=filter_duplicates,
                                                                duration=duration, period=period)
        except Exception as e:
            if error_expected in str(e):
                logger().info(f"Got Expected error: {str(e)}")
            else:
                logger().info(f"Got Exception : {str(e)}")
                assert False, "Test case failed with Excepton {}".format(str(e))
        else:
            logger().info("\n\n **** Test case is passed successfully..! ****\n\n")
        finally:
            if not dont_cleanup:
                logger().info("\n\n *** Clean Up... Disabling AE scan... ***\n\n")
                central.interfaces.bluetooth.ble_ae_set_scan_enable(enable=0)

    def verify_adv(self, peripheral, adv_type, ble_dut_address,
                   central=None, print_all_adv_devices=1, data_len=0, data_len_s2=None,
                   pri_adv_phy=1, sec_adv_phy=1, adv_data="", adv_handle=0, duration=0, max_ae_events=0,
                   min_interval=48, max_interval=48, min_interval_s2=64, max_interval_s2=64, sec_adv_max_skip=1,
                   adv_async_required=0, own_address_type=0, peer_addr_type=0, random_address=None,
                   random_address_s2=None, ConnIntervalMax=160, ConnIntervalMin=160,
                   scan_req_notify_enable=1, scan_resp_len=0, whitelist=None, scanning_whitelist=None,
                   adv_filter_policy=0, scanning_filter_policy=0, powersave_p=None, powersave_c=None,
                   scanning_phys=1, adv_handle_s2=None, adv_type_s2=None, loop_count=0, adv_data_type=None,
                   ble_sniffer=None, wifi_sniffer=None, bt_sniffer=None, periodic_data_len=None,
                   test_case_id="nrf_logs", init_phys=7,
                   test_in_progress=False, dont_cleanup=False, error_expected="*****", invalid_data_hdl=None,
                   filter_duplicates=0, scan_duration=0, scan_period=0, scan_interval_pri=48, scan_interval_sec=48,
                   scan_window_pri=48, scan_window_sec=30, initiator_filter_policy=0, connection_time=30,
                   scan_type_pri=1, scan_type_sec=1, scan_set_2=0, stop_scan=1, ble_client_address=None, connect=None,
                   ble_addr_type=0, remote_addr_type=0):
        try:
            own_address_temp = ble_dut_address
            local_address = random_address if random_address and adv_handle == 0 else random_address_s2 if random_address_s2 and adv_handle == 1 else ble_dut_address
            logger().info(f"Local Device Address: {local_address}")

            if central:
                logger().info(f"BLE Client address: {ble_client_address}")
                assert ble_client_address, "failed to initiate ble in remote device"
            else:
                ble_client_address = "00:00:00:00:00:00"

            adv_set = 2 if adv_handle_s2 else 1
            # peripheral.interfaces.wifi.ble_get_max_no_of_supp_adv_sets(no_adv_sets=adv_set)
            for i in range(adv_set):
                logger().info(f"\n\n ** ADV Set : {i + 1} **\n\n")
                handle = adv_handle_s2 if i == 1 else adv_handle  # configuring handle as per adv_sets, 0=set1 and 1=set2
                adv_event_prop = adv_type_s2 if i == 1 else adv_type  # configuring adv_type as per adv sets
                data_len = data_len_s2 if i == 1 else data_len  # configuring data len as per adv set
                min_interval = min_interval_s2 if i == 1 else min_interval
                max_interval = max_interval_s2 if i == 1 else max_interval

                if whitelist:
                    peripheral.interfaces.bluetooth.ble_add_white_list(remote_dev_addr=ble_client_address,
                                                                       remote_addr_type=0)

                if scanning_whitelist:
                    central.interfaces.wifi.ble_add_white_list(remote_dev_addr=ble_dut_address, remote_addr_type=0)

                if (random_address and i == 0) or (random_address_s2 and i == 1):
                    own_address_type = 1

                self.ble_ae_set_params(pheripheral_dev=peripheral, adv_event_prop=adv_event_prop,
                                       own_address_type=own_address_type,
                                       peer_addr_type=peer_addr_type, peer_address=ble_client_address,
                                       adv_handle=handle,
                                       pri_adv_phy=pri_adv_phy, sec_adv_phy=sec_adv_phy,
                                       scan_req_notify_enable=scan_req_notify_enable,
                                       adv_filter_policy=adv_filter_policy, adv_min_interval=min_interval,
                                       adv_max_interval=max_interval,
                                       sec_adv_max_skip=sec_adv_max_skip)
                if adv_data_type == 2:
                    peripheral.interfaces.bluetooth.ble_app_set_periodic_ae_params(max_interval=max_interval,
                                                                                   min_interval=min_interval,
                                                                                   properties=64)

                if (random_address and i == 0) or (random_address_s2 and i == 1):
                    peripheral.interfaces.bluetooth.set_ae_set_random_address(
                        adv_handle=adv_handle if i == 0 else adv_handle_s2,
                        random_address=random_address if random_address else random_address_s2)
                    ble_dut_address = random_address if random_address else random_address_s2

                if adv_data:
                    if invalid_data_hdl:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=invalid_data_hdl)
                    if adv_data_type == 2:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle)
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=2,
                                             data_len=periodic_data_len, adv_data=adv_data, operation=3,
                                             adv_handle=handle)
                    else:
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=1,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle)
                        self.ble_set_ae_data(ble_dut=peripheral, dut_address=ble_dut_address, adv_data_type=3,
                                             data_len=data_len, adv_data=adv_data, adv_handle=handle,
                                             scan_resp_len=scan_resp_len)
                peripheral.interfaces.wifi.ble_get_max_adv_data_len(max_data_len=data_len)

                if ble_sniffer and i == 0:
                    ble_sniffer.interfaces.sniffer.init_sniffer()
                    ble_sniffer.interfaces.sniffer.start_capture()
                    time.sleep(5)

                if bt_sniffer:
                    bt_sniffer.interfaces.sniffer.init_sniffer()
                    bt_sniffer.interfaces.sniffer.start_capture(capture_file="ellisys/" + test_case_id)

                if not loop_count:
                    self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address, duration=duration,
                                                  max_ae_events=max_ae_events,
                                                  adv_handle=handle, adv_async_required=adv_async_required)
                    if adv_data_type == 2:
                        peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=1, handle=0)

                    if powersave_p:
                        logger().info("\n\nenable power save in ble dut")
                        peripheral.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                                        psp_type=Si91xPowerSaveProcedureTypes.MaxPowerSave)
                        peripheral.interfaces.wifi.set_performance_profile(mode='power_save_low_latency')
                    time.sleep(60)

                if loop_count:  ##adding a condition to perform multiple iteration test case
                    previous_pkt_count = 0
                    for j in range(loop_count):
                        logger().info(f"\n\n ** Iteration  : {j + 1} **\n\n")
                        self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address,
                                                      duration=duration,
                                                      max_ae_events=max_ae_events,
                                                      adv_handle=handle, adv_async_required=adv_async_required)
                        if adv_data_type == 2:
                            peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=1, handle=0)

                        if powersave_p:
                            logger().info("\n\nenable power save in ble dut")
                            peripheral.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                                            psp_type=Si91xPowerSaveProcedureTypes.MaxPowerSave)
                            peripheral.interfaces.wifi.set_performance_profile(mode='power_save_low_latency')
                        time.sleep(60)

                        if not max_ae_events:
                            # stopping AE advertising
                            self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address, adv_enable=0,
                                                          adv_handle=adv_handle)
                            if adv_data_type == 2:
                                peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=0, handle=0)

            time.sleep(10)

            if ble_sniffer:
                # Mapping Master and Slave Address for Adding devices for sniffer
                ble_dut_address_hex = re.split(":", ble_dut_address)
                ble_client_address_hex = re.split(":", ble_client_address)
                master_address = "0x"
                for hex_data_part in ble_dut_address_hex:
                    master_address = master_address + hex_data_part
                slave_address = "0x"
                for hex_data_part in ble_client_address_hex:
                    slave_address = slave_address + hex_data_part
                if random_address != random_address_s2:
                    own_address_temp_hex = re.split(":", own_address_temp)
                    own_address_temp_ = "0x"
                    for hex_data_part in own_address_temp_hex:
                        own_address_temp_ = own_address_temp_ + hex_data_part
                    ble_sniffer.interfaces.sniffer.select_bt_devices(
                        [own_address_temp_, slave_address, master_address])
                elif random_address:
                    ble_sniffer.interfaces.sniffer.select_bt_devices(
                        [slave_address, master_address])
                else:
                    ble_sniffer.interfaces.sniffer.select_bt_devices([master_address, slave_address])

            if bt_sniffer:
                bt_sniffer.interfaces.sniffer.stop_capture()
                log_file_size = os.path.getsize(bt_sniffer.interfaces.sniffer.capture_file)
                assert log_file_size > 0, "Sniffer didn't capture any packets...Setup Issue"
            if central and not loop_count:
                central.interfaces.wifi.ble_ae_set_scan_params(ble_addr_type=ble_addr_type,
                                                               scanning_phys=scanning_phys,
                                                               scanning_filter_policy=scanning_filter_policy,
                                                               scan_type=scan_type_pri,
                                                               scan_type_sec=scan_type_sec,
                                                               ScanInterval=scan_interval_pri,
                                                               ScanWindow=scan_window_pri,
                                                               remote_addr_type=remote_addr_type,
                                                               scan_interval_sec=scan_interval_sec,
                                                               scan_window_sec=scan_window_sec, )

                status = central.interfaces.wifi.ble_ae_set_scan_enable(enable=1,
                                                                        filter_duplicates=filter_duplicates,
                                                                        duration=scan_duration,
                                                                        period=scan_period,
                                                                        remote_address=ble_dut_address)
                logger().info(f"\n\n *** Scanning status: {status} ***\n\n")
                if "259" in str(status):
                    central.interfaces.wifi.is_dut_bad_state = True
                elif "19980" in str(status):
                    central.interfaces.wifi.ble_ae_set_scan_enable(enable=0,
                                                                   filter_duplicates=filter_duplicates,
                                                                   duration=scan_duration, period=scan_period,
                                                                   remote_address=ble_dut_address)
                    status = central.interfaces.wifi.ble_ae_set_scan_enable(enable=1,
                                                                            filter_duplicates=filter_duplicates,
                                                                            duration=scan_duration,
                                                                            period=scan_period,
                                                                            remote_address=ble_dut_address)
                    logger().info(f"\n\n *** Scanning status: {status} ***\n\n")

                
                if powersave_c:
                    logger().info("\n\nenable power save in ble dut")
                    central.interfaces.wifi.enable_bt_power_save(psp_mode=Si91xPowerSaveModes.PowerSaveMode2,
                                                                 psp_type=Si91xPowerSaveProcedureTypes.MaxPowerSave)
                    central.interfaces.wifi.set_performance_profile(mode='power_save_low_latency')

                time.sleep(30)
                if stop_scan:
                    try:
                        status = central.interfaces.wifi.ble_ae_set_scan_enable(enable=0,
                                                                                filter_duplicates=filter_duplicates,
                                                                                duration=scan_duration,
                                                                                period=scan_period,
                                                                                remote_address=ble_dut_address)
                        logger().info(f"\n\n *** Scanning status: {status} ***\n\n")
                        if "259" in str(status):
                            central.interfaces.wifi.is_dut_bad_state = True
                    except:
                        pass
                if connect:
                    central.interfaces.wifi.ble_extended_connect_with_params(remote_dev_addr=ble_dut_address,
                                                                             remote_addr_type=remote_addr_type,
                                                                             initiator_filter_policy=initiator_filter_policy,
                                                                             init_phys=init_phys,
                                                                             ConnIntervalMin=ConnIntervalMin,
                                                                             ConnIntervalMax=ConnIntervalMax)
                    time.sleep(60)
                    logger().info("\nChecking connection status of BLE")
                    state = central.interfaces.wifi.ble_get_device_state()
                    state_int = int(state) if state.isdigit() else -1
                    logger().info(f"\nDevice state: {state_int}")
                    assert state_int == BLEDeviceState.Connected, "DUT BLE device is not in connected state"
                    time.sleep(connection_time)
                    central.interfaces.wifi.ble_disconnect(ble_dut_address)
                    time.sleep(10)
                    logger().info("\nChecking connection status of BLE after disconnection")
                    state = central.interfaces.wifi.ble_get_device_state()
                    state_int = int(state) if state.isdigit() else -1
                    logger().info(f"\nDevice state: {state_int}")

            if ble_sniffer:
                ble_sniffer.interfaces.sniffer.stop_capture()
                captured_files = str(ble_sniffer.interfaces.sniffer.local_capture_files).split(';')

                time.sleep(30)
                exported_csv_file = ble_sniffer.interfaces.sniffer.export_to_csv("LE", "LE ADV")
                for captured_file in captured_files:
                    captured_file = captured_file.replace("/tmp/reports", "/app/reports")
                    file_size = os.path.getsize(captured_file)
                    assert file_size > 0

                exported_csv_file = exported_csv_file.replace("/tmp/reports", "/app/reports")
                file_size = os.path.getsize(exported_csv_file)
                assert file_size > 0
                sniffer_data_df = ble_sniffer.interfaces.sniffer.import_data_from_csv_to_df_obj(exported_csv_file)
                logger().info(sniffer_data_df.head())
                assert sniffer_data_df is not None
        except Exception as e:
            if error_expected in str(e):
                logger().info(f"Got Expected error: {str(e)}")
            elif "Expected 'RSI_APP_EVENT_AE_ADV_REPORT'" in str(e):
                central.interfaces.wifi.ble_ae_set_scan_enable(enable=1,
                                                               filter_duplicates=filter_duplicates,
                                                               duration=scan_duration,
                                                               period=scan_period)
                assert False, "Test case failed with Excepton {}".format(str(e))
            elif "No such file or directory: '/app/reports/ellisys/":
                logger().info(f"Got Exception : {str(e)}")
                assert False, f"Setup Issue... {str(e)}... close Ellysis application and reopen alos power reset the Ellysis device"
            else:
                logger().info(f"Got Exception : {str(e)}")
                assert False, "Test case failed with Excepton {}".format(str(e))
        finally:
            try:
                if not loop_count and not dont_cleanup:
                    if adv_data_type == 2:
                        peripheral.interfaces.bluetooth.ble_app_set_periodic_ae(enable=0, handle=0)
                    try:
                        logger().info(
                            "\n\n ****  Stopping Advertisement  ****\n\n")
                        self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address, adv_enable=0,
                                                      adv_handle=adv_handle)
                        if adv_handle_s2:
                            self.ble_ae_start_advertising(ble_dut=peripheral, dut_address=ble_dut_address, adv_enable=0,
                                                          adv_handle=adv_handle_s2)

                    except Exception as e:
                        logger().info(f"Got Exception : {str(e)}")
            except:
                pass
            try:
                if peripheral:
                    peripheral.interfaces.bluetooth.ble_app_adv_set_clear_or_remove(type=2, handle=0)
                    if adv_handle_s2:
                        peripheral.interfaces.bluetooth.ble_app_adv_set_clear_or_remove(type=2, handle=1)
                time.sleep(2)
            except:
                pass

            try:
                if peripheral:
                    peripheral.interfaces.bluetooth.ble_app_adv_set_clear_or_remove(type=2, handle=0)
                    if adv_handle_s2:
                        peripheral.interfaces.bluetooth.ble_app_adv_set_clear_or_remove(type=2, handle=1)
                time.sleep(2)
            except:
                pass

            if ble_sniffer:
                return sniffer_data_df

    def load_tls_client_private_key(self, wifi_dut, cert_file: str = None,
                                    cert_type: Si91xCertificateType = Si91xCertificateType.SL_NET_TLS_PRIVATE_KEY_CBC_WRAP,
                                    cert_identifier: Si91xCertIdentifier = Si91xCertIdentifier.SL_NET_TLS_CLIENT_CREDENTIAL_START,
                                    cert_index=0,
                                    key_type=Si91xCryptoKeyType.SL_SI91X_TRANSPARENT_KEY,
                                    wrap_iv_mode=Si91xCryptoWrapMode.SL_SI91X_WRAP_IV_CBC_MODE,
                                    iv="1234567890123456"):
        """
        This function is used to load the wrapped private key
        cert_type: SL_NET_TLS_PRIVATE_KEY_CBC_WRAP or SL_NET_TLS_PRIVATE_KEY_ECB_WRAP
        cert_identifier: SL_NET_TLS_CLIENT_CREDENTIAL_START
        cert_index: Possible inputs 0, 1 and, 2
        key_type: possible inputs SL_SI91X_TRANSPARENT_KEY, SL_SI91X_WRAPPED_KEY, and SL_SI91X_BUILT_IN_KEY
        wrap_iv_mode: possible inputs SL_SI91X_WRAP_IV_ECB_MODE, and SL_SI91X_WRAP_IV_CBC_MODE
        iv: string of 16 characters
        """
        cert_file = str(get_tls_certificate_dir().joinpath(cert_file))
        with open(cert_file) as f:
            cert_contents = f.read()
        size = len(cert_contents)
        logger().info(f"\nLoading  certificate '{cert_type}' at index {cert_index}")
        buffer_size = (512 * (int(size / 512))) + 512  # buffer_size should be more than size
        address = wifi_dut.interfaces.wifi.allocate_memory(size=buffer_size)
        wifi_dut.interfaces.wifi.load_memory(address, size=size, write_content=cert_contents)
        data = wifi_dut.interfaces.wifi.generate_wrap_key(address=address,
                                                          key_type=key_type,
                                                          wrap_iv_mode=wrap_iv_mode,
                                                          iv=iv)
        data = data.decode()
        pattern = r"wrapped_private_key_address:(0x[0-9A-Fa-f]+)|key_length:(\d+)"
        # Find all matches using regular expression
        matches = re.findall(pattern, data)
        # Extract the address and key length from the matches
        key_address = matches[0][0]  # The address will be the first element in the first tuple
        length = matches[1][1]  # The key length will be the second element in the second tuple

        try:
            wifi_dut.interfaces.wifi.load_private_wrap_key(address=key_address, cert_type=cert_type,
                                                           cert_identifier=cert_identifier, cert_index=cert_index,
                                                           iv=iv,
                                                           cert_length=length)
            wifi_dut.interfaces.wifi.memory_free(address)
        except:
            logger().info("loading of private wrapped key failed")
            wifi_dut.interfaces.wifi.reset()
            raise

    def stop_guest_bss_on_third_party_ap(self,
                                         wifi_access_point,
                                         band: str = "2g",
                                         index: str = "1",
                                         *,
                                         fallback_full_ap_restart: bool = True,
                                         ) -> None:
        """
        Disable one guest / MBSSID BSS on the lab third-party AP when the driver supports it.

        On **ASUS RT-AX3000**, this uses ``interfaces.wifi._stop_guest_network`` (maps to
        ``wl0``/``wl1`` via *band* and the guest *index*). Other AP models may only support
        the abstract ``_stop_guest_networks`` / full ``stop_ap`` path.

        Args:
            wifi_access_point: Fixture object with ``interfaces.wifi``.
            band: ``'2g'`` or ``'5g'`` for supported APs.
            index: Guest BSS index as string (e.g. ``'1'`` for first guest VAP).
            fallback_full_ap_restart: If True and the specific API is missing or raises,
                performs ``stop_ap()`` then ``start_ap()`` (same idea as storeconfig autojoin tests).

        Example:
            ``stop_guest_bss_on_third_party_ap(wifi_access_point, band='2g', index='1')``
        """
        ap_wifi = wifi_access_point.interfaces.wifi
        log = logger()
        log.info("Stopping guest BSS (band=%s, index=%s)", band, index)
        try:
            if hasattr(ap_wifi, "_stop_guest_network"):
                with ap_wifi._create_shell() as shell:
                    ap_wifi._stop_guest_network(shell=shell, band=band, index=index)
                log.info("Stopped guest BSS via _stop_guest_network")
                return
            if not fallback_full_ap_restart:
                log.warning(
                    "_stop_guest_network not available on this AP; skipping (no fallback)"
                )
                return
            log.info(
                "Specific guest stop not supported; falling back to stop_ap / start_ap"
            )
            ap_wifi.stop_ap()
            ap_wifi.start_ap()
            log.info("AP restarted after stop_ap / start_ap fallback")
        except Exception as exc:
            log.warning("Failed to stop guest BSS: %s", exc)
            if not fallback_full_ap_restart:
                raise
            log.info("Falling back to stop_ap / start_ap")
            ap_wifi.stop_ap()
            ap_wifi.start_ap()

    def ping_ipv6_link_local(self, device_ipv6, interface, ping_count=10, byte_size=64):
        """
        Ping IPv6 link local address using ping6 command with interface specification.
 
        Args:
            device_ipv6 (str): IPv6 link local address to ping (e.g., fe80::add:ebff:fece:f860)
            interface (str): Network interface to use (e.g., wlan0)
            ping_count (int): Number of ping packets to send. Default is 10.
            byte_size (int): Size of ping packet in bytes. Default is 64.
 
        Returns:
            bool: True if ping succeeds, False otherwise.
        """
        command = ["ping", "-I", interface, "-c", str(ping_count), "-s", str(byte_size), device_ipv6]
        result = subprocess.run(command, capture_output=True)
        rc = result.returncode
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
 
        # Check if stderr contains only warnings (not actual errors)
        is_warning_only = stderr and "warning:" in stderr.lower() and rc == 0
 
        if rc != 0:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}\n{stderr}")
            assert False, f"Failed to ping IPv6 link local address {device_ipv6} on interface {interface}"
        elif stderr and not is_warning_only:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}\n{stderr}")
            assert False, f"Failed to ping IPv6 link local address {device_ipv6} on interface {interface}"
        else:
            logger().info(f"{command} command exited with code {rc} with output:\n{stdout}")
            if stderr and is_warning_only:
                logger().info(f"Warning message (ignored): {stderr}")
 
        return rc == 0

    def stop_all_guest_bss_on_third_party_ap(self, wifi_access_point, *, fallback_full_ap_restart: bool = True) -> None:
        """
        Disable every guest / MBSSID BSS listed on the AP (e.g. indices 1, 2, 3 from config).

        Reads ``interfaces.wifi.guest_networks`` and calls ``_stop_guest_network`` once per
        entry using a **single** shell session (ASUS RT-AX3000 and similar).

        Args:
            wifi_access_point: Fixture object with ``interfaces.wifi``.
            fallback_full_ap_restart: If True and per-BSS stop is unavailable or fails,
                performs ``stop_ap()`` then ``start_ap()``.

        Example:
            ``stop_all_guest_bss_on_third_party_ap(wifi_access_point)``
        """
        ap_wifi = wifi_access_point.interfaces.wifi
        log = logger()
        guest_networks = getattr(ap_wifi, "guest_networks", None) or []

        if not guest_networks:
            log.warning("No guest_networks on AP; skip stop-all-guests")
            return

        try:
            if hasattr(ap_wifi, "_stop_guest_network"):
                with ap_wifi._create_shell() as shell:
                    for gn in guest_networks:
                        band = gn.get("band", "2g")
                        index = gn.get("index")
                        if index is None:
                            continue
                        log.info(
                            "Stopping guest BSS band=%s index=%s", band, index
                        )
                        ap_wifi._stop_guest_network(
                            shell=shell, band=band, index=str(index)
                        )
                log.info(
                    "Stopped all %d guest BSS via _stop_guest_network",
                    len(guest_networks),
                )
                return
            if not fallback_full_ap_restart:
                log.warning(
                    "_stop_guest_network not available; skipping (no fallback)"
                )
                return
            log.info(
                "Specific guest stop not supported; falling back to stop_ap / start_ap"
            )
            ap_wifi.stop_ap()
            ap_wifi.start_ap()
            log.info("AP restarted after stop_ap / start_ap fallback")
        except Exception as exc:
            log.warning("Failed to stop all guest BSS: %s", exc)
            if not fallback_full_ap_restart:
                raise
            log.info("Falling back to stop_ap / start_ap")
            ap_wifi.stop_ap()
            ap_wifi.start_ap()
