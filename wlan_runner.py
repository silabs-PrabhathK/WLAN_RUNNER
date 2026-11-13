"""
WLAN Runner

One script for WLAN connectivity, sanity, and regression.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

from sanity_config import (
    ARTIFACTORY_CONFIG,
    BUILD_CONFIG,
    BUILD_DETAILS,
    CLONE_UPDATE_COMMAND,
    CONNECTIVITY_CONFIG,
    EXECUTION_CONFIG,
    MANIFEST_OPTIONS,
    POST_CLONE_COMMANDS,
    PRODUCT_SETUPS,
    PROJECT,
    PYTEST_DEFAULTS,
    PYTEST_MARKERS,
    REGRESSION_PLANS,
    REPOSITORY,
    SANITY_CONFIG,
    TEST_AGENT_CONFIG,
    UTF_CORE_CONFIG,
    WORKSPACE_ROOT,
    RESOURCE_LAYOUT,
)
from test_mail import (
    counts_from_reports,
    parse_report,
    pytest_counts,
    send_latest_report,
    status_from_counts,
    write_plain_summary,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_FOLDER = os.path.join(PROJECT_ROOT, "Reports")
LOGS_FOLDER = os.path.join(PROJECT_ROOT, "Logs")
RESOURCES_FOLDER = os.path.join(PROJECT_ROOT, "Resources")
LOG_FILE = os.path.join(LOGS_FOLDER, "sanity_log.txt")
WORKSPACE_MEMORY = os.path.join(PROJECT_ROOT, "wlan_runner_workspace.path")
LOCAL_ENV_FILE = os.path.join(PROJECT_ROOT, "wlan_runner.local.env")

WORKSPACE = None
CURRENT_MILESTONE = None
CURRENT_SETUP = None
CURRENT_PRODUCT = None
CURRENT_TEST_TYPE = None
CURRENT_CATEGORY = None
CURRENT_CATEGORY_LABEL = None
CURRENT_RUN_ID = None
CURRENT_RUN_START = None
CURRENT_TEST_NODE = None
CURRENT_REPORT_SNAPSHOT = {}
SCRIPT_STARTED_AT = None
ENV_READY_KEY = None
COLOR_ENABLED = False

REPORT_MTIME_SLACK_SECONDS = 5
_UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-",
    re.IGNORECASE,
)

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "red": "\033[91m",
    "yellow": "\033[93m",
    "dim": "\033[2m",
    "blue": "\033[94m",
    "white": "\033[97m",
}

def reboot_raspberry_pi():
    import paramiko
    pi_ip = EXECUTION_CONFIG[CURRENT_SETUP]["target_ip"]
    if not pi_ip:
        say(
            f"  Raspberry Pi IP not configured for {CURRENT_SETUP}",
            "yellow",
            log=True
        )
        return
    try:
        say(
            f"  Connecting to Raspberry Pi : {pi_ip}",
            "cyan",
            log=True
        )
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )
        ssh.connect(
            hostname=pi_ip,
            username="pi",
            password="raspberry",
            timeout=20
        )
        ssh.exec_command(
            "sudo reboot"
        )
        ssh.close()
        say(
            f"  Reboot triggered : {pi_ip}",
            "green",
            log=True
        )
    except Exception as error:
        say(
            f"  Raspberry Pi reboot failed : {error}",
            "red",
            log=True
        )


def get_resource_root():
    product = CURRENT_PRODUCT or "NCP"
    return os.path.join(
        RESOURCES_FOLDER,
        RESOURCE_LAYOUT[product]
    )

def enable_console():
    global COLOR_ENABLED
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if os.environ.get("NO_COLOR"):
        COLOR_ENABLED = False
        return
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass
    COLOR_ENABLED = True


def paint(text, color):
    if not COLOR_ENABLED or color not in ANSI:
        return text
    return f"{ANSI[color]}{text}{ANSI['reset']}"


def write_log(message):
    try:
        os.makedirs(LOGS_FOLDER, exist_ok=True)
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            log.write(f"[{timestamp}] {message}\n")
            log.flush()
    except OSError as error:
        print(f"Could not write Logs\\sanity_log.txt: {error}")


def say(message="", color=None, log=False):
    printed = paint(message, color) if color else message
    print(printed)
    if log and message:
        write_log(message)


def banner():
    name = PROJECT.get("name", "WLAN Runner")
    tagline = PROJECT.get("tagline", "")
    line = "═" * 64
    say()
    say(paint(f"╔{line}╗", "cyan"))
    say(paint(f"║  {name:<62}║", "cyan"))
    say(paint(f"║  {tagline[:62]:<62}║", "cyan"))
    say(paint(f"╚{line}╝", "cyan"))


def section(title):
    say()
    say(paint(f"── {title} ", "blue") + paint("─" * max(8, 58 - len(title)), "dim"))


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def progress_bar(done, total, width=24):
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, int(width * done / total)))
    return ("█" * filled) + ("░" * (width - filled))


def context_line():
    parts = []
    if CURRENT_MILESTONE:
        parts.append(CURRENT_MILESTONE)
    if CURRENT_PRODUCT and CURRENT_SETUP:
        parts.append(f"{CURRENT_PRODUCT} {CURRENT_SETUP}")
    elif CURRENT_SETUP:
        parts.append(str(CURRENT_SETUP))
    if CURRENT_TEST_TYPE:
        parts.append(CURRENT_TEST_TYPE)
    if parts:
        say("  " + "   ·   ".join(parts), "dim")


def format_duration(seconds):
    total = int(round(max(0, seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def script_runtime_text():
    if not SCRIPT_STARTED_AT:
        return "N/A"
    elapsed = time.time() - SCRIPT_STARTED_AT
    started = datetime.fromtimestamp(SCRIPT_STARTED_AT).strftime("%d-%b-%Y %H:%M:%S")
    finished = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    return f"{format_duration(elapsed)}  ({started} to {finished})"


def prompt(message):
    return input(paint(message, "white")).strip()


def choose(title, options, allow_quit=True):
    """options is a list of (key, label). Returns the key, or None on quit."""
    while True:
        section(title)
        for key, label in options:
            say(f"  {paint(str(key), 'cyan')}  {label}")
        if allow_quit:
            say(paint("  q  Back / cancel", "dim"))
        raw = prompt("\n  Select: ")
        if allow_quit and raw.lower() in {"q", "quit", "exit", "back"}:
            write_log(f"Menu cancelled: {title}")
            return None
        keys = {str(key): key for key, _label in options}
        if raw in keys:
            chosen = next(label for key, label in options if str(key) == raw)
            write_log(f"Menu {title}: {raw} {chosen}")
            return keys[raw]
        say("  That option is not in the list.", "yellow", log=True)


def confirm(message):
    while True:
        raw = prompt(f"\n  {message} (Y/N): ").lower()
        if raw in {"y", "yes"}:
            write_log(f"Confirmed: {message}")
            return True
        if raw in {"n", "no"}:
            write_log(f"Declined: {message}")
            return False
        say("  Enter Y or N.", "yellow")


def load_local_env():
    """Load this PC's private values. Existing environment variables win."""
    if not os.path.isfile(LOCAL_ENV_FILE):
        write_log("No wlan_runner.local.env file")
        return
    with open(LOCAL_ENV_FILE, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    write_log("Loaded wlan_runner.local.env")


def artifactory_setting(config_key, env_name):
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env
    return str(ARTIFACTORY_CONFIG.get(config_key, "")).strip()


def artifactory_credentials():
    return (
        artifactory_setting("username", "ARTIFACTORY_USERNAME"),
        artifactory_setting("password", "ARTIFACTORY_PASSWORD"),
    )


def require_artifactory_credentials():
    username, password = artifactory_credentials()
    if username and password:
        write_log("Artifactory credentials are configured")
        return True
    say("  Artifactory username or password is missing.", "red", log=True)
    say("  Add them to wlan_runner.local.env, then start again.", "yellow")
    return False


def create_project_folders():
    for folder in (REPORTS_FOLDER, LOGS_FOLDER, RESOURCES_FOLDER):
        os.makedirs(folder, exist_ok=True)
    write_log("Project folders verified")


def verify_dependencies():
    package_map = {
        "yaml": "pyyaml",
        "win32com": "pywin32",
        "ruamel": "ruamel.yaml",
        "paramiko": "paramiko",
    }
    for module, pip_name in package_map.items():
        try:
            __import__(module)
            say(f"  {pip_name} ready", "green")
        except ImportError:
            say(f"  Installing {pip_name}...", "yellow", log=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
            write_log(f"Installed {pip_name}")


def git_milestone_name(milestone):
    milestone = milestone.strip().lower()
    match = re.match(r"^m(\d+)$", milestone)
    if match:
        return f"milestone{match.group(1)}"
    if milestone.startswith("milestone"):
        return milestone
    return milestone


def git_branch_for(milestone):
    template = REPOSITORY.get("branch", "release/{milestone}")
    return template.format(milestone=git_milestone_name(milestone))


def resolve_workspace():
    configured = (WORKSPACE_ROOT or "").strip()
    if configured:
        if os.path.isdir(configured):
            write_log(f"Workspace from config: {configured}")
            return configured
        say(f"Configured workspace does not exist: {configured}", "red", log=True)

    parent = os.path.dirname(PROJECT_ROOT)
    if _milestone_candidates(parent):
        write_log(f"Workspace: {parent}")
        return parent

    if os.path.isfile(WORKSPACE_MEMORY):
        remembered = open(WORKSPACE_MEMORY, "r", encoding="utf-8").read().strip()
        if remembered and os.path.isdir(remembered):
            write_log(f"Workspace from memory: {remembered}")
            return remembered

    section("Workspace")
    say("  No milestone folders were found beside this project.")
    entered = prompt("  Folder that contains the milestone clones: ").strip().strip('"')
    if not entered or not os.path.isdir(entered):
        say("  That folder does not exist. Using the parent of this project.", "yellow", log=True)
        return parent
    with open(WORKSPACE_MEMORY, "w", encoding="utf-8") as handle:
        handle.write(entered)
    write_log(f"Workspace saved: {entered}")
    return entered


def _milestone_candidates(root):
    if not root or not os.path.isdir(root):
        return []
    excluded = {
        os.path.basename(PROJECT_ROOT),
        "Reports",
        "Logs",
        "Resources",
        "__pycache__",
    }
    found = []
    try:
        names = os.listdir(root)
    except OSError:
        return []
    for item in names:
        if item.startswith(".") or item in excluded:
            continue
        item_path = os.path.join(root, item)
        if os.path.isdir(item_path):
            found.append(item)
    return sorted(found, key=str.lower)


def get_available_milestones():
    return _milestone_candidates(WORKSPACE)


def utf_wifi_path(milestone):
    folder = REPOSITORY.get("folder", "utf_wifi")
    return os.path.join(WORKSPACE, milestone, folder)


def display_milestones(milestones):
    for index, name in enumerate(milestones, start=1):
        ready = os.path.isdir(utf_wifi_path(name))
        state = paint("utf_wifi ready", "green") if ready else paint("no utf_wifi", "yellow")
        say(f"  {paint(str(index), 'cyan')}  {name:<18} {state}")


def run_command(command, working_directory):
    say(f"  {command}", "dim", log=True)
    say(f"  cwd: {working_directory}", "dim", log=True)
    try:
        result = subprocess.run(command, cwd=working_directory, shell=True)
    except Exception as error:
        say(f"  Command error: {error}", "red", log=True)
        return False
    if result.returncode != 0:
        say(f"  Command failed ({result.returncode}): {command}", "red", log=True)
        return False
    write_log(f"SUCCESS: {command}")
    return True


def verify_repository_contents(path):
    missing = [
        item for item in REPOSITORY.get("required", [])
        if not os.path.exists(os.path.join(path, item))
    ]
    if missing:
        say("  Repository is missing: " + ", ".join(missing), "red", log=True)
        return False
    write_log(f"Repository contents verified: {path}")
    return True


def show_git_status(path):
    say("  Current clone:", "dim")
    subprocess.run("git status -sb", cwd=path, shell=True)
    write_log(f"Shown git status for {path}")


def maybe_update_clone(path):
    section("Clone Update")
    say(f"  {path}")
    if os.path.isdir(os.path.join(path, ".git")):
        show_git_status(path)
    else:
        say("  This folder is not a git clone. Skipping pull.", "yellow", log=True)
        return True
    say("  Latest changes are pulled only when you ask.")
    choice = choose(
        "Update this utf_wifi clone?",
        [
            ("1", f"Yes, run {CLONE_UPDATE_COMMAND}"),
            ("2", "No, keep this folder as it is"),
        ],
        allow_quit=False,
    )
    if choice == "2":
        say("  Continuing with the selected folder.", "green", log=True)
        return True
    say(f"  Running {CLONE_UPDATE_COMMAND}", "cyan", log=True)
    if run_command(CLONE_UPDATE_COMMAND, path):
        say("  Clone updated.", "green", log=True)
        return True
    say("  git pull did not complete.", "yellow", log=True)
    return confirm("Continue with the folder as it is anyway?")


def clone_milestone(milestone):
    milestone_path = os.path.join(WORKSPACE, milestone)
    wifi_path = utf_wifi_path(milestone)
    branch = git_branch_for(milestone)
    os.makedirs(milestone_path, exist_ok=True)
    if not os.path.isdir(wifi_path):
        section("Clone")
        say("  This can take several minutes.", "dim")
        clone_command = f"git clone --recursive {REPOSITORY['url']}"
        if not run_command(clone_command, milestone_path):
            return None
    if not os.path.isdir(wifi_path):
        say("  utf_wifi was not created by the clone.", "red", log=True)
        return None
    if not verify_repository_contents(wifi_path):
        return None
    for template in POST_CLONE_COMMANDS:
        command = template.format(branch=branch, milestone=git_milestone_name(milestone))
        if not run_command(command, wifi_path):
            return None
    say(f"  {milestone} is ready on {branch}.", "green", log=True)
    return milestone_path


def select_milestone():
    global CURRENT_MILESTONE
    milestones = get_available_milestones()
    section("Milestone")
    say(f"  Workspace: {WORKSPACE}", "dim")
    if milestones:
        display_milestones(milestones)
    else:
        say("  No milestone folders in this workspace.", "yellow")

    choice = choose(
        "Milestone source",
        [
            ("1", "Use an existing milestone"),
            ("2", "Clone a new milestone"),
        ],
    )
    if choice is None:
        return None

    if choice == "1":
        if not milestones:
            say("  There is no existing milestone to select.", "yellow", log=True)
            return None
        picked = choose(
            "Existing milestone",
            [(str(index), name) for index, name in enumerate(milestones, start=1)],
        )
        if picked is None:
            return None
        milestone = milestones[int(picked) - 1]
        CURRENT_MILESTONE = milestone
        wifi_path = utf_wifi_path(milestone)
        write_log(f"Selected milestone: {milestone}")
        write_log(f"Git branch: {git_branch_for(milestone)}")
        if os.path.isdir(wifi_path):
            if not maybe_update_clone(wifi_path):
                return None
        else:
            say("  utf_wifi is missing in that milestone.", "yellow", log=True)
            if confirm("Clone utf_wifi into it now?"):
                if clone_milestone(milestone) is None:
                    return None
            else:
                return None
        return os.path.join(WORKSPACE, milestone)

    name = prompt("  New milestone folder (example: M99): ")
    if not name:
        return None
    CURRENT_MILESTONE = name
    branch = git_branch_for(name)
    write_log(f"Selected milestone: {name}")
    write_log(f"Git branch: {branch}")
    if os.path.isdir(utf_wifi_path(name)):
        say(f"  {name} already has utf_wifi. Using that folder.", "green", log=True)
        if not maybe_update_clone(utf_wifi_path(name)):
            return None
        return os.path.join(WORKSPACE, name)
    say(f"  Branch: {branch}", "dim")
    if not confirm(f"Create and clone {name}?"):
        return None
    if clone_milestone(name) is None:
        return None
    return os.path.join(WORKSPACE, name)


def setup_validation():
    if not BUILD_CONFIG:
        say("  BUILD_CONFIG is empty. Update sanity_config.py.", "red", log=True)
        return False
    if not EXECUTION_CONFIG:
        say("  EXECUTION_CONFIG is empty. Update sanity_config.py.", "red", log=True)
        return False
    write_log("Setup validation successful")
    return True


def available_products():
    products = []
    for product, setups in PRODUCT_SETUPS.items():
        ready = [setup for setup in setups if setup in EXECUTION_CONFIG]
        if ready:
            products.append((product, ready))
    return products


def select_product_and_setup():
    products = available_products()
    if not products:
        say("  No products are configured in sanity_config.py.", "red", log=True)
        return None, None
    product_choice = choose(
        "Product",
        [(str(index), name) for index, (name, _setups) in enumerate(products, start=1)],
    )
    if product_choice is None:
        return None, None
    product, setups = products[int(product_choice) - 1]
    setup_choice = choose(
        f"{product} setup",
        [
            (
                str(index),
                f"{EXECUTION_CONFIG[setup].get('display_name', setup):<26}   "
                f"{EXECUTION_CONFIG[setup].get('target_ip', '')}"
            )
            for index, setup in enumerate(setups, start=1)
        ],
    )
    if setup_choice is None:
        return None, None
    setup = setups[int(setup_choice) - 1]
    write_log(f"Product: {product}  Setup: {setup}")
    return product, setup


def select_manifest():
    options = [(key, name) for key, name in MANIFEST_OPTIONS.items()]
    choice = choose("Manifest", options, allow_quit=False)
    return MANIFEST_OPTIONS[str(choice)]


def marker_text(key):
    if not key:
        return None
    return PYTEST_MARKERS.get(key, key)


def resolve_marker(category, plan):
    if plan.get("use_marker") is False:
        return None
    if "marker" in plan:
        key = plan.get("marker")
    else:
        key = category.get("marker") if category else None
    return marker_text(key)


def resolve_manifest(category, plan):
    if plan.get("manifest"):
        return plan["manifest"]
    if category and category.get("default_manifest"):
        return category["default_manifest"]
    return MANIFEST_OPTIONS.get("1", "manifest_917_ncp.yaml")


def build_pytest_command(path, marker=None, extra_args=None):
    parts = [PYTEST_DEFAULTS.get("base", "pytest --tb=native --count=1").strip()]
    if marker:
        parts.append(f"-m {marker}")
    if extra_args:
        parts.append(str(extra_args).strip())
    parts.append(path)
    return " ".join(part for part in parts if part)


def build_launch_command(setup, pytest_command, manifest):
    setup_config = EXECUTION_CONFIG[setup]
    target_ip = setup_config["target_ip"]
    harness = setup_config["harness"]
    manifest_name = os.path.basename(str(manifest))
    command = pytest_command.strip()
    if "--manifest" not in command:
        command = (
            f"{command} "
            f"--manifest /app/manifest/{manifest_name}"
        )
    publish = (
        "true"
        if PYTEST_DEFAULTS.get(
            "publish_test_results",
            True
        )
        else "false"
    )
    upload = (
        "True"
        if PYTEST_DEFAULTS.get(
            "upload_reports_to_artifacts",
            True
        )
        else "False"
    )
    rerun = (
        "True"
        if PYTEST_DEFAULTS.get(
            "rerun_failed_tests",
            True
        )
        else "False"
    )
    api = PYTEST_DEFAULTS.get(
        "test_results_source_api",
        "TEST_RAIL_API"
    )
    launch_command = (
        f'call .\\launch_utf_tests.bat '
        f'--target={target_ip} '
        f'--harness={harness} '
        f'--pytest_command="{command}" '
        f'--test_results_source_api={api} '
        f'--publish_test_results {publish} '
        f'--upload_reports_to_artifacts={upload} '
        f'--rerun_failed_tests={rerun}'
    )
    write_log(f"Launch Command: {launch_command}")
    return launch_command


def materialize_plan(category, plan):
    return {
        "name": plan.get("name") or os.path.basename(plan["path"]),
        "path": plan["path"],
        "marker": resolve_marker(category, plan),
        "extra_args": plan.get("extra_args") or (category or {}).get("extra_args"),
        "manifest": resolve_manifest(category, plan),
    }


def launch_command_for(setup, plan):
    pytest_command = build_pytest_command(
        plan["path"],
        plan.get("marker"),
        plan.get("extra_args"),
    )
    return build_launch_command(setup, pytest_command, plan["manifest"])


def resolve_executor():
    root = utf_wifi_path(CURRENT_MILESTONE)
    candidates = [
        os.path.join(root, "executor"),
        root,
    ]
    for path in candidates:
        if os.path.isfile(os.path.join(path, "launch_utf_tests.bat")):
            return path
    return None


def run_launch(command, executor):
    write_log(f"Launch: {command}")
    try:
        result = subprocess.run(command, cwd=executor, shell=True)
        write_log(f"Launch exit code: {result.returncode}")
        return result.returncode
    except Exception as error:
        write_log(f"Launch error: {error}")
        say(f"  Launch error: {error}", "red")
        return 1


def initialize_run():
    global CURRENT_RUN_ID
    global CURRENT_RUN_START
    global CURRENT_REPORT_SNAPSHOT
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [CURRENT_SETUP or "setup", CURRENT_TEST_TYPE or "run"]
    if CURRENT_CATEGORY:
        parts.append(CURRENT_CATEGORY)
    parts.append(timestamp)
    CURRENT_RUN_ID = "_".join(parts)
    CURRENT_RUN_START = None
    CURRENT_REPORT_SNAPSHOT = {}
    destination = os.path.join(REPORTS_FOLDER, CURRENT_RUN_ID)
    if os.path.exists(destination):
        shutil.rmtree(destination, ignore_errors=True)
    os.makedirs(destination, exist_ok=True)
    say(f"  Run ID: {CURRENT_RUN_ID}", "cyan", log=True)
    return destination


def _source_reports_root():
    if not CURRENT_MILESTONE:
        return None
    return os.path.join(utf_wifi_path(CURRENT_MILESTONE), "reports")


def snapshot_existing_reports():
    snapshot = {}
    source_root = _source_reports_root()
    if not source_root or not os.path.exists(source_root):
        return snapshot
    for root, dirs, files in os.walk(source_root):
        for file in files:
            if not file.lower().endswith(".html"):
                continue
            path = os.path.join(root, file)
            try:
                snapshot[path] = os.path.getmtime(path)
            except OSError:
                continue
    return snapshot


def mark_execution_start():
    global CURRENT_RUN_START
    global CURRENT_REPORT_SNAPSHOT
    CURRENT_RUN_START = time.time()
    CURRENT_REPORT_SNAPSHOT = snapshot_existing_reports()
    stamp = datetime.fromtimestamp(CURRENT_RUN_START).strftime("%Y-%m-%d %H:%M:%S")
    write_log(f"Execution marker: {stamp}  existing html: {len(CURRENT_REPORT_SNAPSHOT)}")
    say(f"  Execution marker: {stamp}", "dim")


def refresh_snapshot():
    global CURRENT_REPORT_SNAPSHOT
    CURRENT_REPORT_SNAPSHOT = snapshot_existing_reports()


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def is_empty_report(report_file):
    try:
        content = _read_text(report_file)
    except OSError:
        return True
    passed, failed, errors = pytest_counts(content)
    return passed == 0 and failed == 0 and errors == 0


def report_belongs_to_current_run(report_file):
    try:
        mtime = os.path.getmtime(report_file)
    except OSError:
        return False

    previous_mtime = CURRENT_REPORT_SNAPSHOT.get(report_file)
    if previous_mtime is not None:
        if mtime <= previous_mtime:
            return False
    elif CURRENT_RUN_START is not None:
        if mtime < (CURRENT_RUN_START - REPORT_MTIME_SLACK_SECONDS):
            return False

    file_name = os.path.basename(report_file).lower()
    if file_name == "pytest-report.html":
        return False
    if not file_name.endswith("pytest-report.html"):
        return False

    if CURRENT_TEST_NODE:
        test_token = CURRENT_TEST_NODE.split("::")[-1].lower()
        if test_token and test_token not in file_name:
            return False

    expected_harness = ""
    if CURRENT_SETUP in EXECUTION_CONFIG:
        expected_harness = EXECUTION_CONFIG[CURRENT_SETUP].get("harness", "").lower()
    setup_token = str(CURRENT_SETUP or "").lower()
    if expected_harness or setup_token:
        try:
            content = _read_text(report_file)
        except OSError:
            return False
        harness_match = re.search(r"harness[^\"'<>\s]+\.ya?ml", content, re.IGNORECASE)
        if harness_match:
            harness_name = harness_match.group(0).lower()
            if expected_harness and expected_harness not in harness_name:
                return False
            if setup_token and setup_token not in harness_name and f"sdk_{setup_token}" not in harness_name:
                return False
    return True


def collect_new_reports(destination):
    source_root = _source_reports_root()
    copied = []
    if not source_root or not os.path.exists(source_root):
        say(f"  Report source missing: {source_root}", "yellow", log=True)
        return copied
    os.makedirs(destination, exist_ok=True)
    for root, dirs, files in os.walk(source_root):
        for file in files:
            source_file = os.path.join(root, file)
            if not report_belongs_to_current_run(source_file):
                continue
            destination_file = os.path.join(destination, file)
            if os.path.exists(destination_file):
                name, ext = os.path.splitext(file)
                destination_file = os.path.join(
                    destination,
                    f"{name}_{int(os.path.getmtime(source_file))}{ext}",
                )
            shutil.copy2(source_file, destination_file)
            copied.append(destination_file)
            write_log(f"Report copied: {os.path.basename(destination_file)}")
    refresh_snapshot()
    say(f"  Reports archived this step: {len(copied)}", "green" if copied else "yellow", log=True)
    return copied


def report_identity(path):
    name = os.path.basename(path)
    name = _UUID_PREFIX.sub("", name)
    name = re.sub(r"-pytest-report\.html$", "", name, flags=re.IGNORECASE)
    return name.lower()


def pretty_identity(identity):
    return identity.replace("~", "/").replace("@", "::")


def plan_token(path):
    if "::" in path:
        return path.split("::")[-1].lower()
    base = os.path.basename(path.replace("\\", "/"))
    if base.endswith(".py"):
        return base.lower()
    return base.lower()


def _row_status(passed, failed, errors, exit_code=None, has_report=True):
    if not has_report:
        return "FAILED" if exit_code not in (None, 0) else "EMPTY"
    return status_from_counts(passed, failed, errors)


def aggregate_run_results(report_files):
    latest = {}
    archived = [path for path in report_files if path and os.path.isfile(path)]
    for report_file in archived:
        if is_empty_report(report_file):
            continue
        identity = report_identity(report_file)
        try:
            content = _read_text(report_file)
            mtime = os.path.getmtime(report_file)
        except OSError:
            continue
        passed, failed, errors = pytest_counts(content)
        current = {
            "identity": identity,
            "name": pretty_identity(identity),
            "path": report_file,
            "mtime": mtime,
            "passed": passed,
            "failed": failed,
            "errors": errors,
        }
        previous = latest.get(identity)
        if previous is None:
            latest[identity] = current
        else:
            latest[identity] = {
                "identity": identity,
                "name": current["name"],
                "path": current["path"],
                "mtime": current["mtime"],
                "passed": previous["passed"] + current["passed"],
                "failed": current["failed"],
                "errors": current["errors"],
            }

    rows = []
    for identity in sorted(latest):
        item = latest[identity]
        item["status"] = status_from_counts(item["passed"], item["failed"], item["errors"])
        item["duration"] = ""
        rows.append(item)

    passed = sum(item["passed"] for item in rows)
    failed = sum(item["failed"] for item in rows)
    errors = sum(item["errors"] for item in rows)
    harness = ""
    if CURRENT_SETUP in EXECUTION_CONFIG:
        harness = EXECUTION_CONFIG[CURRENT_SETUP].get("harness", "")
    return {
        "date": datetime.now().strftime("%d-%b-%Y"),
        "milestone": CURRENT_MILESTONE or "UNKNOWN",
        "firmware": BUILD_DETAILS.get("firmware", "UNKNOWN"),
        "runtime": "N/A",
        "harness": harness or "UNKNOWN",
        "setup": CURRENT_SETUP or "UNKNOWN",
        "product_type": CURRENT_PRODUCT or "UNKNOWN",
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "build": BUILD_DETAILS.get("build", "UNKNOWN"),
        "compiler": BUILD_DETAILS.get("compiler", "UNKNOWN"),
        "stack": BUILD_DETAILS.get("stack", "UNKNOWN"),
        "report_name": "",
        "status": status_from_counts(passed, failed, errors),
        "attachment_count": 1,
        "plan_rows": rows,
        "test_type": CURRENT_TEST_TYPE or "WLAN",
        "category_label": CURRENT_CATEGORY_LABEL or "",
        "archived_reports": len(archived),
        "run_id": CURRENT_RUN_ID or "",
    }


def apply_executed_plans(summary, executed):
    if not executed:
        return summary
    source_rows = summary.get("plan_rows") or []
    used = set()
    rows = []
    for item in executed:
        token = plan_token(item["path"])
        matched = [
            row for row in source_rows
            if token and token in row.get("identity", "")
        ]
        for row in matched:
            used.add(row.get("identity"))
        if matched:
            passed = sum(row["passed"] for row in matched)
            failed = sum(row["failed"] for row in matched)
            errors = sum(row["errors"] for row in matched)
            status = _row_status(passed, failed, errors, item.get("returncode"), True)
        else:
            passed = failed = errors = 0
            status = _row_status(0, 0, 0, item.get("returncode"), False)
        rows.append({
            "name": item["name"],
            "identity": token,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "status": status,
            "duration": item.get("duration", ""),
            "exit_code": item.get("returncode"),
        })
    for row in source_rows:
        if row.get("identity") not in used:
            rows.append(row)
    summary["plan_rows"] = rows
    summary["passed"] = sum(row.get("passed", 0) for row in rows)
    summary["failed"] = sum(row.get("failed", 0) for row in rows)
    summary["errors"] = sum(row.get("errors", 0) for row in rows)
    summary["total"] = summary["passed"] + summary["failed"] + summary["errors"]
    statuses = {row.get("status") for row in rows}
    if "FAILED" in statuses or ( "PASSED" in statuses and "EMPTY" in statuses):
        summary["status"] = "FAILED"
    elif statuses == {"PASSED"}:
        summary["status"] = "PASSED"
    elif summary["failed"] or summary["errors"]:
        summary["status"] = "FAILED"
    elif summary["passed"]:
        summary["status"] = "PASSED"
    else:
        summary["status"] = "EMPTY"
    return summary


def enrich_summary(summary, report_files):
    for report_file in report_files:
        if not report_file or not os.path.isfile(report_file) or is_empty_report(report_file):
            continue
        parsed = parse_report(report_file)
        for key in ("milestone", "firmware", "harness", "setup", "product_type"):
            value = parsed.get(key)
            if value and value != "UNKNOWN":
                summary[key] = value
        break
    if CURRENT_MILESTONE:
        summary["milestone"] = CURRENT_MILESTONE
    if CURRENT_SETUP:
        summary["setup"] = CURRENT_SETUP
    if CURRENT_PRODUCT:
        summary["product_type"] = CURRENT_PRODUCT
    summary["test_type"] = CURRENT_TEST_TYPE or summary.get("test_type") or "WLAN"
    summary["category_label"] = CURRENT_CATEGORY_LABEL or ""
    summary["run_id"] = CURRENT_RUN_ID or ""
    summary["runtime"] = script_runtime_text()
    if CURRENT_SETUP in EXECUTION_CONFIG:
        summary["harness"] = EXECUTION_CONFIG[CURRENT_SETUP].get("harness", summary.get("harness"))
    return summary


def _session_id_from_report(report_file):
    name = os.path.basename(report_file)
    match = re.match(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        name,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else name


def select_mail_attachments(report_files, summary=None):
    """Pass sends 1 pytest HTML. A failure sends 2."""
    del summary
    report_files = [path for path in report_files if path and os.path.isfile(path)]
    if not report_files:
        return []

    scored = []
    for report_file in report_files:
        if is_empty_report(report_file):
            continue
        try:
            content = _read_text(report_file)
            mtime = os.path.getmtime(report_file)
        except OSError:
            continue
        passed, failed, errors = pytest_counts(content)
        scored.append({
            "path": report_file,
            "mtime": mtime,
            "session": _session_id_from_report(report_file),
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "has_failure": (failed + errors) > 0,
        })

    if not scored:
        return [max(report_files, key=os.path.getmtime)]

    latest_session = max(scored, key=lambda item: item["mtime"])["session"]
    session_reports = [item for item in scored if item["session"] == latest_session]
    session_reports.sort(key=lambda item: item["mtime"], reverse=True)
    attachments = [session_reports[0]["path"]]

    if any(item["has_failure"] for item in scored):
        failed_reports = sorted(
            [item for item in scored if item["has_failure"]],
            key=lambda item: item["mtime"],
            reverse=True,
        )
        for item in failed_reports:
            if item["path"] not in attachments:
                attachments.append(item["path"])
                break
        if len(attachments) == 1 and len(session_reports) > 1:
            for item in session_reports[1:]:
                if item["path"] not in attachments:
                    attachments.append(item["path"])
                    break

    return attachments[:2]


def publish_campaign(destination, report_files, executed):
    summary = aggregate_run_results(report_files)
    regression = (CURRENT_TEST_TYPE or "").lower() == "regression"
    if regression:
        apply_executed_plans(summary, executed)
    enrich_summary(summary, report_files)
    attachments = select_mail_attachments(report_files)
    if regression:
        write_log("Mail counts: latest result of each plan")
    elif attachments:
        headline = counts_from_reports(attachments)
        summary["passed"] = headline["passed"]
        summary["failed"] = headline["failed"]
        summary["errors"] = headline["errors"]
        summary["total"] = headline["total"]
        summary["status"] = headline["status"]
        summary["plan_rows"] = []
        write_log("Mail counts: pytest summary of the attached reports")
    runtime_file = write_plain_summary(destination, summary)
    write_log(f"Runtime file: {runtime_file}")
    write_log(f"Runtime: {summary['runtime']}")
    write_log(
        f"Counts: passed={summary['passed']} failed={summary['failed']} "
        f"errors={summary['errors']} total={summary['total']}"
    )
    write_log(f"Pytest HTML files archived: {len(report_files)}")
    write_log(f"Mail attachments: {len(attachments)}")
    for attachment in attachments:
        write_log(f"Mail attachment: {attachment}")
    section("Result")
    color = "green" if summary["status"] == "PASSED" else "red"
    say(f"  Status : {summary['status']}", color, log=True)
    say(
        f"  Passed : {summary['passed']}    Failed : {summary['failed']}    Errors : {summary['errors']}",
        log=True,
    )
    say(f"  Runtime: {summary['runtime']}", "cyan", log=True)
    say(f"  Mail attachments: {len(attachments)}", "cyan", log=True)
    for attachment in attachments:
        say(f"   {os.path.basename(attachment)}", "dim")
    for row in summary.get("plan_rows") or []:
        say(
            f"  {row.get('status', ''):<8} {row.get('duration', ''):<12} {row.get('name', '')}",
            "green" if row.get("status") == "PASSED" else "yellow",
        )
    if not attachments and not regression:
        say("No pytest HTML report was found to mail.","red",log=True,)
        return summary
    try:
        if regression:
            send_latest_report(
                [],
                runtime=summary["runtime"],
                test_type=CURRENT_TEST_TYPE or "WLAN",
                headline=summary,
            )
        else:
            send_latest_report(
                attachments,
                runtime=summary["runtime"],
                test_type=CURRENT_TEST_TYPE or "WLAN",
                headline=summary,
            )
    except Exception as error:
        say(f"  Mail was not sent: {error}", "red", log=True)
        say(f"  Reports are saved in {destination}", "yellow", log=True)
    return summary


def prepare_tool(script_name, *args):
    command = [sys.executable, script_name, CURRENT_MILESTONE, WORKSPACE, CURRENT_PRODUCT, *args]
    say(f"  {script_name} {' '.join(str(arg) for arg in args)}", "dim", log=True)
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed")
    write_log(f"{script_name} completed")


def place_firmware_files(milestone):
    latest_fw = BUILD_CONFIG["rps_filename"].replace("/", "")
    old_fw = BUILD_CONFIG["http_url"].replace("/", "")
    destination = os.path.join(utf_wifi_path(milestone), "common", "www")
    os.makedirs(destination, exist_ok=True)
    resource_root = get_resource_root()
    for firmware in (os.path.join(resource_root, latest_fw), os.path.join(resource_root, old_fw)):
        if not os.path.exists(firmware):
            say(f"  Firmware missing: {os.path.basename(firmware)}", "yellow", log=True)
            continue
        shutil.copy2(firmware, os.path.join(destination, os.path.basename(firmware)))
        write_log(f"Firmware copied: {os.path.basename(firmware)}")
        say(f"  Copied {os.path.basename(firmware)}", "green")


def place_tests_folder(milestone):
    source_folder = os.path.join(get_resource_root(), "tests")
    destination_folder = os.path.join(utf_wifi_path(milestone), "utf_wiseconnect_3", "tests")
    if not os.path.exists(source_folder):
        say(f"  Tests folder missing: {source_folder}", "red", log=True)
        return
    if os.path.exists(destination_folder):
        shutil.rmtree(destination_folder)
        write_log("Removed existing tests folder")
    shutil.copytree(source_folder, destination_folder)
    write_log(f"Tests folder replaced: {destination_folder}")
    say("  Tests folder replaced", "green")


def update_settings_defaults(milestone):
    settings_file = os.path.join(utf_wifi_path(milestone), "config", "settings_defaults.env")
    if not os.path.exists(settings_file):
        say(f"  settings_defaults.env missing: {settings_file}", "red", log=True)
        return
    with open(settings_file, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    updated = []
    for line in lines:
        if line.startswith("SDK_BUILD_NUM="):
            line = f"SDK_BUILD_NUM={ARTIFACTORY_CONFIG['sdk_build_num']}\n"
        elif line.startswith("ARTIFACTORY_URL_TO_UPLOAD_REPORTS="):
            line = f"ARTIFACTORY_URL_TO_UPLOAD_REPORTS={ARTIFACTORY_CONFIG['artifactory_url']}\n"
        elif line.startswith("ARTIFACTORY_USERNAME="):
            line = f"ARTIFACTORY_USERNAME={artifactory_setting('username', 'ARTIFACTORY_USERNAME')}\n"
        elif line.startswith("ARTIFACTORY_PASSWORD="):
            line = f"ARTIFACTORY_PASSWORD={artifactory_setting('password', 'ARTIFACTORY_PASSWORD')}\n"
        updated.append(line)
    with open(settings_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(updated)
    write_log("settings_defaults.env updated")
    say("  settings_defaults.env updated", "green")


def update_test_agent_cli(milestone):
    test_agent_file = os.path.join(
        utf_wifi_path(milestone),
        "utf_wiseconnect_3",
        "tests",
        "interfaces",
        "sl_wifi_test_agent_cli.py",
    )
    if not os.path.exists(test_agent_file):
        say(f"  File missing: {test_agent_file}", "red", log=True)
        return
    with open(test_agent_file, "r", encoding="utf-8") as handle:
        content = handle.read()
    if "from socket import gethostbyname, timeout" not in content:
        content = re.sub(
            r"from socket import gethostbyname\b",
            "from socket import gethostbyname, timeout",
            content,
        )
    content = re.sub(
        r"(def\s+sntp_client_start\(.*?server_ip:\s*str\s*=\s*\")([^\"]+)(\")",
        rf"\g<1>{TEST_AGENT_CONFIG['sntp_server_ip']}\g<3>",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"(def\s+bsdSockClose\(.*?timeout:\s*int\s*=\s*)(\d+)",
        rf"\g<1>{TEST_AGENT_CONFIG['socket_close_timeout']}",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"(def\s+bsdAsyncSockClose\(.*?timeout:\s*int\s*=\s*)(\d+)",
        rf"\g<1>{TEST_AGENT_CONFIG['socket_close_timeout']}",
        content,
        flags=re.DOTALL,
    )
    with open(test_agent_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    write_log("sl_wifi_test_agent_cli.py updated")
    say("  sl_wifi_test_agent_cli.py updated", "green")


def update_utf_core_files(milestone):
    utf_core_folder = os.path.join(utf_wifi_path(milestone), "utf_core")
    launch_utf_tests = os.path.join(utf_core_folder, "src", "utf", "executor", "launch_utf_tests.py")
    if os.path.exists(launch_utf_tests):
        with open(launch_utf_tests, "r", encoding="utf-8") as handle:
            content = handle.read()
        content = re.sub(
            r'(help="Enable rerun of failed tests, needs pytest-rerunfailures plugin",\s*default=)0',
            rf"\1{UTF_CORE_CONFIG['rerun_failed_tests_default']}",
            content,
            flags=re.DOTALL,
        )
        with open(launch_utf_tests, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        write_log("launch_utf_tests.py updated")
        say("  launch_utf_tests.py updated", "green")
    else:
        say(f"  File missing: {launch_utf_tests}", "yellow", log=True)

    requirements_file = os.path.join(utf_core_folder, "wifi-requirements.txt")
    if os.path.exists(requirements_file):
        with open(requirements_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        requirement = UTF_CORE_CONFIG["pytest_rerunfailures"]
        if requirement not in content:
            if not content.endswith("\n"):
                content += "\n"
            content += requirement + "\n"
            with open(requirements_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            write_log("wifi-requirements.txt updated")
            say("  wifi-requirements.txt updated", "green")
    else:
        say(f"  File missing: {requirements_file}", "yellow", log=True)

    run_tests_file = os.path.join(utf_core_folder, "run_tests.sh")
    if os.path.exists(run_tests_file):
        with open(run_tests_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        old_function = r'''function execute_command() {
  if [ -n "$RERUN_FAILED_TESTS_COMMAND" ] && [ "$RERUN_FAILED_TESTS_COMMAND" -gt 0 ]; then
    echo "Rerun failed tests command is enabled. Rerun count: $RERUN_FAILED_TESTS_COMMAND"
    PYTEST_COMMAND="$1 --reruns $RERUN_FAILED_TESTS_COMMAND"
  else
    PYTEST_COMMAND="$1"
  fi
  eval echo "Running $PYTEST_COMMAND"
  eval "$PYTEST_COMMAND"
  pytest_exitcode=$?

  return $pytest_exitcode
}'''
        new_function = r'''function execute_command() {
  eval echo Running "$1"
  eval "$1"
  pytest_exitcode=$?
  if [ "$RERUN_FAILED_TESTS_COMMAND" ]; then
    RERUN_FAILED_TESTS="$PYTEST_COMMAND --lf --last-failed-no-failures=none"
    eval echo Running "$RERUN_FAILED_TESTS"
    eval "$RERUN_FAILED_TESTS"
    pytest_exitcode=$?
  fi
}'''
        if old_function in content:
            content = content.replace(old_function, new_function)
            with open(run_tests_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            write_log("run_tests.sh updated")
            say("  run_tests.sh updated", "green")
    else:
        say(f"  File missing: {run_tests_file}", "yellow", log=True)

def ask_pi_reboot():
    choice = choose(
        "Raspberry Pi",
        [
            ("1", "Reboot Raspberry Pi"),
            ("2", "Skip Reboot"),
        ],
        allow_quit=False
    )
    if choice == "1":
        reboot_raspberry_pi()
        say(
            "  Waiting 30 seconds for reboot...",
            "yellow",
            log=True
        )
        time.sleep(30)

def prepare_execution_environment():
    global ENV_READY_KEY
    ready_key = f"{CURRENT_MILESTONE}:{CURRENT_SETUP}"
    if ENV_READY_KEY == ready_key:
        section("Environment")
        if not confirm("Environment is already prepared for this milestone and setup. Prepare it again?"):
            say("  Reusing the prepared environment.", "green", log=True)
            return
    if not require_artifactory_credentials():
        raise RuntimeError("Artifactory credentials are missing")
    section("Environment")
    ask_pi_reboot()
    write_log(f"Environment preparation started for {CURRENT_MILESTONE} {CURRENT_SETUP}")
    prepare_tool("harness_updater.py", CURRENT_SETUP)
    say("  Harness ready", "green")
    prepare_tool("manifest_updater.py")
    say("  Manifest ready", "green")
    place_firmware_files(CURRENT_MILESTONE)
    place_tests_folder(CURRENT_MILESTONE)
    update_settings_defaults(CURRENT_MILESTONE)
    update_test_agent_cli(CURRENT_MILESTONE)
    update_utf_core_files(CURRENT_MILESTONE)
    ENV_READY_KEY = ready_key
    write_log("Environment preparation completed")
    say("  Environment ready", "green")


def parse_plan_selection(raw, count):
    raw = raw.strip().lower()
    if raw in {"all", "*"}:
        return list(range(count))
    selected = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            start_text, end_text = piece.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                if 1 <= number <= count:
                    selected.add(number - 1)
        else:
            number = int(piece)
            if 1 <= number <= count:
                selected.add(number - 1)
    return sorted(selected)


def choose_plans(category):
    plans = category.get("plans") or []
    if not plans:
        say("  This category has no plans.", "yellow", log=True)
        return []
    section(category.get("label", "Plans"))
    for index, plan in enumerate(plans, start=1):
        say(f"  {paint(f'{index:>2}', 'cyan')}  {plan['name']}")
    choice = choose(
        "How should these plans run?",
        [
            ("1", f"Run all {len(plans)} plans"),
            ("2", "Choose plans"),
        ],
    )
    if choice is None:
        return []
    if choice == "1":
        return list(plans)
    while True:
        raw = prompt("  Plan numbers (example: 1,3,5-7 or all): ")
        try:
            indexes = parse_plan_selection(raw, len(plans))
        except ValueError:
            say("  Use numbers, commas, and ranges.", "yellow")
            continue
        if not indexes:
            say("  No plans selected.", "yellow")
            continue
        chosen = [plans[index] for index in indexes]
        write_log("Selected plans: " + ", ".join(plan["name"] for plan in chosen))
        return chosen


def execute_plans(plans, single_node=None):
    global CURRENT_TEST_NODE
    destination = initialize_run()
    executor = resolve_executor()
    if executor is None:
        say("  launch_utf_tests.bat was not found in this milestone.", "red", log=True)
        publish_campaign(destination, [], [
            {
                "name": "executor",
                "path": "launch_utf_tests.bat",
                "returncode": 1,
                "duration": "0s",
            }
        ])
        return
    write_log(f"Executor: {executor}")
    say(f"  Executor: {executor}", "dim")
    mark_execution_start()
    CURRENT_TEST_NODE = single_node
    executed = []
    archived = []
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        command = launch_command_for(CURRENT_SETUP, plan)
        section(f"{plan['name']}")
        say(f"  {paint(progress_bar(index, total), 'cyan')}  {index}/{total}")
        say(f"  Manifest  {plan['manifest']}", "dim")
        marker = plan.get("marker") or "none"
        say(f"  Marker    {marker}", "dim")
        started = time.time()
        code = run_launch(command, executor)
        write_log(f"Launch Command: {command}")
        duration = format_duration(time.time() - started)
        color = "green" if code == 0 else "red"
        say(f"  Exit {code}   Plan time {duration}", color, log=True)
        plan_folder = os.path.join(destination, f"{index:02d}_{_safe_name(plan['name'])}")
        archived.extend(collect_new_reports(plan_folder))
        executed.append({
            "name": plan["name"],
            "path": plan["path"],
            "returncode": code,
            "duration": duration,
        })
        with open(os.path.join(destination, "commands.log"), "a", encoding="utf-8") as handle:
            handle.write(f"[{index}/{total}] exit={code} time={duration}\n{command}\n\n")
    CURRENT_TEST_NODE = None
    publish_campaign(destination, archived, executed)


def _safe_name(name):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_")
    return cleaned or "plan"


def connectivity_test():
    global CURRENT_SETUP, CURRENT_PRODUCT, CURRENT_TEST_TYPE, CURRENT_CATEGORY, CURRENT_CATEGORY_LABEL
    product, setup = select_product_and_setup()
    if not setup:
        return
    CURRENT_PRODUCT = product
    CURRENT_SETUP = setup
    CURRENT_TEST_TYPE = "Connectivity"
    CURRENT_CATEGORY = None
    CURRENT_CATEGORY_LABEL = ""
    section("Connectivity")
    say(f"  {product}  {setup}  {EXECUTION_CONFIG[setup]['target_ip']}")
    prepare_execution_environment()
    manifest = select_manifest()
    write_log(f"Connectivity manifest: {manifest}")
    plan = materialize_plan(None, {
        "name": "connectivity",
        "path": CONNECTIVITY_CONFIG["path"],
        "marker": CONNECTIVITY_CONFIG.get("marker"),
        "use_marker": bool(CONNECTIVITY_CONFIG.get("marker")),
        "extra_args": CONNECTIVITY_CONFIG.get("extra_args"),
        "manifest": manifest,
    })
    execute_plans([plan], single_node=CONNECTIVITY_CONFIG["path"])


def sanity_test():
    global CURRENT_SETUP, CURRENT_PRODUCT, CURRENT_TEST_TYPE, CURRENT_CATEGORY, CURRENT_CATEGORY_LABEL
    product, setup = select_product_and_setup()
    if not setup:
        return
    CURRENT_PRODUCT = product
    CURRENT_SETUP = setup
    CURRENT_TEST_TYPE = "Sanity"
    CURRENT_CATEGORY = None
    CURRENT_CATEGORY_LABEL = ""
    section("Sanity")
    say(f"  {product}  {setup}  {EXECUTION_CONFIG[setup]['target_ip']}")
    say(f"  Marker: {marker_text(SANITY_CONFIG.get('marker'))}", "dim")
    prepare_execution_environment()
    plan = materialize_plan(None, {
        "name": "sanity",
        "path": SANITY_CONFIG["path"],
        "marker": SANITY_CONFIG.get("marker"),
        "extra_args": SANITY_CONFIG.get("extra_args"),
        "manifest": SANITY_CONFIG["manifest"],
    })
    execute_plans([plan])


def regression_test():
    global CURRENT_SETUP, CURRENT_PRODUCT, CURRENT_TEST_TYPE, CURRENT_CATEGORY, CURRENT_CATEGORY_LABEL
    product, setup = select_product_and_setup()
    if not setup:
        return
    categories = REGRESSION_PLANS.get(setup) or {}
    if not categories:
        say(f"  No regression categories are configured for {setup}.", "yellow", log=True)
        return
    CURRENT_PRODUCT = product
    CURRENT_SETUP = setup
    CURRENT_TEST_TYPE = "Regression"
    ordered = list(categories.items())
    options = [
        (str(index), f"{data.get('label', key)}    {len(data.get('plans') or [])} plans")
        for index, (key, data) in enumerate(ordered, start=1)
    ]
    total_plans = sum(len(data.get("plans") or []) for _key, data in ordered)
    options.append((str(len(options) + 1), f"All categories    {total_plans} plans"))
    choice = choose(f"{setup} regression", options)
    if choice is None:
        return
    if int(choice) == len(ordered) + 1:
        selected = ordered
        category_key = "all"
        label = "All categories"
    else:
        category_key, data = ordered[int(choice) - 1]
        selected = [(category_key, data)]
        label = data.get("label", category_key)
    confirmed = []
    for key, data in selected:
        note = data.get("confirm")
        if note and not confirm(note):
            write_log(f"Skipped category: {key}")
            say(f"  Skipped {data.get('label', key)}.", "yellow")
            continue
        confirmed.append((key, data))
    selected = confirmed
    if not selected:
        say("  No regression category selected.", "yellow", log=True)
        return
    plans = []
    labels = []
    single_category = len(selected) == 1
    for key, data in selected:
        chosen = choose_plans(data) if single_category else list(data.get("plans") or [])
        if not chosen:
            say(f"  No plans selected for {data.get('label', key)}.", "yellow")
            continue
        labels.append(f"{data.get('label', key)} ({len(chosen)}/{len(data.get('plans') or [])})")
        for plan in chosen:
            materialized = materialize_plan(data, plan)
            materialized["name"] = f"{data.get('label', key)} / {plan['name']}" if len(selected) > 1 else plan["name"]
            plans.append(materialized)
    if not plans:
        say("  Nothing selected to run.", "yellow", log=True)
        return
    CURRENT_CATEGORY = category_key
    CURRENT_CATEGORY_LABEL = " + ".join(labels) if labels else label
    section("Regression")
    say(f"  {product}  {setup}")
    say(f"  {CURRENT_CATEGORY_LABEL}")
    say(f"  Plans: {len(plans)}", "cyan")
    prepare_execution_environment()
    execute_plans(plans)


def campaign_menu():
    if not setup_validation():
        return
    while True:
        clear_screen()
        banner()
        context_line()
        choice = choose(
            "Campaign",
            [
                ("1", "Connectivity     one join test"),
                ("2", "Sanity            full sanity marker"),
                ("3", "Regression        pick a category, then the plans"),
            ],
        )
        if choice is None:
            return
        if choice == "1":
            connectivity_test()
        elif choice == "2":
            sanity_test()
        elif choice == "3":
            regression_test()
        say(f"  Script runtime so far: {script_runtime_text()}", "cyan", log=True)
        again = choose(
            "Next",
            [
                ("1", "Run another campaign"),
                ("2", "Exit"),
            ],
            allow_quit=False,
        )
        if again == "2":
            return

def send_failure_mail(title, message):

    try:

        from test_mail import send_mail

        results = {
            "date": datetime.now().strftime("%d-%b-%Y"),
            "milestone": CURRENT_MILESTONE or "UNKNOWN",
            "product_type": CURRENT_PRODUCT or "UNKNOWN",
            "setup": CURRENT_SETUP or "UNKNOWN",
            "firmware": BUILD_DETAILS.get("firmware", "UNKNOWN"),
            "build": BUILD_DETAILS.get("build", "UNKNOWN"),
            "compiler": BUILD_DETAILS.get("compiler", "UNKNOWN"),
            "stack": BUILD_DETAILS.get("stack", "UNKNOWN"),
            "runtime": script_runtime_text(),
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "test_type": CURRENT_TEST_TYPE or "WLAN",
            "status": "FAILED",
            "attachment_count": 0,
            "report_name": "",
            "plan_rows": [],
            "harness": "",
        }

        html_body = f"""
        <html>
        <body style="font-family:Segoe UI;">

        <h2>{title}</h2>

        <table border="1"
            cellspacing="0"
            cellpadding="8">

            <tr>
                <td><b>Milestone</b></td>
                <td>{results['milestone']}</td>
            </tr>

            <tr>
                <td><b>Setup</b></td>
                <td>{results['setup']}</td>
            </tr>

            <tr>
                <td><b>Test Type</b></td>
                <td>{results['test_type']}</td>
            </tr>

            <tr>
                <td><b>Runtime</b></td>
                <td>{results['runtime']}</td>
            </tr>

            <tr>
                <td><b>Error</b></td>
                <td><pre>{message}</pre></td>
            </tr>

        </table>

        </body>
        </html>
        """

        send_mail([], html_body, results)

    except Exception as mail_error:

        write_log(
            f"Failure mail could not be sent: {mail_error}"
        )

def main():
    global WORKSPACE
    global SCRIPT_STARTED_AT
    enable_console()
    SCRIPT_STARTED_AT = time.time()
    banner()
    started = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    say(f"  Started {started}", "dim", log=True)
    write_log("===== WLAN Runner started =====")
    try:
        verify_dependencies()
        create_project_folders()
        load_local_env()
        WORKSPACE = resolve_workspace()
        say(f"  Workspace: {WORKSPACE}", "dim", log=True)
        if select_milestone():
            campaign_menu()
        else:
            say("  No milestone selected.", "yellow", log=True)
    except KeyboardInterrupt:
        send_failure_mail(
            "Keyboard Interrupt",
            "Execution stopped manually by user."
        )
        say(
            "\n  Stopped.",
            "yellow",
            log=True,
        )
    except Exception as error:
        import traceback
        trace = traceback.format_exc()
        write_log(trace)
        send_failure_mail(
            "Execution Error",
            trace
        )
        say(
            f"  Stopped because of an error: {error}",
            "red",
            log=True,
        )
    finally:
        runtime = script_runtime_text()
        say(f"\n  Runtime: {runtime}", "cyan")
        write_log(f"Runtime: {runtime}")
        write_log("===== WLAN Runner completed =====")


if __name__ == "__main__":
    main()
