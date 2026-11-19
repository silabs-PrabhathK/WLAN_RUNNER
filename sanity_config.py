"""
WLAN Runner configuration.
Modify this file only when a setup, marker, manifest, or plan changes.
"""

# ============================================================
# PROJECT
# ============================================================

PROJECT = {
    "name": "WLAN RUNNER",
    "tagline": "Connectivity, sanity, and regression from one script.",
}

# Folder that contains milestone clones (M99, Milestone100, ...).
# Leave empty to use the parent directory of this project.
# Example: r"D:\lab\milestones"
WORKSPACE_ROOT = ""


RESOURCE_LAYOUT = {
    "NCP": "NCP",
    "SoC": "SoC"
}

# Product names and the setup keys that belong to them.
# Every setup listed here must also exist in EXECUTION_CONFIG.
PRODUCT_SETUPS = {
    "NCP": ["8A", "9A", "23A", "23B"],
    "SoC":["8B", "8C", "9B", "10A", "10C"],
}

# utf_wifi clone. {milestone} becomes milestone99 for a folder named M99.
REPOSITORY = {
    "url": "https://stash.silabs.com/scm/iot_infra_sw/utf_wifi.git",
    "folder": "utf_wifi",
    "branch": "release/{milestone}",
    "required": [
        "tcmgr",
        "utf_core",
        "utf_wifi_zephyr",
        "utf_wiseconnect",
        "utf_wiseconnect_3",
        "workspace_setup.bat",
    ],
}

# Commands run inside utf_wifi after a new clone. {branch} is the full branch.
POST_CLONE_COMMANDS = [
    "git fetch origin {branch}",
    "git checkout {branch}",
    "git submodule update --init --recursive",
    "python -m venv venv",
    "workspace_setup.bat",
]

# Existing clone update. Asked only when the user chooses to update.
CLONE_UPDATE_COMMAND = "git pull"

# ============================================================
# HARNESS PRECONDITIONS
# Any value defined here will override the generated harness.
# If key is not present here, value from previous milestone
# (or resource harness) will be used.
# ============================================================

# Optional keys on a setup: pi_ip, pi_user, pi_password, pi_reboot_wait.
# pi_ip defaults to target_ip. Login defaults to pi / raspberry,
# unless RASPI_USERNAME and RASPI_PASSWORD are set in wlan_runner.local.env.
EXECUTION_CONFIG = {
    "8A": {
        "display_name": "8A (PDU_2EVK)",
        "target_ip": "10.207.18.15",
        "harness": "harness_example_ncp_si917_sdk_8A.yaml"
    },
    "8B": {
        "display_name": "8B (PDU_2AP_2Raspi)",
        "target_ip": "10.207.18.24",
        "harness": "harness_example_SOC_Need_to_update.yaml"
    },
    "8C": {
        "display_name": "8C (PDU_2EVK_2AP_4Raspi)",
        "target_ip": "10.207.18.214",
        "harness": "harness_example_SOC_Need_to_update.yaml"
    },
    "9A": {
        "display_name": "9A (PDU_Multi-Raspi)",
        "target_ip": "10.207.18.65",
        "harness": "harness_example_ncp_si917_sdk_9A.yaml"
    },
    "9B": {
        "display_name": "9B (PDU_2EVK_2Raspi)",
        "target_ip": "10.207.18.61",
        "harness": "harness_example_SOC_Need_to_update.yaml"
    },
    "10A": {
        "display_name": "10A (PDU_2Raspi)",
        "target_ip": "10.207.18.148",
        "harness": "harness_example_SOC_Need_to_update.yaml"
    },
    "10C": {
        "display_name": "10C (PDU_2Raspi)",
        "target_ip": "10.207.18.29",
        "harness": "harness_example_SOC_Need_to_update.yaml"
    },
    "23A": {
        "display_name": "23A",
        "target_ip": "10.207.18.52",
        "harness": "harness_example_ncp_si917_sdk_23A.yaml"
    },
    "23B": {
        "display_name": "23B (PDU)",
        "target_ip": "10.207.18.66",
        "harness": "harness_example_ncp_si917_sdk_23B.yaml"
    },
}

# Names written into the milestone manifest folder.
# without_firmware_alias keeps the previous long filename working.
MANIFEST_FILES = {
    "standard": "manifest_917_ncp.yaml",
    "without_firmware": "manifest_917_ncp_without_fw.yaml",
    "paho": "manifest_917_ncp_paho.yaml",
}

MANIFEST_OPTIONS = {
    "1": MANIFEST_FILES["standard"],
    "2": MANIFEST_FILES["without_firmware"],
}

# ============================================================
# EDIT FOR EVERY BUILD / IFC
# Change marker names here only. Plans reference keys below.
# ============================================================

PYTEST_MARKERS = {
    # Sanity suite marker
    "sanity": "SANITY_RERUN_413_IFC3_rerun", #WLAN_Dev_sanity_917",

    # Main closed-env regression marker
    "regression": "NCP420FCLLVMLTO_rerun",

    #Custom markers for rerun
    "custom": "CUSTOM_RUN_413IFC3"

}

# Shared pytest / launch defaults
PYTEST_DEFAULTS = {
    "base": "pytest --tb=native --count=1",
    "test_results_source_api": "TEST_RAIL_API",
    "publish_test_results": True,
    "upload_reports_to_artifacts": True,
    "rerun_failed_tests": True,
}

# Connectivity test target (single testcase)
CONNECTIVITY_CONFIG = {
    "path": (
        "example_test_package/sqa_test_suites_wifi_sdk_3/"
        "wlan_standalone/functional/join_2_4ghz/"
        "test_join_2_4_sdk.py::"
        "test_wifi_sdk_connectivity_with_11n_mode_c19707"
    ),
    # None = no -m filter; or a key from PYTEST_MARKERS / raw marker string
    "marker": None,
    "ask_manifest": True,
}

# Sanity suite target
SANITY_CONFIG = {
    "path": (
        "example_test_package/sqa_test_suites_wifi_sdk_3/"
        "wlan_standalone/functional"
    ),
    "marker": "sanity",
    "extra_args": "--continue-on-collection-errors",
    "manifest": "manifest_917_ncp.yaml",
}

# Regression plans:
# - category "marker": PYTEST_MARKERS key, or None for no marker
# - plan "path": test file / nodeid
# - plan "marker": override category marker key
# - plan "use_marker": False to force no -m for that plan
# - plan "manifest": override category default_manifest
# - plan "extra_args": optional extra pytest flags
REGRESSION_PLANS = {
    '23A': {'regression': {'label': 'Regression (Closed Env)',
                        'marker': 'regression',
                        'default_manifest': 'manifest_917_ncp_without_fw.yaml',
                        'plans': [{'name': 'apmode_network_stack_l1_and_l2',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_network_stack_l1_and_l2_sdk.py'},
                                  {'name': 'dhcp',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/dhcp_and_dns/test_dhcp_sdk.py'},
                                  {'name': 'dns_server',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/dhcp_and_dns/test_dns_server_sdk.py'},
                                  {'name': 'mdns_ipv6',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mdns_and_sntp/test_mdns_ipv6_sdk.py'},
                                  {'name': 'mdns',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mdns_and_sntp/test_mdns_sdk.py'},
                                  {'name': 'wifi_sntp',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mdns_and_sntp/test_wifi_sntp_sdk.py'},
                                  {'name': 'request_timeout',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/request_timeout_and_rtc_timer/test_request_timeout_sdk.py'},
                                  {'name': 'rtc_ap',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/request_timeout_and_rtc_timer/test_rtc_ap_wifi_sqa_sdk.py'},
                                  {'name': 'rtc_sta',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/request_timeout_and_rtc_timer/test_rtc_sta_wifi_sqa_sdk.py'},
                                  {'name': 'wreck_vulnerability',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/wreck_vulnerability/test_wreck_vulnerability_sdk.py'},
                                  {'name': 'wlan_data_rates',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_wlan_data_rates_sdk.py'},
                                  {'name': 'wmm_qos',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_wmm_qos_sdk.py'},
                                  {'name': '11ax_aggregation',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_11ax_aggregation_sdk.py'},
                                  {'name': 'ipv6_ipv4',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ipv6/test_ipv6_ipv4_sdk.py'},
                                  {'name': 'ipv6',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ipv6/test_ipv6_sdk.py'},
                                  {'name': 'wlan_config_ga',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wlan_config_ga_sdk.py'},
                                  {'name': 'wlan_csa',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wlan_csa_sdk.py'},
                                  {'name': 'wlan_join_wireless_information',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wlan_join_wireless_information_sdk.py'},
                                  {'name': 'https_file_download',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_https_file_download_sdk.py'}]},
         'open_box': {'label': 'Open Box (Open Env)',
                      'marker': None,
                      'default_manifest': 'manifest_917_ncp_without_fw.yaml',
                      'plans': [{'name': 'scan_china_region_c662089',
                                 'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_scan_2_4_sdk.py::test_wifi_sdk_scan_type_extended_enabled_in_China_region_c662089',
                                 'use_marker': False},
                                {'name': 'scan_extended_c653150',
                                 'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_scan_2_4_sdk.py::test_wifi_sdk_scan_type_extended_enabled_c653150',
                                 'use_marker': False}]},
         'stress': {'label': 'Stress (~2 days)',
                    'marker': 'regression',
                    'confirm': 'Stress usually takes about 2 days. Start it now?',
                    'default_manifest': 'manifest_917_ncp.yaml',
                    'plans': [{'name': 'http_https_get_post_stress',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_http_https_get_post_sdk.py'}]}},
    '23B': {'regression': {'label': 'Regression (Closed Env)',
                        'marker': 'regression',
                        'default_manifest': 'manifest_917_ncp_without_fw.yaml',
                        'plans': [{'name': 'http_server',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_http_server_sdk.py'},
                                  {'name': 'storeconfig_autojoin',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wlan_storeconfig_autojoin_sdk.py'},
                                  {'name': 'dns_resolution',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/dhcp_and_dns/test_dns_resolution_sdk.py'},
                                  {'name': 'wps_pbc',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wps_pbc_sdk.py'},
                                  {'name': 'get_nwp_config',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/nwp_config/test_get_nwp_config_sdk.py'},
                                  {'name': 'maxpsp_enhanced',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/powersave/test_wlan_maxpsp_enhanced_maxpsp_sdk.py'},
                                  {'name': 'max_psp_functionality',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/powersave/test_wlan_max_psp_functionality_sdk.py'},
                                  {'name': 'powersave_traffic',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/powersave/test_wlan_powersave_traffic_sdk.py'},
                                  {'name': 'iot_socket',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_iot_socket_sdk.py'},
                                  {'name': 'multicast',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_multicast_wifi_sqa_sdk.py'},
                                  {'name': 'socket_select',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_socket_select_sdk.py'},
                                  {'name': 'tcp_udp_multi_socket_thread',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_tcp_udp_multi_socket_thread_sdk.py'},
                                  {'name': 'tcp_udp_wifi',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_tcp_udp_wifi_sdk.py'},
                                  {'name': 'wmm_aggregation',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/tcp_udp/test_wmm_aggregation_sdk.py'},
                                  {'name': 'wpa3_functional',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa3_functional_sdk.py'},
                                  {'name': 'websocket',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/websocket/test_websocket_sdk.py'},
                                  {'name': 'https_get',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_https_get_sdk.py'},
                                  {'name': 'https_post',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_https_post_sdk.py'},
                                  {'name': 'http_put',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_http_put_sdk.py'},
                                  {'name':'rtc_sta',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/request_timeout_and_rtc_timer/test_rtc_sta_wifi_sqa_sdk.py::test_wifi_sdk_get_rtc_after_rejoin_c19055'},                                 
                                  {'name': 'https_otaf_rejoin',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_rejoin_wifi_sdk.py',
                                   'manifest': 'manifest_917_ncp.yaml'},
                                  {'name': 'https_otaf',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_wifi_sdk.py',
                                   'manifest': 'manifest_917_ncp.yaml'},
                                  {'name': 'http_https_otaf_stress',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_http_https_otaf_sdk_stress.py',
                                   'manifest': 'manifest_917_ncp.yaml'},
                                  {'name': 'http_otaf',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_http_otaf_sdk.py',
                                   'manifest': 'manifest_917_ncp.yaml'},
                                  {'name': 'https_otaf_cloud',
                                   'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_cloud_wifi_sdk.py',
                                   'manifest': 'manifest_917_ncp.yaml'}]},
         'common': {'label': 'Common Cases (Closed Env)',
                    'marker': None,
                    'default_manifest': 'manifest_917_ncp_without_fw.yaml',
                    'plans': [{'name': 'ap_soft_reset_c19450',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_sdk.py::test_wifi_sdk_dut_ap_mode_soft_reset_ap_to_sta_c19450',
                               'use_marker': False},
                              {'name': 'scan_worldwide_c148601',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_scan_2_4_sdk.py::test_wifi_sdk_scan_all_channels_in_worldwide_region_c148601',
                               'use_marker': False},
                              {'name': 'wlan_stats_c19177',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_wlan_stats_c19177',
                               'use_marker': False},
                              {'name': 'traffic_load_c38192',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_join_2_4_sdk.py::test_wifi_sdk_traffic_with_load_default_nwp_fw_active_low_c38192',
                               'use_marker': False},
                              {'name': 'wps_bit_disabled_c893059',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wps_pbc_sdk.py::test_wifi_sdk_sta_wps_bit_disabled_c893059',
                               'use_marker': False},
                              {'name': 'wps_registrar_c893052',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_wps_pbc_sdk.py::test_wifi_sdk_wps_ragistrar_role_c893052',
                               'use_marker': False},
                              {'name': 'rejoin_c19721',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_c19721',
                               'use_marker': False},
                              {'name': 'rejoin_max_retry_c19729',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_max_retry_failure_with_security_mode_change_c19729',
                               'use_marker': False},
                              {'name': 'rejoin_disable_c19733',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_disable_c19733',
                               'use_marker': False},
                              {'name': 'rejoin_disconnect_c19735',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_with_disconnect_c19735',
                               'use_marker': False},
                              {'name': 'rejoin_beacon_miss_c19736',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_beacon_miss_counter_c19736',
                               'use_marker': False},
                              {'name': 'rejoin_scan_interval_c19737',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_scan_interval_1sec_c19737',
                               'use_marker': False},
                              {'name': 'rejoin_bgscan_c19739',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_with_bgscan_c19739',
                               'use_marker': False},
                              {'name': 'rejoin_eu_c19743',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_in_eu_region_c19743',
                               'use_marker': False},
                              {'name': 'wifi_sntp_common',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mdns_and_sntp/test_wifi_sntp_sdk.py',
                               'use_marker': False},
                              {'name': 'http_https_get_post_common',
                               'path': 'example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_http_https_get_post_sdk.py',
                               'marker': 'regression'}]},
            },
    "8A": {"full_runs": {"label": "Full Runs","marker": "regression",
        "plans": [
            {"name": "start_stop_soft_ap", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_start_and_stop_soft_ap.py"},
            {"name": "apmode_2evk", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_2evk.py"},
            {"name": "vs_ie", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_vs_ie_sdk.py"},
            {"name": "wpa3_aput", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_wpa3_aput_mode_sdk.py"},
            {"name": "aws_iot", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/cloud_connectivity/test_aws_iot_wifi_sqa_sdk.py"},
            {"name": "azure_mqtt", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/cloud_connectivity/test_azure_mqtt_sdk.py"},
            {"name": "wlan_provision_via_ap", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_provision_via_ap_sdk.py"},
            {"name": "wpa3_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wpa3_concurrent_mode_sdk.py"},
            {"name": "wlan_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_sdk.py"},
            {"name": "dtls", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/dtls/test_dtls_functionality_sdk.py"},
            {"name": "join_2_4", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/join_2_4ghz/test_join_2_4_sdk.py"},
            {"name": "mbssid", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mbssid/test_wlan_mbssid_sdk.py"},
            {"name": "rejoin", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py"},
            {"name": "2ap_scan_join", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_2ap_scan_join_sdk.py"},
            {"name": "scan_2_4", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_scan_2_4_sdk.py"},
            {"name": "bg_scan", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_wlan_bg_scan_sdk.py"},
            {"name": "passive_scan", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_wlan_sta_passive_scan_functionality_sdk.py"},
            {"name": "pmf_11w", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wlan_pmf_11w_sdk.py"},
            {"name": "ssl_client_legacy", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ssl/test_ssl_client_legacy_wifi_sqa_sdk.py"},
            {"name": "ssl_dynamic_cert", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ssl/test_ssl_dynamic_load_cert_wifi_sdk.py"},
            {"name": "ssl_functionality", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ssl/test_ssl_functionality_sdk.py"},
            {"name": "softap_ble_provisioning", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/softap_provisioning/test_ap_ble_provisioning_softap_sdk.py"},
            {"name": "ssl_advertize_ciphers", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ssl/test_ssl_advertize_ciphers_rsa_ecdsa_sdk.py"},
            {"name": "http_https_get_post", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/http_https/test_http_https_get_post_sdk.py"},
        ]
    },
    "background_scan_scenarios": {"label": "Background Scan Scenarios", "marker": "regression",
        "plans": [
            {
                "name": "request_timeout",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/request_timeout_and_rtc_timer/test_request_timeout_sdk.py",
            },
            {
                "name": "wpa3_conc_tcp_rx_c463724",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wpa3_concurrent_mode_sdk.py::test_wifi_sdk_wpa3_conc_with_11n_mode_tcp_rx_C463724",
                "use_marker": False,
            }
        ]
    },
    "lwip_validation": {"label": "LWIP Validation", "marker": "regression",
        "plans": [
            {
                "name": "lwip_default",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/lwip/test_wlan_sta_lwip_default_timer_sdk.py",
            },
            {
                "name": "lwip_optimized",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/lwip/test_wlan_sta_lwip_optimized_timer_sdk.py",
            },
            {
                "name": "host_mqtt",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mqtt/test_host_mqtt_sdk.py",
                "manifest": "manifest_917_ncp_paho.yaml",
            },
            {
                "name": "mqtt_host_lwip",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mqtt/test_mqtt_on_host_lwip_sdk.py",
            }
        ]
    },
    "rejoin_validation": {"label": "Rejoin Validation", "marker": "regression",
        "plans": [
            {
                "name": "rejoin_scan_all_channels",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_scan_all_channels_c19723",
                "use_marker": False,
            },
            {
                "name": "rejoin_disconnect",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_with_disconnect_c19735",
                "use_marker": False,
            },
            {
                "name": "rejoin_disable",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_disable_c19733",
                "use_marker": False,
            },
            {
                "name": "rejoin_eap_tls",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_eap_tls_c19730",
                "use_marker": False,
            },
            {
                "name": "rejoin_max_retry",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_max_retry_failure_with_security_mode_change_c19729",
                "use_marker": False,
            },
            {
                "name": "rejoin_beacon_miss",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_beacon_miss_count_stats_90_c641350",
                "use_marker": False,
            },
            {
                "name": "rejoin_failure_disable",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_join_failure_with_max_retry_1_rejoin_disable_c877263",
                "use_marker": False,
            }
        ]
    },
    "ip_conflict_validation": {"label": "IP Conflict Validation", "marker": "regression",
        "plans": [
            {
                "name": "ip_conflict",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/dhcp_and_dns/test_ip_conflict_sdk.py",
            }
        ]
    },
    },
    "9A": {

    "full_runs": {
        "label": "Full Runs",
        "marker": "regression",
        "plans": [
            {"name": "apmode_scan", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_scan_sdk.py"},
            {"name": "apmode_sdk", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_sdk.py"},
            {"name": "11ax_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_11ax_concurrent_sdk.py"},
            {"name": "tea_wlan_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_tea_wlan_concurrent_sdk.py"},
            {"name": "websocket_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_websocket_concurrent_sdk.py"},
            {"name": "http_server_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_http_server_sdk.py"},
            {"name": "multi_client", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_multi_client_sdk.py"},
            {"name": "wlan_concurrent", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_sdk.py"},
            {"name": "mqtt", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mqtt/test_mqtt_sdk.py"},
            {"name": "wlan_sta_enterprise", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wlan_sta_enterprise_sdk.py"},
            {"name": "wpa2_enterprise_bypass", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa2_enterprise_bypass_sdk.py"},
            {"name": "wpa2_enterprise", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa2_enterprise_sdk.py"},
            {"name": "wpa2_enterprise_diff_ciphers", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa2_enterprise_with_diff_ciphers_sdk.py"},
            {"name": "wpa3_enhancements", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa3_enhancements_sdk.py"},
            {"name": "wpa3_enhancements_aps", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa3_enhancements_sdk_APs.py"},
            {"name": "wpa3_enterprise", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa3_enterprise_sdk.py"},
            {"name": "reschedule_twt", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/twt/test_reschedule_twt_sta_sdk.py"},
            {"name": "twt_sta", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/twt/test_twt_sta_sdk.py"},
            {"name": "itwt_autoconfig", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/twt/test_wlan_itwt_autoconfig_sdk.py"},
            {"name": "azure_mqtt", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/cloud_connectivity/test_azure_mqtt_sdk.py"},
        ]
    },
    "two_ap_validation": {
        "label": "2 AP Validation",
        "plans": [
            {
                "name": "2ap_same_security_c19065",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_2ap_scan_join_sdk.py::test_wifi_sdk_2aps_same_security_c19065",
                "use_marker": False
            },
            {
                "name": "2ap_diff_security_c19066",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/scan_2_4ghz/test_2ap_scan_join_sdk.py::test_same_2aps_diff_security_c19066",
                "use_marker": False
            }
        ]
    },
    "multi_client_validation": {
        "label": "Multi Client Validation",
        "plans": [
            {
                "name": "concurrent_sta_ap_c19312",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_sdk.py::test_wifi_sdk_concurrent_mode_sta_ap_c19312",
                "use_marker": False
            },
            {
                "name": "wpa3_multi_ap_c113965",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/security_enhancements/test_wpa3_enhancements_sdk_APs.py::test_wifi_sdk_DUT_behavior_in_h2e_with_multi_aps_C113965",
                "use_marker": False
            },
            {
                "name": "multi_client_chinese_ssid_c148578",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_multi_client_sdk.py::test_wifi_sdk_concurrent_mode_with_chinese_char_ssid_and_4_clients_connected_in_conc_mode_c148578",
                "use_marker": False
            },
            {
                "name": "ssl_rx_4_clients_c148561",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/concurrent_mode/test_wlan_concurrent_multi_client_sdk.py::test_wifi_sdk_ssl_rx_with_tls_v1_2_in_when_4_clients_connected_in_conc_mode_c148561",
                "use_marker": False
            },
            {
                "name": "dutap_multiclient_c19432",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/ap_mode/test_apmode_sdk.py::test_wifi_sdk_dutap_multiclient_connect_disconnect_c19432",
                "use_marker": False
            },
            {
                "name": "azure_mqtt_receive_c19524",
                "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/cloud_connectivity/test_azure_mqtt_sdk.py::test_azure_mqtt_receive_with_diff_sizes_C19524",
                "use_marker": False
            }
        ]
    },
    "lwip_validation": {
        "label": "LWIP Validation",
        "marker": "regression",
        "plans": [
            {"name": "lwip_default", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/lwip/test_wlan_sta_lwip_default_timer_sdk.py"},
            {"name": "lwip_optimized", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/lwip/test_wlan_sta_lwip_optimized_timer_sdk.py"},
            {"name": "host_mqtt", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mqtt/test_host_mqtt_sdk.py", "manifest": "manifest_917_ncp_paho.yaml"},
            {"name": "mqtt_on_host_lwip", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/mqtt/test_mqtt_on_host_lwip_sdk.py"},
        ]
    },
    "otaf_validation": {
        "label": "OTAF Validation",
        "marker": "regression",
        "plans": [
            {"name": "https_otaf_cloud", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_cloud_wifi_sdk.py"},
            {"name": "https_otaf_rejoin", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_rejoin_wifi_sdk.py"},
            {"name": "https_otaf", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_https_otaf_wifi_sdk.py"},
            {"name": "http_https_otaf_stress", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_http_https_otaf_sdk_stress.py"},
            {"name": "http_otaf", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/firmware_upgrade/test_http_otaf_sdk.py"},
        ]
    },
    "rejoin_validation": {
        "label": "Rejoin Validation",
        "plans": [
            {"name": "rejoin_c19721", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_c19721", "use_marker": False},
            {"name": "rejoin_max_retry_c19729", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_max_retry_failure_with_security_mode_change_c19729", "use_marker": False},
            {"name": "rejoin_disable_c19733", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_disable_c19733", "use_marker": False},
            {"name": "rejoin_disconnect_c19735", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_with_disconnect_c19735", "use_marker": False},
            {"name": "rejoin_beacon_miss_c19736", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_beacon_miss_counter_c19736", "use_marker": False},
            {"name": "rejoin_scan_interval_c19737", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_scan_interval_1sec_c19737", "use_marker": False},
            {"name": "rejoin_bgscan_c19739", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_with_bgscan_c19739", "use_marker": False},
            {"name": "rejoin_eu_c19743", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_rejoin_in_eu_region_c19743", "use_marker": False},
            {"name": "wlan_stats_c19177", "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional/rejoin/test_wlan_rejoin_2G_sdk.py::test_wifi_sdk_wlan_stats_c19177", "use_marker": False},
        ]
    },
},
}


UTF_CORE_CONFIG = {

    "rerun_failed_tests_default":
        "False",

    "pytest_rerunfailures":
        "pytest-rerunfailures==10.2"
}

TEST_AGENT_CONFIG = {

    "sntp_server_ip":
        "10.200.110.11",

    "socket_close_timeout":
        70
}

ARTIFACTORY_CONFIG = {

    "sdk_build_num":
        "22165301",

    "artifactory_url":
        "https://artifactory.silabs.net/artifactory/iotwifi-sqa-reports/917/26Q4/WC_4_1_3_IFC1/4346A_NCP_GCC_CMAKE/",

    # Leave these empty. Put them in wlan_runner.local.env
    # or set ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD
    # before starting WLAN Runner. The local file stays on this PC.
    "username":
        "",

    "password":
        ""
}

BUILD_CONFIG = {

    "rps_filename": #latest FW
        "/SiWG917-B.2.16.5.3.0.1.rps",

    "http_url": #Old FW
        "/SiWG917-B.2.16.5.2.0.10.rps"
}

HARNESS_PRECONDITIONS = {

    "23A": {

        # AP
        "devices.asus_rt_ax3000_ap.interfaces.wifi.ip_address":
            "10.207.18.86",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ssid":
            "AP_23A",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.admin_password":
            "admin@12345",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.channel":
            5,

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_ip":
            "192.168.50.222",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_port":
            "1812",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ap_test_ip":
            "192.168.50.4",

        # Sniffer
        "devices.airpcap.interfaces.local_shell.remote":
            "10.207.20.228",

        "devices.airpcap.interfaces.live_capture.host_address":
            "10.207.22.154",

        # Raspberry Pi
        "devices.raspi_wifi_ssh.interfaces.linux_shell.remote":
            "10.208.71.231",

        # Radius
        "devices.raspi_radius_server.interfaces.radius_server.ap_ip_address":
            "192.168.50.4/24",

        "devices.raspi_radius_server_v2.interfaces.radius_server.ap_ip_address":
            "192.168.50.4/24",

        # IOP
        "defaults.iop_sockets.server_ip":
            "192.168.50.190",

        "defaults.iop_sockets.server_port":
            "5007",

        # IOT
        "defaults.iot_sockets.server_ip":
            "192.168.50.222",

        "defaults.iot_sockets.port":
            "8989",

        # Firmware
        "defaults.rps_filename.value":
            BUILD_CONFIG["rps_filename"],

        "defaults.http_url":
            BUILD_CONFIG["http_url"]
    },

    "23B": {

        # AP
        "devices.asus_rt_ax3000_ap.interfaces.wifi.ip_address":
            "10.207.20.79",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ssid":
            "AP_23B",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.admin_password":
            "admin@12345",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.channel":
            5,

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_ip":
            "192.168.50.145",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_port":
            "1812",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ap_test_ip":
            "192.168.50.3",

        # Sniffer
        "devices.airpcap.interfaces.local_shell.remote":
            "10.207.23.149",

        "devices.airpcap.interfaces.live_capture.host_address":
            "10.207.22.154",

        # Raspberry Pi
        "devices.raspi_wifi_ssh.interfaces.linux_shell.remote":
            "10.208.71.232",

        # Radius
        "devices.raspi_radius_server.interfaces.radius_server.ap_ip_address":
            "192.168.50.3/24",

        "devices.raspi_radius_server_v2.interfaces.radius_server.ap_ip_address":
            "192.168.50.3/24",

        # IOP
        "defaults.iop_sockets.server_ip":
            "192.168.50.213",

        "defaults.iop_sockets.server_port":
            "5027",

        # IOT
        "defaults.iot_sockets.server_ip":
            "192.168.50.145",

        "defaults.iot_sockets.port":
            "8989",

        # Firmware
        "defaults.rps_filename.value":
            BUILD_CONFIG["rps_filename"],

        "defaults.http_url":
            BUILD_CONFIG["http_url"]
    },

    "9A": {

        # AP
        "devices.asus_rt_ax3000_ap.interfaces.wifi.ip_address":
            "192.168.50.1",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ssid":
            "917_NCP_MULTI",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.admin_password":
            "admin@12345",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.channel":
            5,

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_ip":
            "192.168.50.178",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_port":
            "1812",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ap_test_ip":
            "192.168.50.1",

        #PDU
        "devices.switched_ap.interfaces.pdu_switch.hostname":
                    "10.207.18.31",

        "devices.switched_ap.interfaces.pdu_switch.user":
                            "admin",

        "devices.switched_ap.interfaces.pdu_switch.password":
                            "1234",

        "devices.switched_ap.interfaces.pdu_switch.outlet":
                            "2",

        # Sniffer
        "devices.airpcap.interfaces.local_shell.remote":
            "10.207.18.50",

        "devices.airpcap.interfaces.live_capture.host_address":
            "10.207.18.50",

        # Raspberry Pi
        "devices.raspi_wifi_ssh.interfaces.linux_shell.remote":
            "192.168.50.107",

        "devices.raspi_wifi_ssh1.interfaces.linux_shell.remote":
                    "192.168.50.151",

        "devices.raspi_wifi_ssh2.interfaces.linux_shell.remote":
                    "192.168.50.148",

        # Radius
        "devices.raspi_radius_server.interfaces.radius_server.ap_ip_address":
            "192.168.50.1/24",

        "devices.raspi_radius_server_v2.interfaces.radius_server.ap_ip_address":
            "192.168.50.1/24",

        # IOP
        "defaults.iop_sockets.server_ip":
            "192.168.50.154",

        "defaults.iop_sockets.server_port":
            "7003",

        # IOT
        "defaults.iot_sockets.server_ip":
            "192.168.50.217",

        "defaults.iot_sockets.port":
            "6666",

        # Firmware
        "defaults.rps_filename.value":
            BUILD_CONFIG["rps_filename"],

        "defaults.http_url":
            BUILD_CONFIG["http_url"]
    },

    "8A": {

        # AP
        "devices.asus_rt_ax3000_ap.interfaces.wifi.ip_address":
            "192.168.50.2",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ssid":
            "917_NCP_8A",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.admin_password":
            "admin@12345",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.channel":
            10,

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_ip":
            "192.168.50.216",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.radius_port":
            "1812",

        "devices.asus_rt_ax3000_ap.interfaces.wifi.ap_test_ip":
            "192.168.50.2",

        #PDU
        "devices.switched_ap.interfaces.pdu_switch.hostname":
                    "10.207.18.74",

        "devices.switched_ap.interfaces.pdu_switch.user":
                            "admin",

        "devices.switched_ap.interfaces.pdu_switch.password":
                            "1234",

        "devices.switched_ap.interfaces.pdu_switch.outlet":
                            "4",

        # Sniffer
        "devices.airpcap.interfaces.local_shell.remote":
            "10.207.18.73",

        "devices.airpcap.interfaces.live_capture.host_address":
            "10.207.18.73",

        # Raspberry Pi
        "devices.raspi_wifi_ssh.interfaces.linux_shell.remote":
            "10.207.18.84",


        # Radius
        "devices.raspi_radius_server.interfaces.radius_server.ap_ip_address":
            "192.168.50.2/24",

        "devices.raspi_radius_server_v2.interfaces.radius_server.ap_ip_address":
            "192.168.50.2/24",

        # IOP
        "defaults.iop_sockets.server_ip":
            "192.168.50.233",

        "defaults.iop_sockets.server_port":
            "7001",

        # IOT
        "defaults.iot_sockets.server_ip":
            "192.168.50.216",

        "defaults.iot_sockets.port":
            "6666",

        # Firmware
        "defaults.rps_filename.value":
            BUILD_CONFIG["rps_filename"],

        "defaults.http_url":
            BUILD_CONFIG["http_url"]
    }
}

BUILD_DETAILS = {

    "firmware": "SiWG917-B.2.16.5.3.0.1.rps",

    "build": "4.1.3_IFC1",

    "compiler": "GCC",

    "stack": "917"
}

EMAIL_SETTINGS = {

    "to": [

        "prabhath.kattupalli@silabs.com"
    ],

    "cc": []#"Shobharani.Jogu@silabs.com", "Manusha.Bejjam@silabs.com", "Sushma.G@silabs.com", "Srinivasulu.Beluguppa@silabs.com"]
}