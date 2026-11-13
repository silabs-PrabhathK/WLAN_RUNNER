"""WLAN Runner mail and the single final report."""

import os
import re
from datetime import datetime

import win32com.client as win32

from sanity_config import BUILD_DETAILS, EMAIL_SETTINGS, PROJECT

REPORTS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")

def _esc(value):
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def write_plain_summary(folder, summary):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "runtime.txt")
    lines = [
        f"project={PROJECT.get('name', 'WLAN Runner')}",
        f"run_id={summary.get('run_id', '')}",
        f"test={summary.get('test_type', '')}",
        f"category={summary.get('category_label', '')}",
        f"setup={summary.get('setup', '')}",
        f"status={summary.get('status', '')}",
        f"runtime={summary.get('runtime', '')}",
        f"passed={summary.get('passed', 0)}",
        f"failed={summary.get('failed', 0)}",
        f"errors={summary.get('errors', 0)}",
        f"total={summary.get('total', 0)}",
        "",
    ]
    for row in summary.get("plan_rows") or []:
        lines.append(
            f"{row.get('name', '')}"
            f" | {row.get('status', '')}"
            f" | passed={row.get('passed', 0)}"
            f" failed={row.get('failed', 0)}"
            f" errors={row.get('errors', 0)}"
            f" | {row.get('duration', '')}"
        )
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def generate_html(results):
    test_type = _esc(results.get("test_type") or "WLAN")
    attachment_section = ""
    if results.get("attachment_count", 0):
        attachment_section = f"""
<tr>
<td colspan="4"
    style="
        padding:18px;
        border:1px solid #E2E8F0;
        background:#F8FAFC;
        font-size:15px;
        line-height:1.6;
    ">
<b>Attached Report</b><br>
{_esc(results.get('report_name', ''))}
<br>
<span style="color:#64748B;">
Attachments: {_esc(results.get('attachment_count', 1))}
</span>
</td>
</tr>
"""
    return f"""
<html>
<body style="
    margin:0;
    padding:25px;
    background:#F4F7FB;
    font-family:'Segoe UI',Arial,sans-serif;
">
<table width="100%"
       cellpadding="0"
       cellspacing="0"
       style="
            max-width:1200px;
            margin:auto;
            border-collapse:collapse;
            background:white;
            border:1px solid #E2E8F0;
            box-shadow:0 4px 12px rgba(0,0,0,0.08);
       ">
<tr>
<td colspan="4"
    align="center"
    style="
        background:#0F172A;
        padding:40px;
    ">
<div style="
    color:white;
    font-size:40px;
    font-weight:700;
    letter-spacing:1px;
">
WLAN 917 {_esc(results.get('test_type', 'WLAN')).upper()} REPORT
</div>
<div style="
    color:#CBD5E1;
    font-size:16px;
    margin-top:10px;
">
Silicon Labs Wireless Quality Assurance
</div>
<div style="
    color:white;
    font-size:18px;
    margin-top:12px;
">
{test_type}
</div>
</td>
</tr>
<tr>
<td colspan="4" style="padding:25px;">
<table width="100%" cellpadding="10" cellspacing="10">
<tr>
<td align="center"
    style="
        background:#2563EB;
        color:white;
        padding:25px;
        border-radius:10px;
    ">
<div style="font-size:16px;">TOTAL</div>
<div style="
    font-size:50px;
    font-weight:700;
">
{_esc(results.get('total', 0))}
</div>
</td>
<td align="center"
    style="
        background:#059669;
        color:white;
        padding:25px;
        border-radius:10px;
    ">
<div style="font-size:16px;">PASSED</div>
<div style="
    font-size:50px;
    font-weight:700;
">
{_esc(results.get('passed', 0))}
</div>
</td>
<td align="center"
    style="
        background:#DC2626;
        color:white;
        padding:25px;
        border-radius:10px;
    ">
<div style="font-size:16px;">FAILED</div>
<div style="
    font-size:50px;
    font-weight:700;
">
{_esc(results.get('failed', 0))}
</div>
</td>
<td align="center"
    style="
        background:#D97706;
        color:white;
        padding:25px;
        border-radius:10px;
    ">
<div style="font-size:16px;">ERRORS</div>
<div style="
    font-size:50px;
    font-weight:700;
">
{_esc(results.get('errors', 0))}
</div>
</td>
</tr>
</table>
</td>
</tr>
<tr>
<td style="
    padding:18px;
    border:1px solid #E2E8F0;
    background:#F8FAFC;
    font-size:15px;
    line-height:1.6;
">
<b>Date</b><br>
{_esc(results.get('date', ''))}
</td>
<td style="
    padding:18px;
    border:1px solid #E2E8F0;
    background:#F8FAFC;
    font-size:15px;
    line-height:1.6;
">
<b>Milestone</b><br>
{_esc(results.get('milestone', ''))}
</td>
<td style="
    padding:18px;
    border:1px solid #E2E8F0;
    background:#F8FAFC;
    font-size:15px;
    line-height:1.6;
">
<b>Product Type</b><br>
{_esc(results.get('product_type', ''))}
</td>
<td style="
    padding:18px;
    border:1px solid #E2E8F0;
    background:#F8FAFC;
    font-size:15px;
    line-height:1.6;
">
<b>Setup</b><br>
{_esc(results.get('setup', ''))}
</td>
</tr>
<tr>
<td style="padding:18px;border:1px solid #E2E8F0;font-size:15px;line-height:1.6;">
<b>Firmware</b><br>
{_esc(results.get('firmware', ''))}
</td>
<td style="padding:18px;border:1px solid #E2E8F0;font-size:15px;line-height:1.6;">
<b>Build</b><br>
{_esc(results.get('build', ''))}
</td>
<td style="padding:18px;border:1px solid #E2E8F0;font-size:15px;line-height:1.6;">
<b>Compiler</b><br>
{_esc(results.get('compiler', ''))}
</td>
<td style="padding:18px;border:1px solid #E2E8F0;font-size:15px;line-height:1.6;">
<b>Stack</b><br>
{_esc(results.get('stack', ''))}
</td>
</tr>
<tr>
<td colspan="2"
    style="
        padding:18px;
        border:1px solid #E2E8F0;
        font-size:15px;
        line-height:1.6;
    ">
<b>Harness File</b><br>
{_esc(results.get('harness', ''))}
</td>
<td colspan="2"
    style="
        padding:18px;
        border:1px solid #E2E8F0;
        font-size:15px;
        line-height:1.6;
    ">
<b>Runtime</b><br>
{_esc(results.get('runtime', 'N/A'))}
</td>
</tr>
{attachment_section}
</table>
<br>
{_plan_table(results)}
</body>
</html>
"""


def _plan_table(results):
    rows = results.get("plan_rows") or []
    if not rows:
        return ""
    body = []
    for row in rows:
        color = "#059669" if row.get("status") == "PASSED" else "#DC2626"
        body.append(
            "<tr>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;\">{_esc(row.get('name', ''))}</td>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;color:{color};font-weight:700;\">{_esc(row.get('status', ''))}</td>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;\">{_esc(row.get('passed', 0))}</td>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;\">{_esc(row.get('failed', 0))}</td>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;\">{_esc(row.get('errors', 0))}</td>"
            f"<td style=\"padding:8px;border:1px solid #E2E8F0;\">{_esc(row.get('duration', ''))}</td>"
            "</tr>"
        )
    return (
        "<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"max-width:1200px;margin:16px auto;border-collapse:collapse;background:white;\">"
        "<tr style=\"background:#0F172A;color:white;\">"
        "<th align=\"left\" style=\"padding:8px;\">Plan</th>"
        "<th align=\"left\" style=\"padding:8px;\">Status</th>"
        "<th align=\"left\" style=\"padding:8px;\">Passed</th>"
        "<th align=\"left\" style=\"padding:8px;\">Failed</th>"
        "<th align=\"left\" style=\"padding:8px;\">Errors</th>"
        "<th align=\"left\" style=\"padding:8px;\">Duration</th>"
        "</tr>"
        + "".join(body)
        + "</table>"
    )


def send_summary(final_report, summary):
    """Kept for a one-report resend. Campaign mail uses send_latest_report."""
    return send_latest_report(final_report, runtime=summary.get("runtime"), test_type=summary.get("test_type"))


def pytest_counts(content):
    """Read the pytest-html summary spans. Fall back only when those spans are absent."""
    has_spans = 'class="passed"' in content.lower() or 'class="failed"' in content.lower()
    passed = _span_count(content, "passed", "passed")
    failed = _span_count(content, "failed", "failed")
    errors = _span_count(content, "error", "errors?")
    if has_spans:
        return passed, failed, errors
    return (
        _loose_count(content, r"(\d+)\s+passed"),
        _loose_count(content, r"(\d+)\s+failed"),
        _loose_count(content, r"(\d+)\s+errors?"),
    )


def _span_count(content, css_class, word):
    match = re.search(
        rf'class="{css_class}">(\d+)\s+{word}',
        content,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else 0


def _loose_count(content, pattern):
    match = re.search(pattern, content, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def counts_from_reports(report_files):
    report_data = []
    for report_file in report_files or []:
        if not report_file or not os.path.isfile(report_file):
            continue
        with open(
            report_file,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as handle:
            content = handle.read()
        current_passed, current_failed, current_errors = pytest_counts(content)
        report_data.append({
            "file": report_file,
            "passed": current_passed,
            "failed": current_failed,
            "errors": current_errors,
            "total": current_passed + current_failed + current_errors
        })
    if not report_data:
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "status": "EMPTY",
            "primary": None
        }
    report_data.sort(
        key=lambda item: item["total"],
        reverse=True
    )
    primary = report_data[0]
    if len(report_data) == 1:
        passed = primary["passed"]
        failed = primary["failed"]
        errors = primary["errors"]
        total = primary["total"]
    else:
        rerun = report_data[1]
        passed = primary["passed"] + rerun["passed"]
        failed = rerun["failed"]
        errors = rerun["errors"]
        total = primary["total"]
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": total,
        "status": status_from_counts(
            passed,
            failed,
            errors
        ),
        "primary": primary["file"]
    }


def send_latest_report(report_files, runtime=None, test_type=None, headline=None):
    if isinstance(report_files, str):
        report_files = [report_files]
    report_files = [
    path for path in report_files
    if path and os.path.isfile(path)
    ]
    if not report_files and not headline:
        print("\nNo valid HTML attachments to mail")
        return False

    if report_files:
        counted = counts_from_reports(report_files)
        primary_report = counted["primary"] or report_files[-1]
        final_results = parse_report(primary_report)
    else:
        primary_report = ""
        counted = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "status": "EMPTY",
        }
        final_results = {}
    final_results.update({
        "passed": counted["passed"],
        "failed": counted["failed"],
        "errors": counted["errors"],
        "total": counted["total"],
        "status": counted["status"],
    })
    if headline:
        for key in (
            "passed", "failed", "errors", "total", "status", "plan_rows",
            "milestone", "firmware", "harness", "setup", "product_type",
            "build", "compiler", "stack", "category_label", "run_id",
        ):
            if key in headline:
                final_results[key] = headline[key]
        final_results["status"] = status_from_counts(
            final_results.get("passed", 0),
            final_results.get("failed", 0),
            final_results.get("errors", 0),
        )
    final_results["attachment_count"] = len(report_files)
    final_results["report_name"] = (
    os.path.basename(primary_report)
    if primary_report
    else "Regression Summary"
    )
    if runtime:
        final_results["runtime"] = runtime
    if test_type:
        final_results["test_type"] = test_type
    if "date" not in final_results or not final_results.get("date"):
        final_results["date"] = datetime.now().strftime("%d-%b-%Y")
    html_body = generate_html(final_results)
    return send_mail(report_files, html_body, final_results)


def get_html_report():
    html_files = []
    for root, dirs, files in os.walk(REPORTS_FOLDER):
        for file in files:
            if file.lower().endswith(".html") and file.lower() != "pytest-report.html":
                html_files.append(os.path.join(root, file))
    if not html_files:
        raise Exception("No HTML report found.")
    return max(html_files, key=os.path.getmtime)


def get_setup_from_harness(harness):
    match = re.search(r"sdk_([0-9]+[A-Z])", harness, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return "UNKNOWN"


def get_product_type(harness):
    lowered = harness.lower()
    if "_ncp_" in lowered:
        return "NCP"
    if "_soc_" in lowered:
        return "SoC"
    return "UNKNOWN"


def parse_report(report_file):
    with open(report_file, "r", encoding="utf-8", errors="ignore") as file:
        content = file.read()

    results = {
        "date": datetime.now().strftime("%d-%b-%Y"),
        "milestone": "UNKNOWN",
        "firmware": BUILD_DETAILS.get("firmware", "UNKNOWN"),
        "runtime": "N/A",
        "harness": "UNKNOWN",
        "setup": "UNKNOWN",
        "product_type": "UNKNOWN",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "total": 0,
        "build": BUILD_DETAILS.get("build", "UNKNOWN"),
        "compiler": BUILD_DETAILS.get("compiler", "UNKNOWN"),
        "stack": BUILD_DETAILS.get("stack", "UNKNOWN"),
        "report_name": os.path.basename(report_file),
        "status": "UNKNOWN",
        "attachment_count": 1,
        "plan_rows": [],
        "test_type": "WLAN",
        "category_label": "",
        "archived_reports": 1,
        "run_id": "",
    }

    milestone = re.search(r"release/(milestone\d+)", content, re.IGNORECASE)
    if milestone:
        value = milestone.group(1)
        results["milestone"] = value.replace("milestone", "Milestone")

    results["passed"], results["failed"], results["errors"] = pytest_counts(content)
    results["total"] = results["passed"] + results["failed"] + results["errors"]
    results["status"] = status_from_counts(
        results["passed"], results["failed"], results["errors"]
    )
    results["firmware"] = BUILD_DETAILS.get("firmware", "UNKNOWN")

    harness = re.search(r"harness[^\"'<>\s]+\.ya?ml", content, re.IGNORECASE)
    if harness:
        harness_name = os.path.basename(harness.group(0).split("=")[-1])
        results["harness"] = harness_name
        results["setup"] = get_setup_from_harness(harness_name)
        results["product_type"] = get_product_type(harness_name)
    return results


def status_from_counts(passed, failed, errors):
    if failed or errors:
        return "FAILED"
    if passed:
        return "PASSED"
    return "EMPTY"


def send_mail(report_files, html_body, results):
    outlook = win32.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ";".join(EMAIL_SETTINGS.get("to", []))
    mail.CC = ";".join(EMAIL_SETTINGS.get("cc", []))
    mail.Subject = (
        f"[{results.get('setup', '')}] "
        f"{results.get('product_type', '')} "
        f"{results.get('test_type', 'WLAN')} REPORT"
    )
    mail.HTMLBody = html_body

    attached = set()
    for report in report_files:
        absolute_path = os.path.abspath(report)
        if absolute_path in attached or not os.path.isfile(absolute_path):
            continue
        mail.Attachments.Add(absolute_path)
        attached.add(absolute_path)
        print(f"Attached : {os.path.basename(absolute_path)}")

    mail.Send()
    print("\nMail sent")
    return True


def main():
    report_file = get_html_report()
    send_latest_report(report_file)


if __name__ == "__main__":
    main()
