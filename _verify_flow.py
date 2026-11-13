"""Checks command shape, report rollup, and the single final report."""

import os
import shutil
import tempfile
import time

import wlan_runner
from sanity_config import BUILD_DETAILS, EXECUTION_CONFIG, PYTEST_MARKERS, REGRESSION_PLANS
from test_mail import counts_from_reports, generate_html, parse_report


def write_html(path, passed=0, failed=0, errors=0, harness="harness_example_ncp_si917_sdk_23A.yaml"):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "9 passed 9 failed firmware 1711.2.17.5.0.0.50 "
            f'<span class="passed">{passed} passed</span>'
            f'<span class="failed">{failed} failed</span>'
            f'<span class="error">{errors} errors</span>'
            f" harness={harness}"
        )


def main():
    sanity_plan = wlan_runner.materialize_plan(None, {
        "name": "sanity",
        "path": "example_test_package/sqa_test_suites_wifi_sdk_3/wlan_standalone/functional",
        "marker": "sanity",
        "extra_args": "--continue-on-collection-errors",
        "manifest": "manifest_917_ncp.yaml",
    })
    command = wlan_runner.launch_command_for("23A", sanity_plan)
    assert "--target=10.207.18.52" in command
    assert "harness_example_ncp_si917_sdk_23A.yaml" in command
    assert "-m WLAN_Dev_sanity_917" in command
    assert "--continue-on-collection-errors" in command
    assert "/app/manifest/manifest_917_ncp.yaml" in command

    command_b = wlan_runner.build_launch_command(
        "23B",
        wlan_runner.build_pytest_command(
            REGRESSION_PLANS["23B"]["regression"]["plans"][0]["path"],
            PYTEST_MARKERS["regression"],
        ),
        REGRESSION_PLANS["23B"]["regression"]["default_manifest"],
    )
    assert "--target=10.207.18.66" in command_b
    assert "test_http_server_sdk.py" in command_b
    assert "-m NCP420IFC3OCT15_RERUN" in command_b
    assert "manifest_917_ncp_without_fw.yaml" in command_b

    open_box = wlan_runner.materialize_plan(
        REGRESSION_PLANS["23A"]["open_box"],
        REGRESSION_PLANS["23A"]["open_box"]["plans"][0],
    )
    open_command = wlan_runner.launch_command_for("23A", open_box)
    assert " -m " not in open_command
    assert "test_wifi_sdk_scan_type_extended_enabled_in_China_region_c662089" in open_command

    firmware = wlan_runner.materialize_plan(
        REGRESSION_PLANS["23B"]["regression"],
        next(
            plan for plan in REGRESSION_PLANS["23B"]["regression"]["plans"]
            if plan["name"] == "https_otaf"
        ),
    )
    firmware_command = wlan_runner.launch_command_for("23B", firmware)
    assert "-m NCP420IFC2OCT9" in firmware_command
    assert "/app/manifest/manifest_917_ncp.yaml" in firmware_command

    common = wlan_runner.materialize_plan(
        REGRESSION_PLANS["23B"]["common"],
        next(
            plan for plan in REGRESSION_PLANS["23B"]["common"]["plans"]
            if plan["name"] == "wifi_sntp_common"
        ),
    )
    assert common["marker"] is None
    common_marked = wlan_runner.materialize_plan(
        REGRESSION_PLANS["23B"]["common"],
        next(
            plan for plan in REGRESSION_PLANS["23B"]["common"]["plans"]
            if plan["name"] == "http_https_get_post_common"
        ),
    )
    assert common_marked["marker"] == "NCP420IFC3OCT15_RERUN"
    assert common_marked["manifest"] == "manifest_917_ncp_without_fw.yaml"

    assert list(REGRESSION_PLANS["23A"]) == ["regression", "open_box", "stress"]
    assert list(REGRESSION_PLANS["23B"]) == ["regression", "common"]
    assert len(REGRESSION_PLANS["23A"]["regression"]["plans"]) == 20
    assert len(REGRESSION_PLANS["23A"]["open_box"]["plans"]) == 2
    assert len(REGRESSION_PLANS["23A"]["stress"]["plans"]) == 1
    assert len(REGRESSION_PLANS["23B"]["regression"]["plans"]) == 23
    assert len(REGRESSION_PLANS["23B"]["common"]["plans"]) == 16
    assert EXECUTION_CONFIG["23A"]["target_ip"] == "10.207.18.52"
    assert EXECUTION_CONFIG["23B"]["target_ip"] == "10.207.18.66"
    assert wlan_runner.parse_plan_selection("1,3,5-7", 10) == [0, 2, 4, 5, 6]
    assert wlan_runner.git_branch_for("M99") == "release/milestone99"
    assert wlan_runner.format_duration(3723) == "1h 02m 03s"

    os.environ.pop("ARTIFACTORY_USERNAME", None)
    os.environ.pop("ARTIFACTORY_PASSWORD", None)
    wlan_runner.load_local_env()
    username, password = wlan_runner.artifactory_credentials()
    assert username
    assert password
    for setup, categories in REGRESSION_PLANS.items():
        for category in categories.values():
            for plan in category["plans"]:
                ready = wlan_runner.materialize_plan(category, plan)
                command = wlan_runner.launch_command_for(setup, ready)
                assert f"--target={EXECUTION_CONFIG[setup]['target_ip']}" in command
                assert EXECUTION_CONFIG[setup]["harness"] in command
                assert ready["manifest"] in command
                assert plan["path"] in command
                if ready["marker"]:
                    assert f"-m {ready['marker']}" in command
                else:
                    assert " -m " not in command

    root = tempfile.mkdtemp()
    try:
        wlan_runner.CURRENT_SETUP = "23A"
        wlan_runner.CURRENT_PRODUCT = "NCP"
        wlan_runner.CURRENT_TEST_TYPE = "Regression"
        wlan_runner.CURRENT_CATEGORY = "regression"
        wlan_runner.CURRENT_CATEGORY_LABEL = "Regression (Closed Env)"
        wlan_runner.CURRENT_RUN_ID = "23A_Regression_regression_test"
        wlan_runner.CURRENT_TEST_NODE = None
        wlan_runner.SCRIPT_STARTED_AT = time.time() - 125

        reports_dir = os.path.join(root, "raw")
        os.makedirs(reports_dir)
        first = os.path.join(
            reports_dir,
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa-functional~dhcp_and_dns~"
            "test_dhcp_sdk.py-pytest-report.html",
        )
        second = os.path.join(
            reports_dir,
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb-functional~dhcp_and_dns~"
            "test_dhcp_sdk.py-pytest-report.html",
        )
        third = os.path.join(
            reports_dir,
            "cccccccc-cccc-cccc-cccc-cccccccccccc-functional~http_https~"
            "test_https_get_sdk.py-pytest-report.html",
        )
        write_html(first, failed=2)
        time.sleep(0.05)
        write_html(second, passed=5)
        write_html(third, failed=1, errors=1)

        summary = wlan_runner.aggregate_run_results([first, second, third])
        assert summary["passed"] == 5, summary
        assert summary["failed"] == 1, summary
        assert summary["errors"] == 1, summary
        assert len(summary["plan_rows"]) == 2, summary["plan_rows"]
        assert summary["firmware"] == BUILD_DETAILS["firmware"]
        assert "1711" not in summary["firmware"]

        parsed = parse_report(second)
        assert parsed["passed"] == 5, parsed
        assert parsed["failed"] == 0, parsed
        assert parsed["firmware"] == BUILD_DETAILS["firmware"]
        assert parsed["setup"] == "23A"
        assert "harness_example_ncp_si917_sdk_23A.yaml" in parsed["harness"]

        wlan_runner.enrich_summary(summary, [second, third])
        assert "m" in summary["runtime"] or "s" in summary["runtime"]
        html = generate_html(summary)
        assert "WLAN 917 REGRESSION REPORT" in html
        assert "Runtime" in html
        assert summary["runtime"] in html
        assert "test_dhcp_sdk.py" in html
        assert "test_https_get_sdk.py" in html

        mailed = counts_from_reports([first, second])
        assert mailed["passed"] == 5, mailed
        assert mailed["failed"] == 2, mailed
        assert mailed["total"] == 7, mailed

        passed_only = wlan_runner.select_mail_attachments([second])
        assert passed_only == [second]

        failed_run = wlan_runner.select_mail_attachments([first, second, third])
        assert len(failed_run) == 2
        assert third in failed_run
        assert first in failed_run

        print("ALL CHECKS PASSED")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
