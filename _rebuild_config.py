import pathlib
import pprint
import re

config_path = pathlib.Path(__file__).with_name("sanity_config.py")
text = config_path.read_text(encoding="utf-8")

from _plans_converted import REGRESSION_PLANS

for plan in REGRESSION_PLANS["23B"]["common"]["plans"]:
    if plan["name"] == "http_https_get_post_common":
        plan["marker"] = "regression"

for setup, cats in REGRESSION_PLANS.items():
    for cat, data in cats.items():
        cleaned = []
        for plan in data["plans"]:
            plan = dict(plan)
            if "marker" in plan and plan["marker"] is None:
                del plan["marker"]
                plan["use_marker"] = False
            cleaned.append(plan)
        data["plans"] = cleaned

idx = text.find("UTF_CORE_CONFIG")
if idx < 0:
    raise SystemExit("UTF_CORE_CONFIG not found")
tail = text[idx:]

match = re.search(r"(MANIFEST_OPTIONS\s*=\s*\{.*?\n\})", text, re.S)
if not match:
    raise SystemExit("MANIFEST_OPTIONS not found")
head = text[: match.end()]

plans_src = pprint.pformat(REGRESSION_PLANS, width=110, sort_dicts=False)

middle = f'''

# ============================================================
# EDIT FOR EVERY BUILD / IFC
# Change marker names here only. Plans reference keys below.
# ============================================================

PYTEST_MARKERS = {{
    # Sanity suite marker
    "sanity": "WLAN_Dev_sanity_917",

    # Main closed-env regression marker
    "regression": "NCP420IFC3OCT15_RERUN",

    # Firmware / OTAF marker
    "firmware": "NCP420IFC2OCT9",
}}

# Shared pytest / launch defaults
PYTEST_DEFAULTS = {{
    "base": "pytest --tb=native --count=1",
    "rerun_failed_tests": True,
    "publish_test_results": True,
    "upload_reports_to_artifacts": True,
    "test_results_source_api": "TEST_RAIL_API",
}}

# Connectivity test target (single testcase)
CONNECTIVITY_CONFIG = {{
    "path": (
        "example_test_package/sqa_test_suites_wifi_sdk_3/"
        "wlan_standalone/functional/join_2_4ghz/"
        "test_join_2_4_sdk.py::"
        "test_wifi_sdk_connectivity_with_11n_mode_c19707"
    ),
    # None = no -m filter; or a key from PYTEST_MARKERS / raw marker string
    "marker": None,
    "ask_manifest": True,
}}

# Sanity suite target
SANITY_CONFIG = {{
    "path": (
        "example_test_package/sqa_test_suites_wifi_sdk_3/"
        "wlan_standalone/functional"
    ),
    "marker": "sanity",
    "extra_args": "--continue-on-collection-errors",
    "manifest": "manifest_917_ncp.yaml",
}}

# Regression plans:
# - category "marker": PYTEST_MARKERS key, or None for no marker
# - plan "path": test file / nodeid
# - plan "marker": override category marker key
# - plan "use_marker": False to force no -m for that plan
# - plan "manifest": override category default_manifest
# - plan "extra_args": optional extra pytest flags
REGRESSION_PLANS = {plans_src}


'''

new_text = head + middle + tail
config_path.write_text(new_text, encoding="utf-8")
compile(new_text, "sanity_config.py", "exec")
print("sanity_config.py rewritten successfully")
