from utf.devices import Device
from utf.utils.device_utils import merge_configs
import utf.utils.commander as commander
import os
import yaml
import time
from otel_extensions import instrumented
from enum import IntEnum, IntFlag


def create_device(name: str, config_data=None):
    """
    Called when to create device object of type Si91x

    Args:
        name: ``string`` name value to set
        config_data: ``dict`` configuration data object to set the configuration of the device

    Returns:
        Instance of ``Si91x``

    """
    return Si91x(name, config_data)


class Si91xOperatingMode(IntEnum):
    WiFiClient = 0
    EAPWiFiClient = 2
    AccessPoint = 6
    TransceiverMode = 7
    PERMode = 8
    ConcurrentMode = 9
    Default = WiFiClient


class Si91xCoexMode(IntFlag):
    WLANOnly = 0
    WLAN = 1  # Currently not supported in SiWx917.
    ZigBee = 2
    Bluetooth = 4  # Currently not supported in SiWx917.
    WLANBluetooth = 5  # Currently not supported in SiWx917.
    DualBluetoothBLE = 8
    WLANDual = 9  # Currently not supported in SiWx917.
    BLE = 12  # Bluetooth Low Energy (BLE) only mode, used when power save mode not needed.
    WLANBLE = 13
    ANT = 265
    Default = WLANOnly
    Disabled = WLANOnly


class Si91xFeatureBitMap(IntFlag):
    OpenMode = 1
    PSKSecurity = 2
    Aggregation = 4
    FEAT_DEV_TO_HOST_ULP_GPIO_1 = 32
    LPGPIOHandshake = 8
    ULPGPIOHandshake = 16
    WPSSupportDisabled = 128
    HTTPLongerURL = 1 << 14
    SL_SI91X_FEAT_DISABLE_11AX_SUPPORT = 1 << 15
    SL_SI91X_FEAT_LONG_ICMP_PACKET = 1 << 12
    HidePSKCredentials = 1 << 9
    Default = ULPGPIOHandshake | WPSSupportDisabled | Aggregation | PSKSecurity | OpenMode


class Si91xJoinFeatureBitMap(IntFlag):
    Default = 0
    BGOnly = 1
    ListenIntervalFromJoin = 2
    QuickJoin = 4
    CCVX2 = 8
    APBasedOnBSSID = 16
    MgmtFrameProtectionCapable = 32
    MgmtFrameProtectionRequired = 64
    ListenIntervalFromPowerSave = 128
    ListenIntervalDefault = 1600
    Enable_WPA3 = 96


class IEEE802_11W:
    Protection_capable = 1 << 5
    Protection_Required = 1 << 6

class Si91xIEUniqueIdentifiers:
    SL_WIFI_VENDOR_IE_AUTO_ASSIGN = 0

class Si91xIEMgmtBitMap:
    SL_WIFI_VENDOR_IE_IN_BEACON = 1 << 0
    SL_WIFI_VENDOR_IE_IN_PROBE_RESP = 1 << 1
    SL_WIFI_VENDOR_IE_IN_ASSOC_RESP = 1 << 2
    SL_WIFI_VENDOR_IE_IN_PROBE_REQ = 1 << 3
    SL_WIFI_VENDOR_IE_IN_ASSOC_REQ = 1 << 4


class Si91xTCPIPFeatureBitMap(IntFlag):
    TCPIPBypass = 1
    HTTPServer = 2
    HTTPSServer = 0x1000
    DHCPv4Client = 4
    DHCPv6Client = 8
    DHCPv4Server = 0x10
    DHCPv6Server = 0x20
    DynamicWebPages = 0x40
    HTTPClient = 0x80
    DNSClient = 0x100
    SNMPAgent = 0x200
    SSL = 0x400
    Ping = 0x800
    FTPClient = 0x8000
    SNTPClient = 0x10000
    IPv6Mode = 0x20000
    RawSockets = 0x40000
    mDNS = 0x80000
    SMTPClient = 0x100000
    mDNSSD = 1 << 19
    TCP_IP_FEAT_ICMP = 1 << 11
    TCP_IP_TOTAL_SOCKETS_1 = 1 << 21
    SingleSSLSocket = 1 << 25
    LoadPublicPrivateCerts = 1 << 26
    LoadSSLCertificatesToRAM = 1 << 27
    ExtTCPIPFeatureBitmapValid = 1 << 31
    SL_SI91X_TCP_IP_FEAT_DTLS_THREE_SOCKETS = 1 << 29
    Default = DHCPv4Client | ExtTCPIPFeatureBitmapValid

    @staticmethod
    def TCP_IP_TOTAL_SOCKETS(num_sockets):
        return num_sockets << 21


class Si91xCustomFeatureBitMap(IntFlag):
    DHCPServerNoGatewayAddress = 4
    NWP160MHz = 0x10
    HiddenSSID = 0x20
    DNSServerIPAddrOffer = 0x40
    DFSChannelPassiveScan = 0x100
    AsyncStatusMessagesToHost = 0x400
    PacketPendingWake = 0x800
    PacketAPBlackList = 0x1000
    DeauthRoaming = 0x20000
    TriggerAutoConfiguration = 0x100000
    PerStationPowerSavePacketBufferLimit = 0x400000
    HTTPHTTPSAuthentication = 0x800000
    NWP120MHz = 0x1000000
    HTTPServerCredentialsToHost = 0x2000000
    RejectNewLTCPConnectionsWhenMaxClientsConnected = 0x4000000
    DualBandRoamingAndVcafd = 0x8000000
    RealTimeClockFromHost = 0x10000000
    IAPSupportInBTMode = 0x20000000
    ExtCustomFeatureBitmapValid = 0x80000000
    Default = ExtCustomFeatureBitmapValid

    @staticmethod
    def CUSTOM_FEAT_MAX_NUM_OF_CLIENTS(max_num_clients):
        return max_num_clients << 13

# NCP ext-custom memory (firmware SL_SI91X_EXT_FEAT_672K_M4SS_0K): bits 20|21.
_SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE = (1 << 20) | (1 << 21)
SL_SI91X_EXT_FEAT_672K = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE
SL_SI91X_EXT_FEAT_672K_M4SS_0K = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE


class Si91xExtCustomFeatureBitMap(IntFlag):
    RsaKeyWith4096Support = 1 << 1
    SslCertWith4096Support = 1 << 3
    MultipleSslVersionSupport = 1 << 14
    Feature192kBMemoryMode = 0
    FeatureLowPower = 1 << 19
    EXT_FEAT_XTAL_CLK_ENABLE = 1 << 22
    Feature32KHzBypassClockOnUULP_GPIO_3 = 1 << 23
    Feature256kBMemoryMode = 1 << 21
    Feature320kBMemoryMode = 1 << 20
    SL_SI91X_EXT_FEAT_672K = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE
    SL_SI91X_EXT_FEAT_672K_M4SS_0K = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE
    Feature384kBMemoryMode = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE
    SOC_EXT_CUSTOM_MEMORY_BITS = _SL_SI91X_EXT_FEAT_672K_MEMORY_VALUE
    UartSelForDebugPrints = 1 << 27
    BTFeatureBitmapValid = 1 << 31
    IEEE802_11W = 1 << 13
    DisableDebugPrints = 1 << 28
    SL_SI91X_EXT_FEAT_FRONT_END_SWITCH_PINS_ULP_GPIO_4_5_0 = 1 << 29

    Default = (
            FeatureLowPower
            | EXT_FEAT_XTAL_CLK_ENABLE
            | SL_SI91X_EXT_FEAT_FRONT_END_SWITCH_PINS_ULP_GPIO_4_5_0
    )


class Si91xBTFeatureBitMap(IntFlag):
    RFTypeSelection = 1 << 30
    BTSniff = 1 << 13
    BLEFeatureBitmapValid = 1 << 31
    A2DPProfileEnable = 1 << 23
    A2DPSourceRoleEnable = 1 << 24
    BT_EDR_2DH5_PACKETS_ONLY = (1 << 8) | (1 << 11)
    BT_EDR_2DH3_PACKETS_ONLY = (1 << 8) | (1 << 10)
    BT_EDR_3DH3_PACKETS_ONLY = (1 << 9) | (1 << 10)
    BT_EDR_3DH5_PACKETS_ONLY = (1 << 9) | (1 << 11)
    Default = RFTypeSelection | BLEFeatureBitmapValid


class Si91xPowerSaveModes(IntFlag):
    PowerSaveDisabled = 0
    PowerSaveMode1 = 1
    PowerSaveMode2 = 2
    PowerSaveMode3 = 3
    PowerSaveMode8 = 8
    PowerSaveMode9 = 9


class Si91xPowerSaveProcedureTypes(IntFlag):
    MaxPowerSave = 0
    FastPowerSave = 1
    UAPSDPowerSave = 2


class Si91xExtTCPIPFeatureBitMap(IntFlag):
    DHCPUserClass = 1 << 1
    HTTPServerRootPathBypass = 1 << 2
    SSLCertBypass = 1 << 5
    EXT_TCP_IP_BI_DIR_ACK_UPDATE = 1 << 3
    EXT_TCP_IP_SSL_16K_RECORD = 1 << 6
    EXT_TCP_IP_WINDOW_DIV = 1 << 4
    EXT_DYNAMIC_COEX_MEMORY = 1 << 11
    DNSClientBypass = 1 << 7
    WaitForSocketClose = 1 << 16
    EnableMQTTFeature = 1 << 17
    ConfigFeatureBitmapValid = 1 << 31
    ConfigHttpOTAF = 1 << 18
    Default = ConfigFeatureBitmapValid
    TCP_ACK_CORRECT = 1 << 3
    THREE_SSL_SOCKET_SELECT = 1 << 29
    EXT_TCP_IP_FEAT_SSL_MEMORY_CLOUD = 1 << 30
    EXT_TCP_IP_SSL_16K_RECORDBIT = 1 << 6
    CONFIG_FEAT_EXTENTION_VALID = 1 << 31
    EXT_TCP_IP_WINDOW_SELECT = 1 << 8
    EXT_TCP_NAT_SUPPORT = 1 << 21
    SL_SI91X_EXT_TCP_IP_FEAT_HTTP_HP_SUPPORT = 1 << 22
    EXT_TCP_IP_DUAL_MODE_ENABLE = 1 << 10

    @staticmethod
    def EXT_TCP_IP_TOTAL_SELECTS(num_selects: int = 0):
        return num_selects << 12


class Si91xRegion(IntEnum):
    FromBeacon = 0
    FromUser = 1


class Si91xRegionCode:
    Default = "default"
    US = "us"
    Europe = "europe"
    Japan = "japan"
    Worldwide = "worldwide"
    Korea = "korea"
    Singapore = "singapore"
    China = "china"
    Ignore = "ignore"


class Si91xAwsQos(IntEnum):
    QOS0 = 0
    QOS1 = 1


class Si91xWifiBand(IntEnum):
    SL_SI91X_WIFI_BAND_2_4GHZ = 0
    SL_SI91X_WIFI_BAND_5GHZ = 1
    SL_SI91X_WIFI_DUAL_BAND = 2


class Si91xBootOption(IntEnum):
    LOAD_NWP_FW = 49
    LOAD_DEFAULT_NWP_FW_ACTIVE_LOW = 113


class MulticastParams:
    MULTICAST_MAC_ADD_BIT = 0
    MULTICAST_MAC_CLEAR_BIT = 1
    MULTICAST_MAC_CLEAR_ALL = 2
    MULTICAST_MAC_SET_ALL = 3


class MulticastParams:
    MULTICAST_MAC_ADD_BIT = 0
    MULTICAST_MAC_CLEAR_BIT = 1
    MULTICAST_MAC_CLEAR_ALL = 2
    MULTICAST_MAC_SET_ALL = 3


class DefaultCipher:
    cipher_list = [
        "TLS_RSA_WITH_AES_256_CBC_SHA256",
        "TLS_RSA_WITH_AES_128_CBC_SHA256",
        "TLS_RSA_WITH_AES_256_CBC_SHA",
        "TLS_RSA_WITH_AES_128_CBC_SHA",
        "TLS_RSA_WITH_AES_128_CCM_8",
        "TLS_RSA_WITH_AES_256_CCM_8",
        "TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8",
        "TLS_ECDHE_ECDSA_WITH_AES_256_CCM_8",
        "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
        "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
        "TLS_DHE_RSA_WITH_AES_256_CBC_SHA256",
        "TLS_DHE_RSA_WITH_AES_128_CBC_SHA256",
        "TLS_DHE_RSA_WITH_AES_256_CBC_SHA",
        "TLS_DHE_RSA_WITH_AES_128_CBC_SHA",
        "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384",
        "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256",
        "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
        "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
        "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384",
        "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256",
        "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA",
        "TLS_DHE_RSA_WITH_3DES_EDE_CBC_SHA",
        "TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA",
        "TLS_ECDHE_ECDSA_WITH_3DES_EDE_CBC_SHA",
        "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
        "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
        "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
        "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
        "TLS_DHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
        "TLS_EMPTY_RENEGOTIATION_INFO_SCSV"
        ]

    cipher_list_tls1_3 = [
        "TLS13_AES_128_GCM_SHA256",
        "TLS13_AES_256_GCM_SHA384",
        "TLS13_CHACHA20_POLY1305_SHA256",
        "TLS13_AES_128_CCM_SHA256",
        "TLS13_AES_128_CCM_8_SHA256",
        "TLS_EMPTY_RENEGOTIATION_INFO_SCSV"
        ]


class DeviceConstants:
    ENCODING = 'utf-8'


class Cipher(IntEnum):
    # TLS 1.3 Ciphers
    BIT_TLS13_AES_128_GCM_SHA256 = 1 << 0
    BIT_TLS13_AES_256_GCM_SHA384 = 1 << 1
    BIT_TLS13_CHACHA20_POLY1305_SHA256 = 1 << 2
    BIT_TLS13_AES_128_CCM_SHA256 = 1 << 3
    BIT_TLS13_AES_128_CCM_8_SHA256 = 1 << 4
    # TLS 1.2 Ciphers
    BIT_TLS_RSA_WITH_AES_256_CBC_SHA256 = 1 << 0
    BIT_TLS_RSA_WITH_AES_128_CBC_SHA256 = 1 << 1
    BIT_TLS_RSA_WITH_AES_256_CBC_SHA = 1 << 2
    BIT_TLS_RSA_WITH_AES_128_CBC_SHA = 1 << 3
    BIT_TLS_RSA_WITH_AES_128_CCM_8 = 1 << 4
    BIT_TLS_RSA_WITH_AES_256_CCM_8 = 1 << 5
    BIT_TLS_DHE_RSA_WITH_AES_128_GCM_SHA256 = 1 << 8
    BIT_TLS_DHE_RSA_WITH_AES_256_GCM_SHA384 = 1 << 9
    BIT_TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 = 1 << 10
    BIT_TLS_DHE_RSA_WITH_AES_256_CBC_SHA256 = 1 << 14
    BIT_TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 = 1 << 11
    BIT_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256 = 1 << 12
    BIT_TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384 = 1 << 13
    BIT_TLS_DHE_RSA_WITH_AES_128_CBC_SHA256 = 1 << 15
    BIT_TLS_DHE_RSA_WITH_AES_256_CBC_SHA = 1 << 16
    BIT_TLS_DHE_RSA_WITH_AES_128_CBC_SHA = 1 << 17
    BIT_TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384 = 1 << 18
    BIT_TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256 = 1 << 19
    BIT_TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA = 1 << 20
    BIT_TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA = 1 << 21
    BIT_TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384 = 1 << 22
    BIT_TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256 = 1 << 23
    BIT_TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA = 1 << 24
    BIT_TLS_DHE_RSA_WITH_3DES_EDE_CBC_SHA = 1 << 25
    BIT_TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA = 1 << 26
    BIT_TLS_ECDHE_ECDSA_WITH_3DES_EDE_CBC_SHA = 1 << 27
    BIT_TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256 = 1 << 28
    BIT_TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256 = 1 << 29
    BIT_TLS_DHE_RSA_WITH_CHACHA20_POLY1305_SHA256 = 1 << 30
    SSL_NEW_CIPHERS = 1 << 31


class SocketOptions(IntEnum):
    SOL_SOCKET = 1
    SSL_ENABLE = 1
    SO_SSL_ENABLE = 37
    SO_SSL_V_1_2_ENABLE = 44
    SO_SSL_V_1_0_ENABLE = 42
    SO_SSL_V_1_3_ENABLE = 49
    SL_SO_CERT_INDEX = 46
    CERT_INDEX0 = 0
    CERT_INDEX1 = 1
    CERT_INDEX2 = 2
    TCP_RETRY = 24
    TCP_MAX_RETRY = 250
    SSL_ENABLE_VERSION_1_2 = 9
    SSL_ENABLE_VERSION_1_0 = 5
    SO_TCP_ACK_INDICATION = 45


class Si91xMqttQos(IntEnum):
    QOS0 = 0
    QOS1 = 1
    QOS2 = 2


class Si91xTimeoutParams(IntEnum):
    keep_alive_timeout_value = 10
    auth_assoc_timeout_value = 100
    active_chan_scan_timeout_value = 100
    passive_chan_scan_timeout_value = 0


class Si91xRtsThreshold(IntEnum):
    rts_threshold = 2346


class Si91xModuleType(IntEnum):
    WithoutOnboardAntenna = 0
    WithOnboardAntenna = 1


class Si91xBLEFeatureBitMap(IntFlag):
    TXPowerIndex = 1 << 16 | 1 << 17 | 1 << 18 | 1 << 19 | 1 << 20
    SL_SI91X_BLE_GATT_ASYNC_ENABLE = 1 << 29
    RS9113_Si91x_Compatible_Feature = 1 << 30
    BLECustomFeatureBitmapValid = 1 << 31
    BLE_MAX_NUM_OF_PHERIPHERALS = 1 << 12
    BLE_MAX_NBR_CENTRALS = 2 << 27
    BLE_MAX_NBR_CENTRALS_AE = 0 << 27
    BLE_MAX_NBR_ATT_SERV = 10 << 8
    BLE_MAX_NBR_ATT_REC = 40
    FEAT_BLE_CUSTOM_FEAT_EXTENTION_VALID = 1 << 31
    SL_SI91X_BLE_PWR_INX = 30 << 16
    SL_SI91X_BLE_PWR_INX_45 = 45 << 16
    SL_SI91X_BLE_PWR_INX_63 = 63 << 16
    SL_SI91X_BLE_PWR_INX_64 = 64 << 16
    SL_SI91X_BLE_PWR_INX_75 = 75 << 16
    SL_SI91X_BLE_PWR_SAVE_OPTIONS = 0 << 24
    SL_SI91X_916_BLE_COMPATIBLE_FEAT_ENABLE = 1 << 30
    BLE_MAX_NBR_ATT_REC_AE_COEX = 80

    @classmethod
    def set_num_peripherals(cls, num_peripherals: int) -> int:
        """
        Set the number of BLE peripherals in the feature bitmap.

        Args:
            num_peripherals (int): Number of peripherals to support (1-2)

        Returns:
            int: Feature bitmap value with the specified number of peripherals

        Raises:
            ValueError: If num_peripherals is not between 1 and 2
        """
        if not 0 <= num_peripherals <= 2:
            raise ValueError("Number of peripherals must be between 1 and 2")
        return num_peripherals << 12

    @classmethod
    def set_num_centrals(cls, num_centrals: int) -> int:
        """
        Set the number of BLE centrals in the feature bitmap.

        Args:
            num_centrals (int): Number of centrals to support (0-2)

        Returns:
            int: Feature bitmap value with the specified number of centrals

        Raises:
            ValueError: If num_centrals is not between 0 and 2
        """
        if not 0 <= num_centrals <= 2:
            raise ValueError("Number of centrals must be between 0 and 2")
        return num_centrals << 27  # 27 is the bit position for number of centrals

    Default = (
            BLE_MAX_NUM_OF_PHERIPHERALS
            | BLE_MAX_NBR_CENTRALS
            | BLE_MAX_NBR_ATT_SERV
            | BLE_MAX_NBR_ATT_REC
            | FEAT_BLE_CUSTOM_FEAT_EXTENTION_VALID
            | SL_SI91X_BLE_PWR_INX
            | SL_SI91X_BLE_PWR_SAVE_OPTIONS
            | SL_SI91X_916_BLE_COMPATIBLE_FEAT_ENABLE
    )


_SI91X_EXT_CUSTOM_MEMORY_BIT_MASK = (1 << 20) | (1 << 21)
_SI91X_BLE_CENTRALS_BIT_MASK = 0x3 << 27


def is_si91x_ncp_dut(device_name: str) -> bool:
    """Return True when harness DUT is an Si91x NCP device (e.g. si917_ncp_sl_wifi)."""
    return bool(device_name) and 'ncp' in device_name.lower()


def apply_ncp_oper_mode_ext_custom_features(ext_custom_features: int) -> int:
    """Replace SoC 320k/256k memory bits with NCP SL_SI91X_EXT_FEAT_672K_M4SS_0K."""
    if ext_custom_features & _SI91X_EXT_CUSTOM_MEMORY_BIT_MASK:
        return (
            (ext_custom_features & ~_SI91X_EXT_CUSTOM_MEMORY_BIT_MASK)
            | SL_SI91X_EXT_FEAT_672K_M4SS_0K
        )
    return ext_custom_features


def apply_ncp_oper_mode_ble_features(ble_features: int, coex_mode: int) -> int:
    """Map SoC BLE opermode bitmap to NCP-compatible values when BLE coex is enabled."""
    if not (coex_mode & Si91xCoexMode.BLE):
        return ble_features
    if ble_features & Si91xBLEFeatureBitMap.BLE_MAX_NBR_CENTRALS:
        ble_features = (ble_features & ~_SI91X_BLE_CENTRALS_BIT_MASK) | (1 << 27)
    if ble_features & Si91xBLEFeatureBitMap.BLE_MAX_NBR_ATT_REC:
        ble_features = (
            (ble_features & ~Si91xBLEFeatureBitMap.BLE_MAX_NBR_ATT_REC)
            | Si91xBLEFeatureBitMap.BLE_MAX_NBR_ATT_REC_AE_COEX
        )
    if ble_features & Si91xBLEFeatureBitMap.FEAT_BLE_CUSTOM_FEAT_EXTENTION_VALID:
        ble_features |= Si91xBLEFeatureBitMap.SL_SI91X_BLE_GATT_ASYNC_ENABLE
    return ble_features


class Si91xBLECustomFeatureBitMap(IntFlag):
    BLE_NUM_REC_BYTES = 1 << 11
    SL_SI91X_BLE_NUM_CONN_EVENTS = 6 << 0
    SL_SI91X_BLE_NUM_REC_BYTES = 64 << 5
    SL_SI91X_BLE_INDICATE_CONFIRMATION_FROM_HOST = 1 << 14
    SL_SI91X_BLE_MTU_EXCHANGE_FROM_HOST = 1 << 15
    SL_SI91X_BLE_SET_SCAN_RESP_DATA_FROM_HOST = 1 << 16
    SL_SI91X_BLE_DISABLE_CODED_PHY_FROM_HOST = 1 << 17
    SL_SI91X_BLE_ENABLE_ADV_EXTN = 1 << 19
    SL_SI91X_BLE_GATT_INIT = 1 << 13
    SL_SI91X_BLE_AE_MAX_ADV_SETS = 2 << 20
    SL_SI91X_BLE_NUM_CONN_EVENTS_AE = 2 << 0
    Default = (SL_SI91X_BLE_NUM_CONN_EVENTS | SL_SI91X_BLE_NUM_REC_BYTES)


class Si91xConfigFeatureBitMap(IntFlag):
    WakeupIndicationUULPGPIO0 = 1
    Default = 0
    EnahanceMaxPsp = 1 << 26
    SL_SI91X_ENABLE_NWP_LOGGING = 1 << 12
    TLS_V1 = 1 << 14
    TLS_V2 = 1 << 15
    SL_SI91X_FEAT_SLEEP_GPIO_SEL_BITMAP = 1 << 0
    RSI_CONFIG_FEATURE_BITMAP = 0
    DISABLE_SHORT_GI = 1 << 20


class Si91xAesType:
    SL_SI91X_AES_CBC = 1
    SL_SI91X_AES_ECB = 2
    SL_SI91X_AES_CTR = 3


class Si91xAesOperation:
    SL_SI91X_AES_ENCRYPT = 1
    SL_SI91X_AES_DECRYPT = 2


class Si91xAesKeySize:
    SL_SI91X_AES_KEY_SIZE_128 = 16
    SL_SI91X_AES_KEY_SIZE_192 = 24
    SL_SI91X_AES_KEY_SIZE_256 = 32


class Si91xKeyType:
    SL_SI91X_TRANSPARENT_KEY = 0
    SL_SI91X_WRAPPED_KEY = 1
    SL_SI91X_BUILT_IN_KEY = 2


class Si91xWrapIVMode:
    SL_SI91X_WRAP_IV_ECB_MODE = 0
    SL_SI91X_WRAP_IV_CBC_MODE = 1


class Si91xSHA:
    SL_SI91X_SHA_1 = 1
    SL_SI91X_SHA_256 = 2
    SL_SI91X_SHA_384 = 3
    SL_SI91X_SHA_512 = 4
    SL_SI91X_SHA_224 = 5


class Si91xHMAC:
    SL_SI91X_HMAC_SHA_1 = 1
    SL_SI91X_HMAC_SHA_256 = 2
    SL_SI91X_HMAC_SHA_384 = 3
    SL_SI91X_HMAC_SHA_512 = 4


class Si91xECDH:
    SL_SI91X_ECDH_192 = 1
    SL_SI91X_ECDH_224 = 2
    SL_SI91X_ECDH_256 = 4


class Si91xECDHOperation:
    SL_SI91X_ECDH_MUL = 1
    SL_SI91X_ECDH_ADD = 2
    SL_SI91X_ECDH_SUB = 3
    SL_SI91X_ECDH_DOUBLE = 4
    SL_SI91X_ECDH_AFFINITY = 5


class Si91xCertificateType:
    SL_NET_CERTIFICATE = 'client_cert'
    SL_NET_PUBLIC_KEY = 'public_key'
    SL_NET_PRIVATE_KEY = 'private_key'
    SL_NET_SIGNING_CERTIFICATE = 'ca_cert'
    SL_NET_HTTP_CLIENT_CREDENTIAL = 'http_client'
    SL_NET_EAP_CLIENT_CREDENTIAL = 'eap_client'
    SL_NET_MQTT_CLIENT_CREDENTIAL = 'mqtt_client'
    SL_NET_PACK_FILE = 'eap_fast_client'
    SL_NET_TLS_PRIVATE_KEY_CBC_WRAP = "private_key_cbc_wrap"
    SL_NET_TLS_PRIVATE_KEY_ECB_WRAP = "private_key_ecb_wrap"


class Si91xCryptoWrapMode:
    SL_SI91X_WRAP_IV_ECB_MODE = 0
    SL_SI91X_WRAP_IV_CBC_MODE = 1


class Si91xCryptoKeyType:
    SL_SI91X_TRANSPARENT_KEY = 0
    SL_SI91X_WRAPPED_KEY = 1
    SL_SI91X_BUILT_IN_KEY = 2


class Si91xCertIdentifier:
    SL_NET_INVALID_CREDENTIAL_ID = 'invalid_id'
    SL_NET_DEFAULT_WIFI_CLIENT_CREDENTIAL_ID = 'wifi_client'
    SL_NET_DEFAULT_WIFI_AP_CREDENTIAL_ID = 'wifi_ap'
    SL_NET_WIFI_EAP_CLIENT_CREDENTIAL_ID = 'wifi_eap_client'
    SL_NET_WIFI_EAP_SERVER_CREDENTIAL_ID = 'wifi_eap_server'
    SL_NET_USER_CREDENTIAL_ID = 'user'
    SL_NET_TLS_CLIENT_CREDENTIAL_START = 'tls_client'
    SL_NET_TLS_SERVER_CREDENTIAL_START = 'tls_server'
    SL_NET_MQTT_SERVER_CREDENTIAL_START = 'mqtt_server'
    SL_NET_MQTT_CLIENT_CREDENTIAL_START = 'mqtt_client'
    SL_NET_HTTP_SERVER_CREDENTIAL_START = 'http_server'
    SL_NET_HTTP_CLIENT_CREDENTIAL_START = 'http_client'


class Si91xInterface:
    SL_WIFI_CLIENT_2_4GHZ_INTERFACE = "client"
    SL_WIFI_AP_2_4GHZ_INTERFACE = "ap"
    SL_WIFI_CLIENT_5GHZ_INTERFACE = "client_5g"
    SL_WIFI_AP_5GHZ_INTERFACE = "ap_5g"


class Si91xApplicationProtocol:
    SL_NET_APPLICATION_PROTOCOL_HTTP_HTTPS = "http"
    SL_NET_APPLICATION_PROTOCOL_MQTT = "mqtt"
    SL_NET_APPLICATION_PROTOCOL_FTP = "ftp"
    SL_NET_APPLICATION_PROTOCOL_SSL_SOCKET = "ssl"
    SL_NET_APPLICATION_PROTOCOL_ALL = "all"


class Si91xCustomSyncSockOptParms:
    SOL_SOCKET = "SOL_SOCKET"
    SL_SO_CERT_INDEX = "SL_SO_CERT_INDEX"
    SO_ERROR = "SO_ERROR"
    SO_SNDBUF = "SO_SNDBUF"
    SL_SI91X_SO_MAXRETRY = "SL_SI91X_SO_MAXRETRY"
    SL_SI91X_SO_MSS = "SL_SI91X_SO_MSS"
    SL_SI91X_SO_HIGH_PERFORMANCE_SOCKET = "SL_SI91X_SO_HIGH_PERFORMANCE_SOCKET"
    SL_SI91X_SO_DTLS_ENABLE = "SL_SI91X_SO_DTLS_ENABLE"  # 51 To enable DTLS
    SL_SI91X_SO_DTLS_V_1_0_ENABLE = "SL_SI91X_SO_DTLS_V_1_0_ENABLE"  # 52 To enable DTLS 1.0
    SL_SI91X_SO_DTLS_V_1_2_ENABLE = "SL_SI91X_SO_DTLS_V_1_2_ENABLE"  #53 To enable DTLS 1.2
    SL_SI91X_SO_PER_SOCKET_CLOSE_ENABLE = "SL_SI91X_SO_PER_SOCKET_CLOSE"  #54 Enable per-socket graceful close handling
    SL_SO_PER_SOCKET_CLOSE = "SL_SO_PER_SOCKET_CLOSE"  # 0x102E BSD-level per-socket graceful close, for sync sockets


class Si91xMdnsParams:
    IPV4 = "ip_version4"
    IPV6 = "ip_version6"
    PROTO_PHY = "phy"
    PROTO_UDP = "udp"
    SERVICE_PORT = 80
    TTL = 300


class Si91xIp:
    SL_IPV4 = "ipv4"
    SL_IPV6 = "ipv6"
    SL_IPV6_LINK_LOCAL = "ipv6_link_local"
    SL_IPV6_SITE_LOCAL = "ipv6_site_local"
    SL_IPV6_GLOBAL = "ipv6_global"


class Si91xIpVersion:
    SL_IPV4_VERSION = 4
    SL_IPV6_VERSION = 6


class Si91xBSDSocketParams:
    AF_INET = 2
    SOCK_STREAM = 1
    SOCK_DGRAM = 2
    SOCK_NONBLOCK = 16384
    SOCK_STREAM_NONBLOCK = 16385
    IPPROTO_TCP = 6
    AF_INET6 = 24
    IPPROTO_UDP = 17


class Si91xTWTRescheduleParams:
    SL_WIFI_SUSPEND_INDEFINITELY = 0
    SL_WIFI_SUSPEND_FOR_DURATION = 1
    SL_WIFI_RESUME_IMMEDIATELY = 2


class Si91xBleDutyParams:
    enable_duty_cycle = False
    duty_cycle = 0


class Si91xWebSocketParms:
    SL_WEBSOCKET_OPCODE_CONTINUE = 0
    SL_WEBSOCKET_OPCODE_TEXT = 1
    SL_WEBSOCKET_OPCODE_BINARY = 2
    SL_WEBSOCKET_OPCODE_CLOSE = 8
    SL_WEBSOCKET_OPCODE_PING = 9
    SL_WEBSOCKET_OPCODE_PONG = 10
    SL_WEBSOCKET_FIN_BIT = 128


class Si91xBleConnParams:
    SL_BLE_CONN_INTERVAL_MIN = 160
    SL_BLE_CONN_INTERVAL_MAX = 160
    SL_BLE_CONN_LATENCY = 0
    SL_BLE_SUPERVISION_TIMEOUT = 2000


class Si91x(Device):
    """
    Si91x Device class
    """

    def __init__(self, name: str, config_data):
        """
        Constructor of Si91x

        Args:
            name: ``string`` name value to set
            config_data: ``dict`` configuration data object to set the configuration of the device
        """
        with open(os.path.join(os.path.dirname(__file__), "si91x.yaml")) as f:
            base_data = yaml.safe_load(f)["si91x"]
        super().__init__(name, merge_configs(base_data, config_data or {}))
        self.last_firmware_write = ""
        self.commander_options = ""
        if "commander_options" in self.config:
            self.commander_options = self.config["commander_options"]

    @instrumented
    def reset(self):
        """
        Called when to reset device using commander with commander options

        Returns:
            None

        """
        self.logger.info(f"Resetting Si91x device '{self.name}'")
        commander.reset_device(self.commander_options)
        time.sleep(0.2)
        for i in self.interfaces:
            interface_obj = self.interfaces[i]
            if hasattr(interface_obj, "reset"):
                interface_obj.reset()

    @instrumented
    def erase_flash(self):
        """
        Called when to erase main flash on Si91x device using commander with commander options

        Returns:
            None

        """
        self.logger.info(f"Erasing main flash on Si91x device '{self.name}'")
        commander.erase_device_main_flash(self.commander_options)
        self.logger.info(f"Erasing main flash successful on Si91x device '{self.name}'")

    @instrumented
    def write_bootloader(self, boot_file: str):
        """
        Called when required to write the bootloader to device.

        Args:
            boot_file: ``string`` file path value of the bootloader file

        Returns:
            None

        """
        self.logger.info(
            f"Writing bootloader '{boot_file}' to Si91x device '{self.name}'"
            )
        commander.flash_device(boot_file, self.commander_options)
        self.logger.info(f"Bootloader loading complete on Si91x device '{self.name}'")

    @instrumented
    def write_firmware(self, firmware_file: str):
        """
        Called when required to write the firmware to device.

        Args:
            firmware_file: ``string`` firmware path value of the file

        Returns:
            None
        """
        if self.last_firmware_write == firmware_file:
            return

        self.logger.info(
            f"Writing firmware '{firmware_file}' to Si91x device '{self.name}'"
            )
        commander.flash_device(firmware_file, self.commander_options)
        self.last_firmware_write = firmware_file
        self.logger.info(f"Firmware loading complete on Si91x device '{self.name}'")

    @instrumented
    def device_info(self):
        """
        Called when to read Si91x device information using commander with commander options

        Returns:
            (dict) commander device information available through a single level dictionary

        """
        self.logger.info(f"Reading Si91x device info for '{self.name}':")
        _, raw_device_info, _ = commander.device_info(self.commander_options)
        device_info = commander.convert_commander_output_to_dict(raw_device_info)
        self.logger.info(f"{device_info}")
        return device_info

    @instrumented
    def read_flash(self, start_address: str, end_address: str):
        """
        Called when to read Si91x device flash between start address and end address

        Args:
            start_address: ``string`` starting address for reading flash
            end_address: ``string`` end address for reading flash

        Returns:
            (dict) commander flash output available through a single level dictionary

        """
        self.logger.info(
            f"Reading Si91x device flash between address {start_address} and address {end_address}:"
            )
        _, raw_flash_output, _ = commander.read_flash(
            start_address, end_address, self.commander_options
            )
        flash_output = commander.convert_commander_output_to_dict(raw_flash_output)
        self.logger.info(f"{flash_output}")
        return flash_output

    @instrumented
    def read_swo(self, timeout_seconds: int = 2):
        """
        Called when to read device SWO output using commander with commander options and timeout seconds

        Args:
            timeout_seconds: ``int`` value for --timeout option in commander command

        Returns:
            ``string`` raw SWO output of device

        """
        self.logger.info("Reading device SWO output:")
        _, raw_swo_output, _ = commander.read_swo(
            self.commander_options, timeout_seconds
            )
        self.logger.info(f"{raw_swo_output}")
        return raw_swo_output

    @instrumented
    def flash_image_to_external_flash(self, firmware_file: str):
        """
        Called when required to write image to the external flash of the device.

        Args:
            firmware_file: ``string`` firmware path value of the file

        Returns:
            None

        """
        self.logger.info(
            f"Writing image '{firmware_file}' to external flash of Si91x device '{self.name}'"
            )
        commander.flash_to_external_flash(firmware_file, self.commander_options)
        self.logger.info(
            f"Image loading to external flash complete on Si91x device '{self.name}'"
            )

    @instrumented
    def write_mfg_token(self, token_name: str, token_value: str):
        """
        Called when required to write image to the external flash of the device.

        Args:
            token_name: ``string`` MFG token name to write
            token_value: ``string`` MFG token value to write

        Returns:
            None

        """
        self.logger.info(
            f"Writing MFG token '{token_name}' with value: '{token_value}' on Si91x device '{self.name}'"
            )
        commander.write_mfg_token(token_name, token_value, self.commander_options)
        self.logger.info(
            f"Writing MFG token write complete on Si91x device '{self.name}'"
            )

    @instrumented
    def write_mfg_token_file(self, token_file: str, token_group: str = "znet"):
        """
        Called when required to write image to the external flash of the device.

        Args:
            token_file: ``string`` MFG token details file path
            token_group: ``string`` token group value

        Returns:
            None

        """
        self.logger.info(
            f"Writing MFG token from file at {token_file} on Si91x device '{self.name}'"
            )
        commander.write_mfg_token_file(token_file, token_group, self.commander_options)
        self.logger.info(
            f"Writing MFG token write complete on Si91x device '{self.name}'"
            )

    @instrumented
    def read_token(self, token_group: str):
        """
        Called when required to dump the token used in write_mfg_token

        Args:
            token_group: ``string`` token group value

        Returns:
            None

        """
        self.logger.info("Dump token")
        commander.read_token(token_group, self.commander_options)
        self.logger.info("Dump token complete")
