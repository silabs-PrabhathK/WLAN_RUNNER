"""
WLAN Runner

One script for WLAN connectivity, sanity, regression, and custom runs.
"""

import os
import json
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
    RERUN_REQUIREMENT,
    WORKSPACE_ROOT,
    RESOURCE_LAYOUT,
    HARNESS_PRECONDITIONS,
    EMAIL_SETTINGS,
    XRAY_SETTINGS,
    XRAY_JOB_TYPE,
    SOC_SECURE,
    build_config_for,
    build_details_for,
    default_manifest_for,
    markers_for,
    soc_manifest_names,
)
from marker_cases import MARKER_CASES
from marker_updater import apply_markers, parse_case_lists, remove_marker
from result_cases import case_ids_for_nodes, outcomes_from_reports
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
CLONED_THIS_SESSION = set()
CAMPAIGN = None  # {test node: final result info} while a campaign with auto-rerun is running
STOP_MAIL_SENT = False  # True once a stopped campaign has already mailed its partial results

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

def raspberry_pi_target():
    """Host and login for the optional Pi reboot.

    A setup may set pi_ip, pi_user, pi_password, and pi_reboot_wait.
    Otherwise the target IP is used, and this PC's wlan_runner.local.env
    can override the login with RASPI_USERNAME and RASPI_PASSWORD.
    """
    setup_config = EXECUTION_CONFIG.get(CURRENT_SETUP) or {}
    host = str(setup_config.get("pi_ip") or setup_config.get("target_ip") or "").strip()
    username = os.environ.get("RASPI_USERNAME", "").strip() or str(setup_config.get("pi_user") or "pi")
    password = os.environ.get("RASPI_PASSWORD", "").strip() or str(setup_config.get("pi_password") or "raspberry")
    try:
        wait_seconds = int(os.environ.get("RASPI_REBOOT_WAIT", setup_config.get("pi_reboot_wait", 30)))
    except (TypeError, ValueError):
        wait_seconds = 30
    if wait_seconds < 0:
        wait_seconds = 30
    return host, username, password, wait_seconds


def reboot_raspberry_pi():
    import paramiko
    host, username, password, _wait_seconds = raspberry_pi_target()
    if not host:
        say(
            f"  Raspberry Pi IP not configured for {CURRENT_SETUP}",
            "yellow",
            log=True
        )
        return False
    ssh = None
    try:
        say(
            f"  Connecting to Raspberry Pi : {host} as {username}",
            "cyan",
            log=True
        )
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )
        ssh.connect(
            hostname=host,
            username=username,
            password=password,
            timeout=20,
            banner_timeout=20,
        )
        ssh.exec_command("sudo reboot")
        say(
            f"  Reboot triggered : {host}",
            "green",
            log=True
        )
        return True
    except Exception as error:
        say(
            f"  Raspberry Pi reboot failed : {error}",
            "red",
            log=True
        )
        return False
    finally:
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass


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


AUTO_MODE = False


def confirm(message):
    if AUTO_MODE:
        write_log(f"Auto-answered No (unattended run): {message}")
        return False
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
    missing = []
    for module, pip_name in package_map.items():
        try:
            __import__(module)
            say(f"  {pip_name} ready", "green")
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return True
    say("  Installing " + ", ".join(missing), "yellow", log=True)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except subprocess.CalledProcessError as error:
        say(f"  pip install failed ({error.returncode}).", "red", log=True)
        say("  Run: pip install -r requirements.txt", "yellow")
        return False
    for pip_name in missing:
        write_log(f"Installed {pip_name}")
    return True


_MILESTONE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def valid_milestone_name(name):
    return bool(_MILESTONE_NAME.fullmatch((name or "").strip()))


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
        say("  Repository is missing: " + ", ".join(missing), "yellow", log=True)
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
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch or ""):
        say(f"  Branch name is not safe to run: {branch}", "red", log=True)
        return None
    os.makedirs(milestone_path, exist_ok=True)
    failed = []
    if os.path.isdir(wifi_path):
        say("  utf_wifi already exists in this milestone. Clone step skipped.", "yellow", log=True)
    else:
        section("Clone")
        say("  This can take several minutes.", "dim")
        if not run_command(f"git clone {REPOSITORY['url']}", milestone_path):
            failed.append("git clone")
    for template in POST_CLONE_COMMANDS:
        command = template.format(branch=branch, milestone=git_milestone_name(milestone))
        if not run_command(command, wifi_path):
            failed.append(command)
    # Warning only. Checked after the release branch and submodules are in place.
    verify_repository_contents(wifi_path)
    if failed:
        say(f"  {milestone} finished with {len(failed)} failed step(s):", "yellow", log=True)
        for command in failed:
            say(f"   {command}", "yellow", log=True)
    else:
        say(f"  {milestone} is ready on {branch}.", "green", log=True)
    stamp_cloned_markers(milestone)
    return milestone_path


def functional_tests_directory(milestone):
    relative = SANITY_CONFIG["path"].replace("/", os.sep)
    return os.path.join(utf_wifi_path(milestone), relative)


def stamp_case_markers(milestone, jobs):
    directory = functional_tests_directory(milestone)
    if not os.path.isdir(directory):
        say(f"  Test folder was not found: {directory}", "yellow", log=True)
        return []
    results = apply_markers(directory, jobs)
    if results:
        say(f"  Files updated: {results[0]['files']}", "dim", log=True)
    for result in results:
        say(
            f"  {result['label']}: {result['matched']}/{result['total']} found, "
            f"{result['added']} added, {result['already']} already present.",
            "cyan",
            log=True,
        )
        if result["missing"]:
            say("  Missing: " + ", ".join(result["missing"]), "yellow", log=True)
    return results


def stamp_cloned_markers(milestone):
    jobs = []
    for product, kinds in MARKER_CASES.items():
        for kind in ("sanity", "regression"):
            case_ids = kinds.get(kind) or []
            if case_ids:
                jobs.append((f"{product} {kind}", case_ids, marker_text(kind, product)))
    if not jobs:
        return
    section("Markers")
    say(f"  Adding NCP and SoC sanity and regression markers for {milestone}.", "cyan", log=True)
    stamp_case_markers(milestone, jobs)
    CLONED_THIS_SESSION.add(milestone)


def offer_suite_marker(kind):
    if CURRENT_MILESTONE in CLONED_THIS_SESSION:
        say(f"  The {kind} marker was added when this milestone was cloned.", "dim")
        return
    product = CURRENT_PRODUCT
    marker = marker_text(kind)
    case_ids = (MARKER_CASES.get(product) or {}).get(kind) or []
    if not case_ids:
        say(f"  No {kind} case list is configured for {product}.", "yellow", log=True)
        return
    if not confirm(f"Update the {kind} marker ({marker}) for {product}?"):
        say("  Existing markers were left as they are.", "dim")
        return
    stamp_case_markers(CURRENT_MILESTONE, [(f"{product} {kind}", case_ids, marker)])


def read_custom_case_ids():
    say("  Paste the case list. Type END on its own line when finished.", "cyan")
    say('  Example: ["C925838", "C569445"]', "dim")
    lines = []
    while True:
        line = prompt("  > ")
        if line.upper() == "END":
            break
        if line:
            lines.append(line)
    groups = parse_case_lists("\n".join(lines))
    case_ids = []
    for values in groups.values():
        case_ids.extend(values)
    unique = list(dict.fromkeys(case_ids))
    duplicates = len(case_ids) - len(unique)
    note = f"  {len(unique)} case ids"
    if duplicates:
        note += f" ({duplicates} duplicates removed)"
    say(note, "cyan")
    return unique


def new_custom_marker():
    base = marker_text("custom") or "CUSTOM_RUN"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{base}_{stamp}"


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
    if not valid_milestone_name(name):
        say("  Use letters, numbers, dots, underscores, or hyphens only.", "yellow", log=True)
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
    errors, _warnings = collect_config_findings()
    if errors:
        for item in errors:
            say(f"  {item}", "red", log=True)
        return False
    write_log("Setup validation successful")
    return True


def _config_file_name(value):
    return os.path.basename(str(value or "").replace("\\", "/").strip())


def collect_config_findings():
    """Return (errors, warnings) for the lab config on this PC."""
    errors = []
    warnings = []
    if not EXECUTION_CONFIG:
        errors.append("EXECUTION_CONFIG is empty.")
    if not BUILD_CONFIG:
        errors.append("BUILD_CONFIG is empty.")
    if not PRODUCT_SETUPS:
        errors.append("PRODUCT_SETUPS is empty.")

    known = set(EXECUTION_CONFIG)
    placeholder = []
    missing_preconditions = []
    missing_plans = []
    for product, setups in PRODUCT_SETUPS.items():
        if product not in RESOURCE_LAYOUT:
            warnings.append(f"{product} has no folder in RESOURCE_LAYOUT.")
        for setup in setups:
            if setup not in known:
                errors.append(f"{product} setup {setup} is missing from EXECUTION_CONFIG.")
                continue
            target = str(EXECUTION_CONFIG[setup].get("target_ip") or "").strip()
            harness = str(EXECUTION_CONFIG[setup].get("harness") or "").strip()
            if not target:
                errors.append(f"{setup} has no target_ip.")
            if not harness:
                errors.append(f"{setup} has no harness file name.")
            elif "need_to_update" in harness.lower():
                placeholder.append(setup)
            if setup not in HARNESS_PRECONDITIONS:
                missing_preconditions.append(setup)
            if setup not in REGRESSION_PLANS:
                missing_plans.append(setup)
    if placeholder:
        warnings.append("Harness file still needs a real name for: " + ", ".join(placeholder))
    if missing_preconditions:
        warnings.append("No HARNESS_PRECONDITIONS for: " + ", ".join(missing_preconditions))
    if missing_plans:
        warnings.append("No regression categories for: " + ", ".join(missing_plans))

    for setup, categories in REGRESSION_PLANS.items():
        if setup not in known:
            errors.append(f"REGRESSION_PLANS refers to unknown setup {setup}.")
            continue
        if not isinstance(categories, dict):
            errors.append(f"Regression plans for {setup} are not grouped by category.")
            continue
        for key, category in categories.items():
            plans = (category or {}).get("plans") or []
            if not plans:
                warnings.append(f"{setup} / {key} has no plans.")
            seen = set()
            for plan in plans:
                name = (plan or {}).get("name")
                path = (plan or {}).get("path")
                if not name or not path:
                    errors.append(f"{setup} / {key} has a plan without a name or path.")
                    continue
                if name in seen:
                    warnings.append(f"{setup} / {key} lists {name} more than once.")
                seen.add(name)

    if not str(CONNECTIVITY_CONFIG.get("path") or "").strip():
        errors.append("CONNECTIVITY_CONFIG path is empty.")
    if not str(SANITY_CONFIG.get("path") or "").strip():
        errors.append("SANITY_CONFIG path is empty.")

    for product, folder_name in RESOURCE_LAYOUT.items():
        config = build_config_for(product)
        latest = _config_file_name(config.get("rps_filename"))
        previous = _config_file_name(config.get("http_url"))
        details = _config_file_name(build_details_for(product).get("firmware"))
        if latest and details and latest != details:
            warnings.append(
                f"{product}: BUILD_DETAILS firmware is {details}, while the latest firmware is {latest}."
            )
        for firmware in (latest, previous):
            if firmware and not os.path.isfile(os.path.join(RESOURCES_FOLDER, folder_name, firmware)):
                warnings.append(f"{firmware} is missing from Resources\\{folder_name}")
    if "SoC" in RESOURCE_LAYOUT:
        import soc_secure
        if not soc_secure.script_path():
            warnings.append(f"SoC secure script was not found: {SOC_SECURE.get('script')}")
        if not soc_secure.find_commander():
            warnings.append("Simplicity Commander was not found for the SoC secure files (set COMMANDER_PATH in wlan_runner.local.env).")

    if not [item for item in EMAIL_SETTINGS.get("to", []) if str(item).strip()]:
        warnings.append("EMAIL_SETTINGS has no To recipients, so result mail cannot be sent.")
    username, password = artifactory_credentials()
    if not username or not password:
        warnings.append("Artifactory username or password is missing. Add them to wlan_runner.local.env.")
    if not os.environ.get("VAULT_TOKEN", "").strip():
        warnings.append("VAULT_TOKEN is missing. Add it to wlan_runner.local.env.")
    return errors, warnings


def note_setup_warnings(setup):
    harness = str(EXECUTION_CONFIG.get(setup, {}).get("harness") or "")
    if "need_to_update" in harness.lower():
        say(f"  {setup} harness is still a placeholder: {harness}", "yellow", log=True)
    if setup not in HARNESS_PRECONDITIONS:
        say(f"  {setup} has no harness preconditions in sanity_config.py.", "yellow", log=True)


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
    note_setup_warnings(setup)
    return product, setup


def select_manifest():
    if CURRENT_PRODUCT == "SoC" and CURRENT_SETUP in SOC_SECURE["setup_ids"]:
        names = soc_manifest_names(CURRENT_SETUP)
        options = [(str(index), name) for index, name in enumerate(names, start=1)]
        choice = choose("Manifest", options, allow_quit=False)
        return names[int(choice) - 1]
    options = [(key, name) for key, name in MANIFEST_OPTIONS.items()]
    choice = choose("Manifest", options, allow_quit=False)
    return MANIFEST_OPTIONS[str(choice)]


def marker_text(key, product=None):
    """Marker name for a key. NCP and SoC use different names."""
    if not key:
        return None
    return markers_for(product or CURRENT_PRODUCT).get(key, key)


def resolve_marker(category, plan):
    if plan.get("use_marker") is False:
        return None
    if "marker" in plan:
        key = plan.get("marker")
    else:
        key = category.get("marker") if category else None
    return marker_text(key)


def sanity_manifest():
    """Manifest for sanity, connectivity and custom runs."""
    if CURRENT_PRODUCT == "SoC":
        return default_manifest_for(CURRENT_PRODUCT, CURRENT_SETUP)
    return SANITY_CONFIG["manifest"]


def resolve_manifest(category, plan):
    if plan.get("manifest"):
        return plan["manifest"]
    if category and category.get("default_manifest"):
        return category["default_manifest"]
    return default_manifest_for(CURRENT_PRODUCT, CURRENT_SETUP)


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
        "1"
        if PYTEST_DEFAULTS.get(
            "rerun_failed_tests",
            True
        )
        else "0"
    )
    api = PYTEST_DEFAULTS.get(
        "test_results_source_api",
        "XRAY_API"
    )
    launch_command = (
        f'call .\\launch_utf_tests.bat '
        f'--target={target_ip} '
        f'--harness={harness} '
        f'--pytest_command="{command}" '
        f'--test_results_source_api {api} '
        f'--publish_test_results {publish} '
        f'--upload_reports_to_artifacts={upload} '
        f'--rerun_failed_tests {rerun}'
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
        expected_harness = os.path.basename(
            str(EXECUTION_CONFIG[CURRENT_SETUP].get("harness", ""))
        ).lower()
    setup_token = str(CURRENT_SETUP or "").lower()
    if not expected_harness and not setup_token:
        return True
    try:
        content = _read_text(report_file)
    except OSError:
        return False
    harness_match = re.search(r"harness[^\"'<>\s]+\.ya?ml", content, re.IGNORECASE)
    if not harness_match:
        return True
    found = harness_match.group(0).lower()
    if expected_harness and expected_harness in found:
        return True
    if setup_token and (setup_token in found or f"sdk_{setup_token}" in found):
        return True
    if expected_harness:
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
        if previous is None or mtime >= previous["mtime"]:
            latest[identity] = current

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
        "firmware": build_details_for(CURRENT_PRODUCT).get("firmware", "UNKNOWN"),
        "runtime": "N/A",
        "harness": harness or "UNKNOWN",
        "setup": CURRENT_SETUP or "UNKNOWN",
        "product_type": CURRENT_PRODUCT or "UNKNOWN",
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "build": build_details_for(CURRENT_PRODUCT).get("build", "UNKNOWN"),
        "compiler": build_details_for(CURRENT_PRODUCT).get("compiler", "UNKNOWN"),
        "stack": build_details_for(CURRENT_PRODUCT).get("stack", "UNKNOWN"),
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


def publish_campaign(destination, report_files, executed, send_mail=True, stopped=None):
    summary = aggregate_run_results(report_files)
    regression = (CURRENT_TEST_TYPE or "").lower() == "regression"
    if regression:
        apply_executed_plans(summary, executed)
    enrich_summary(summary, report_files)
    # Regression mail is the plan table only. Connectivity and Sanity attach HTML.
    attachments = [] if regression else select_mail_attachments(report_files)
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
    if stopped:
        apply_stop_to_summary(summary, stopped, add_rows=regression)
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
    if send_mail:
        send_result_mail(summary, attachments, destination)
    return summary, attachments


def send_result_mail(summary, attachments, destination=None):
    regression = (CURRENT_TEST_TYPE or "").lower() == "regression"
    if not attachments and not regression and not summary.get("incomplete"):
        say("No pytest HTML report was found to mail.", "red", log=True)
        return
    try:
        send_latest_report(
            attachments,
            runtime=summary["runtime"],
            test_type=CURRENT_TEST_TYPE or "WLAN",
            headline=summary,
        )
    except Exception as error:
        say(f"  Mail was not sent: {error}", "red", log=True)
        if destination:
            say(f"  Reports are saved in {destination}", "yellow", log=True)


def prepare_tool(script_name, *args):
    command = [sys.executable, script_name, CURRENT_MILESTONE, WORKSPACE, CURRENT_PRODUCT, *args]
    say(f"  {script_name} {' '.join(str(arg) for arg in args)}", "dim", log=True)
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed")
    write_log(f"{script_name} completed")


def secure_firmware_names():
    """secure_<firmware>_<id>.rps for the latest and old SoC firmware."""
    secure_id = SOC_SECURE["setup_ids"].get(CURRENT_SETUP, "")
    config = build_config_for("SoC")
    names = []
    for key in ("rps_filename", "http_url"):
        name = os.path.basename(str(config.get(key) or "").strip("/\\"))
        if name.lower().endswith(".rps"):
            name = name[:-4]
        names.append(f"secure_{name}_{secure_id}.rps")
    return names


def place_firmware_files(milestone):
    if CURRENT_PRODUCT == "SoC":
        latest_fw, old_fw = secure_firmware_names()
    else:
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


def update_settings_defaults(milestone, job_type=None):
    settings_file = os.path.join(utf_wifi_path(milestone), "config", "settings_defaults.env")
    if not os.path.exists(settings_file):
        say(f"  settings_defaults.env missing: {settings_file}", "red", log=True)
        return
    with open(settings_file, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    replacements = {
        "SDK_BUILD_NUM": ARTIFACTORY_CONFIG["sdk_build_num"],
        "ARTIFACTORY_URL_TO_UPLOAD_REPORTS": ARTIFACTORY_CONFIG["artifactory_url"],
        "ARTIFACTORY_USERNAME": artifactory_setting("username", "ARTIFACTORY_USERNAME"),
        "ARTIFACTORY_PASSWORD": artifactory_setting("password", "ARTIFACTORY_PASSWORD"),
    }
    replacements.update(XRAY_SETTINGS)
    if job_type:
        replacements["JOB_TYPE"] = job_type
    vault_token = os.environ.get("VAULT_TOKEN", "").strip().strip('"').strip("'")
    if vault_token:
        replacements["VAULT_TOKEN"] = f"'{vault_token}'"
    else:
        say("  VAULT_TOKEN is missing from wlan_runner.local.env.", "yellow", log=True)
    updated = []
    seen = set()
    for line in lines:
        replaced = False
        for key, value in replacements.items():
            if line.startswith(f"{key}="):
                updated.append(f"{key}={value}\n")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            updated.append(line if line.endswith("\n") else line + "\n")
    for key, value in replacements.items():
        if key not in seen:
            updated.append(f"{key}={value}\n")
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


def update_rerun_preconditions(milestone):
    """Apply the current rerun preconditions inside utf_wifi.

    host-requirements.txt gets pytest-rerunfailures.
    executor/docker_startup.sh reruns with --lf instead of --reruns.
    """
    wifi = utf_wifi_path(milestone)
    requirements_file = os.path.join(wifi, "host-requirements.txt")
    if os.path.isfile(requirements_file):
        with open(requirements_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        if RERUN_REQUIREMENT not in content:
            if content and not content.endswith("\n"):
                content += "\n"
            content += RERUN_REQUIREMENT + "\n"
            with open(requirements_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            write_log("host-requirements.txt updated")
            say("  host-requirements.txt updated", "green")
        else:
            say("  host-requirements.txt already has pytest-rerunfailures", "green")
    else:
        say(f"  File missing: {requirements_file}", "yellow", log=True)

    startup_file = os.path.join(wifi, "executor", "docker_startup.sh")
    if not os.path.isfile(startup_file):
        say(f"  File missing: {startup_file}", "yellow", log=True)
        return
    with open(startup_file, "r", encoding="utf-8") as handle:
        content = handle.read()
    if "execute_command()" in content and "--lf --last-failed-no-failures=none" in content:
        say("  docker_startup.sh already reruns with --lf", "green")
        return
    old_block = (
        "# Add rerun support if configured\n"
        "if [ -n \"$RERUN_FAILED_TESTS_COMMAND\" ] && [ \"$RERUN_FAILED_TESTS_COMMAND\" -gt 0 ]; then\n"
        "  echo \"Rerun failed tests enabled. Rerun count: $RERUN_FAILED_TESTS_COMMAND\"\n"
        "  PYTEST_COMMAND=\"$PYTEST_COMMAND --reruns $RERUN_FAILED_TESTS_COMMAND\"\n"
        "fi\n"
        "\n"
        "echo \"Executing: $PYTEST_COMMAND\"\n"
        "eval \"$PYTEST_COMMAND\"\n"
        "pytest_exitcode=$?\n"
    )
    new_block = (
        "execute_command() {\n"
        "    eval echo Running \"$1\"\n"
        "    eval \"$1\"\n"
        "    pytest_exitcode=$?\n"
        "\n"
        "    if [ \"$RERUN_FAILED_TESTS_COMMAND\" ] && [ \"$RERUN_FAILED_TESTS_COMMAND\" != \"0\" ] && [ \"$RERUN_FAILED_TESTS_COMMAND\" != \"False\" ]; then\n"
        "        echo \"Rerun failed tests enabled. Rerun value: $RERUN_FAILED_TESTS_COMMAND\"\n"
        "\n"
        "        RERUN_FAILED_TESTS=\"$PYTEST_COMMAND --lf --last-failed-no-failures=none\"\n"
        "\n"
        "        eval echo Running \"$RERUN_FAILED_TESTS\"\n"
        "        eval \"$RERUN_FAILED_TESTS\"\n"
        "\n"
        "        pytest_exitcode=$?\n"
        "    fi\n"
        "}\n"
        "\n"
        "execute_command \"$PYTEST_COMMAND\"\n"
    )
    if old_block not in content:
        say("  docker_startup.sh rerun block was not found, so it was left unchanged.", "yellow", log=True)
        return
    content = content.replace(old_block, new_block, 1)
    with open(startup_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    write_log("docker_startup.sh updated")
    say("  docker_startup.sh updated", "green")

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
        if reboot_raspberry_pi():
            _host, _username, _password, wait_seconds = raspberry_pi_target()
            say(
                f"  Waiting {wait_seconds} seconds for reboot...",
                "yellow",
                log=True
            )
            time.sleep(wait_seconds)

def prepare_execution_environment(unattended=False):
    """Prepare the milestone for a run.

    unattended=True is for the automatic non-pass rerun: it never asks. It
    reuses an environment that is already prepared and skips the Pi reboot menu.
    """
    global ENV_READY_KEY
    job_type = XRAY_JOB_TYPE.get(CURRENT_TEST_TYPE or "", "'ext_regression'")
    ready_key = f"{CURRENT_MILESTONE}:{CURRENT_SETUP}:{job_type}"
    if ENV_READY_KEY == ready_key:
        section("Environment")
        if unattended:
            say("  Reusing the environment prepared for the first run.", "green", log=True)
            return
        if not confirm("Environment is already prepared for this milestone and setup. Prepare it again?"):
            say("  Reusing the prepared environment.", "green", log=True)
            return
    if not require_artifactory_credentials():
        raise RuntimeError("Artifactory credentials are missing")
    section("Environment")
    if unattended:
        say("  Pi reboot menu skipped for the automatic rerun.", "dim", log=True)
    else:
        ask_pi_reboot()
    write_log(f"Environment preparation started for {CURRENT_MILESTONE} {CURRENT_SETUP}")
    if CURRENT_PRODUCT == "SoC":
        # SoC has its own scripts: the firmware and test agents are signed
        # first, then the harness and the manifests are built from them.
        prepare_tool("soc_secure.py", CURRENT_SETUP)
        say("  Secure firmware and test agents ready", "green")
        prepare_tool("soc_harness_updater.py", CURRENT_SETUP)
        say("  Harness ready", "green")
        prepare_tool("soc_manifest_updater.py", CURRENT_SETUP)
        say("  Manifest ready", "green")
    else:
        prepare_tool("harness_updater.py", CURRENT_SETUP)
        say("  Harness ready", "green")
        prepare_tool("manifest_updater.py")
        say("  Manifest ready", "green")
    place_firmware_files(CURRENT_MILESTONE)
    place_tests_folder(CURRENT_MILESTONE)
    update_settings_defaults(CURRENT_MILESTONE, job_type)
    update_test_agent_cli(CURRENT_MILESTONE)
    update_rerun_preconditions(CURRENT_MILESTONE)
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


def record_campaign(executed):
    """Store the final outcome of every test node seen in this campaign's reports."""
    for item in executed:
        for node, result in outcomes_from_reports(item.get("reports")).items():
            entry = CAMPAIGN.get(node)
            if entry is None:
                entry = {
                    "plan": item["name"],
                    "manifest": item.get("manifest") or sanity_manifest(),
                    "duration": item.get("duration", ""),
                    "returncode": item.get("returncode"),
                }
                CAMPAIGN[node] = entry
            entry["result"] = result


def rerun_nonpass_cases():
    """Rerun every non-pass case once, through a fresh custom marker."""
    directory = functional_tests_directory(CURRENT_MILESTONE)
    nonpass = [node for node, entry in CAMPAIGN.items() if entry["result"] != "passed"]
    ids_by_node = case_ids_for_nodes(nonpass, directory)
    grouped = {}
    unresolved = []
    for node in nonpass:
        case_ids = ids_by_node.get(node) or []
        if not case_ids:
            unresolved.append(node)
            continue
        bucket = grouped.setdefault(CAMPAIGN[node]["manifest"], [])
        for case_id in case_ids:
            if case_id not in bucket:
                bucket.append(case_id)
    all_ids = []
    for case_ids in grouped.values():
        for case_id in case_ids:
            if case_id not in all_ids:
                all_ids.append(case_id)
    all_ids.sort(key=lambda value: int(value[1:]))
    section("Non-pass rerun")
    say(f"  Non-pass after the first run: {len(nonpass)} of {len(CAMPAIGN)}", "yellow", log=True)
    if unresolved:
        say(f"  No case id for {len(unresolved)} result(s), not rerun:", "yellow", log=True)
        for node in unresolved:
            say(f"   {node}", "dim")
    if not all_ids:
        say("  No non-pass case ids to rerun.", "green", log=True)
        return
    listed = json.dumps(all_ids)
    say(f"  Running these cases again ({len(all_ids)}):", "cyan", log=True)
    say(f"  {listed}", "cyan", log=True)
    write_log(f"Non-pass rerun cases: {listed}")
    for manifest, case_ids in grouped.items():
        if len(grouped) > 1:
            say(f"  Manifest {manifest}: {len(case_ids)} cases", "dim", log=True)
        run_marked_cases(case_ids, manifest)


def stop_reason_text(error):
    if isinstance(error, KeyboardInterrupt):
        return "stopped by the user (Ctrl+C)"
    text = f"{type(error).__name__}: {error}".strip()
    return text if len(text) <= 300 else text[:297] + "..."


def short_list(names, limit=20):
    names = [str(name) for name in names]
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


def build_stop_info(stage, error, completed, total, incomplete, pending, extra=None):
    """Describe a campaign that stopped early, for the mail and the console."""
    lines = [f"RUN STOPPED EARLY ({stage}): {stop_reason_text(error)}."]
    if total:
        lines.append(f"Completed {completed} of {total} plan(s).")
    if incomplete:
        lines.append("Interrupted, not finished: " + short_list(incomplete))
    if pending:
        lines.append("Not run: " + short_list(pending))
    lines.extend(extra or [])
    return {
        "note": "\n".join(lines),
        "incomplete": list(incomplete),
        "pending": list(pending),
    }


def apply_stop_to_summary(summary, stopped, add_rows):
    summary["incomplete"] = True
    summary["status"] = "INCOMPLETE"
    summary["note"] = stopped["note"]
    if add_rows:
        rows = list(summary.get("plan_rows") or [])
        for names, status in (
            (stopped.get("incomplete") or [], "INCOMPLETE"),
            (stopped.get("pending") or [], "NOT RUN"),
        ):
            for name in names:
                existing = next((row for row in rows if row.get("name") == name), None)
                if existing is not None:
                    existing["status"] = status
                    continue
                rows.append({
                    "name": name,
                    "identity": name,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "status": status,
                    "duration": "",
                })
        summary["plan_rows"] = rows
    say("  " + stopped["note"].replace("\n", "\n  "), "yellow", log=True)


def finish_campaign(first_summary, attachments, destination, stopped=None):
    """Send one mail that counts every case once, using each case's final result."""
    if not CAMPAIGN:
        say("  No per-case results were read. The mail uses the first run summary.", "yellow", log=True)
        summary = dict(first_summary)
        if stopped:
            apply_stop_to_summary(summary, stopped, add_rows=False)
        send_result_mail(summary, attachments, destination)
        return
    total = len(CAMPAIGN)
    passed = sum(1 for entry in CAMPAIGN.values() if entry["result"] == "passed")
    failed = total - passed
    rows = {}
    for entry in CAMPAIGN.values():
        row = rows.setdefault(entry["plan"], {
            "name": entry["plan"],
            "identity": entry["plan"],
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "duration": entry.get("duration", ""),
            "exit_code": entry.get("returncode"),
        })
        if entry["result"] == "passed":
            row["passed"] += 1
        else:
            row["failed"] += 1
    for row in rows.values():
        row["status"] = "PASSED" if row["failed"] == 0 else "FAILED"
    summary = dict(first_summary)
    summary.update({
        "passed": passed,
        "failed": failed,
        "errors": 0,
        "total": total,
        "status": "PASSED" if failed == 0 else "FAILED",
        "plan_rows": list(rows.values()),
        "runtime": script_runtime_text(),
    })
    if stopped:
        apply_stop_to_summary(summary, stopped, add_rows=True)
    section("Campaign result")
    color = "green" if summary["status"] == "PASSED" else "red"
    say(f"  Total cases: {total}", log=True)
    say(f"  Passed     : {passed}", "green", log=True)
    say(f"  Failed     : {failed}", color, log=True)
    write_log(f"Campaign totals: total={total} passed={passed} failed={failed}")
    send_result_mail(summary, attachments, destination)


def run_marked_cases(case_ids, manifest):
    marker = new_custom_marker()
    directory = functional_tests_directory(CURRENT_MILESTONE)
    if not os.path.isdir(directory):
        say(f"  Test folder was not found: {directory}", "yellow", log=True)
        return
    say(f"  Marker: {marker}", "cyan", log=True)
    stamped = False
    try:
        stamped = True
        results = stamp_case_markers(CURRENT_MILESTONE, [("nonpass", case_ids, marker)])
        if not results or results[0]["matched"] == 0:
            say("  None of those case ids were found, so the rerun was skipped.", "yellow", log=True)
            return
        prepare_execution_environment(unattended=True)
        plan = materialize_plan(None, {
            "name": "nonpass",
            "path": SANITY_CONFIG["path"],
            "marker": marker,
            "extra_args": SANITY_CONFIG.get("extra_args"),
            "manifest": manifest,
        })
        execute_plans([plan], allow_follow_up=False)
    finally:
        if stamped:
            files_changed, removed = remove_marker(directory, marker)
            say(
                f"  Removed custom marker {marker} ({removed} lines, {files_changed} files).",
                "green",
                log=True,
            )


def execute_plans(plans, single_node=None, allow_follow_up=True):
    global AUTO_MODE
    previous = AUTO_MODE
    try:
        return _execute_plans(plans, single_node, allow_follow_up)
    finally:
        AUTO_MODE = previous


def _execute_plans(plans, single_node=None, allow_follow_up=True):
    global CURRENT_TEST_NODE, CAMPAIGN, STOP_MAIL_SENT, AUTO_MODE
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
    nested = not allow_follow_up
    follow_up = False
    if allow_follow_up:
        follow_up = confirm("Rerun non-pass cases automatically after this run?")
    if follow_up:
        CAMPAIGN = {}
    elif not nested:
        CAMPAIGN = None
    AUTO_MODE = True  # nothing may wait for input once the run has started
    write_log(f"Executor: {executor}")
    say(f"  Executor: {executor}", "dim")
    mark_execution_start()
    CURRENT_TEST_NODE = single_node
    if not nested:
        STOP_MAIL_SENT = False
    executed = []
    archived = []
    total = len(plans)
    position = 0
    plan_done = True
    stop_error = None
    try:
        for index, plan in enumerate(plans, start=1):
            position = index
            plan_done = False
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
            reports = collect_new_reports(plan_folder)
            archived.extend(reports)
            executed.append({
                "name": plan["name"],
                "path": plan["path"],
                "manifest": plan.get("manifest"),
                "returncode": code,
                "duration": duration,
                "reports": reports,
            })
            plan_done = True
            with open(os.path.join(destination, "commands.log"), "a", encoding="utf-8") as handle:
                handle.write(f"[{index}/{total}] exit={code} time={duration}\n{command}\n\n")
    except (KeyboardInterrupt, Exception) as error:
        stop_error = error
        import traceback
        write_log("Run stopped early:\n" + traceback.format_exc())
    CURRENT_TEST_NODE = None

    partial = []
    stopped = None
    if stop_error is not None:
        incomplete = [] if plan_done else [plans[position - 1]["name"]]
        pending = [item["name"] for item in plans[position:]]
        if incomplete:
            plan = plans[position - 1]
            plan_folder = os.path.join(destination, f"{position:02d}_{_safe_name(plan['name'])}")
            try:
                reports = collect_new_reports(plan_folder)
            except Exception:
                reports = []
            archived.extend(reports)
            partial.append({
                "name": plan["name"],
                "manifest": plan.get("manifest"),
                "reports": reports,
            })
        extra = ["The non-pass rerun did not start."] if follow_up else None
        stopped = build_stop_info(
            "campaign run", stop_error, len(executed), total, incomplete, pending, extra,
        )

    if CAMPAIGN is not None:
        record_campaign(executed + partial)

    if stop_error is not None and nested:
        # The campaign that started this rerun sends the one mail.
        raise stop_error

    summary, attachments = publish_campaign(
        destination, archived, executed,
        send_mail=not (follow_up or nested), stopped=stopped,
    )
    if stop_error is not None:
        try:
            if follow_up:
                finish_campaign(summary, attachments, destination, stopped=stopped)
        finally:
            CAMPAIGN = None
            STOP_MAIL_SENT = True
        raise stop_error

    if follow_up:
        rerun_stop = None
        try:
            rerun_nonpass_cases()
        except (KeyboardInterrupt, Exception) as error:
            rerun_stop = error
            import traceback
            write_log("Non-pass rerun stopped early:\n" + traceback.format_exc())
        rerun_info = None
        if rerun_stop is not None:
            still = [node for node, entry in CAMPAIGN.items() if entry["result"] != "passed"]
            rerun_info = build_stop_info(
                "non-pass rerun", rerun_stop, 0, 0, [], [],
                [f"The first run finished. Cases still non-pass: {len(still)}."]
                + ([short_list(still)] if still else []),
            )
        try:
            finish_campaign(summary, attachments, destination, stopped=rerun_info)
        finally:
            CAMPAIGN = None
            if rerun_stop is not None:
                STOP_MAIL_SENT = True
        if rerun_stop is not None:
            raise rerun_stop


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
    offer_suite_marker("sanity")
    section("Sanity")
    say(f"  {product}  {setup}  {EXECUTION_CONFIG[setup]['target_ip']}")
    say(f"  Marker: {marker_text(SANITY_CONFIG.get('marker'))}", "dim")
    prepare_execution_environment()
    plan = materialize_plan(None, {
        "name": "sanity",
        "path": SANITY_CONFIG["path"],
        "marker": SANITY_CONFIG.get("marker"),
        "extra_args": SANITY_CONFIG.get("extra_args"),
        "manifest": sanity_manifest(),
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
    offer_suite_marker("regression")
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


def custom_test():
    global CURRENT_SETUP, CURRENT_PRODUCT, CURRENT_TEST_TYPE, CURRENT_CATEGORY, CURRENT_CATEGORY_LABEL
    product, setup = select_product_and_setup()
    if not setup:
        return
    CURRENT_PRODUCT = product
    CURRENT_SETUP = setup
    CURRENT_TEST_TYPE = "Custom"
    CURRENT_CATEGORY = None
    CURRENT_CATEGORY_LABEL = ""
    case_ids = read_custom_case_ids()
    if not case_ids:
        say("  No case ids were found in the pasted text.", "yellow", log=True)
        return
    marker = new_custom_marker()
    section("Custom run")
    say(f"  {product}  {setup}  {EXECUTION_CONFIG[setup]['target_ip']}")
    say(f"  Marker: {marker}", "cyan")
    say(f"  Path: {SANITY_CONFIG['path']}", "dim")
    if not confirm("Add this marker and run these cases?"):
        return
    directory = functional_tests_directory(CURRENT_MILESTONE)
    if not os.path.isdir(directory):
        say(f"  Test folder was not found: {directory}", "yellow", log=True)
        return
    stamped = False
    try:
        stamped = True
        results = stamp_case_markers(CURRENT_MILESTONE, [("custom", case_ids, marker)])
        if not results:
            return
        result = results[0]
        if result["matched"] == 0:
            say("  None of those case ids were found, so nothing will run.", "yellow", log=True)
            return
        if result["missing"] and not confirm("Run the cases that were found?"):
            return
        prepare_execution_environment()
        plan = materialize_plan(None, {
            "name": "custom",
            "path": SANITY_CONFIG["path"],
            "marker": marker,
            "extra_args": SANITY_CONFIG.get("extra_args"),
            "manifest": sanity_manifest(),
        })
        execute_plans([plan])
    finally:
        if not stamped:
            return
        files_changed, removed = remove_marker(directory, marker)
        say(
            f"  Removed custom marker {marker} ({removed} lines, {files_changed} files).",
            "green",
            log=True,
        )


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
                ("4", "Custom run        paste case ids, then remove the marker"),
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
        elif choice == "4":
            custom_test()
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
            "firmware": build_details_for(CURRENT_PRODUCT).get("firmware", "UNKNOWN"),
            "build": build_details_for(CURRENT_PRODUCT).get("build", "UNKNOWN"),
            "compiler": build_details_for(CURRENT_PRODUCT).get("compiler", "UNKNOWN"),
            "stack": build_details_for(CURRENT_PRODUCT).get("stack", "UNKNOWN"),
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

def show_config_findings(errors, warnings):
    for item in warnings:
        say(f"  {item}", "yellow", log=True)
    for item in errors:
        say(f"  {item}", "red", log=True)


def main():
    global WORKSPACE
    global SCRIPT_STARTED_AT
    enable_console()
    SCRIPT_STARTED_AT = time.time()
    banner()
    built = time.strftime("%d-%b %H:%M", time.localtime(os.path.getmtime(__file__)))
    say(f"  Script version: {built} (fully unattended after the run starts)", "dim", log=True)
    checking = "--check" in sys.argv[1:]
    if checking:
        load_local_env()
        errors, warnings = collect_config_findings()
        show_config_findings(errors, warnings)
        if errors:
            say(f"  {len(errors)} configuration error(s).", "red")
            raise SystemExit(1)
        say("  Configuration check finished.", "green")
        return
    started = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    say(f"  Started {started}", "dim", log=True)
    write_log("===== WLAN Runner started =====")
    try:
        if not verify_dependencies():
            return
        create_project_folders()
        load_local_env()
        errors, warnings = collect_config_findings()
        show_config_findings(errors, warnings)
        if errors:
            say("  Fix sanity_config.py, then start again.", "red", log=True)
            return
        WORKSPACE = resolve_workspace()
        say(f"  Workspace: {WORKSPACE}", "dim", log=True)
        if select_milestone():
            campaign_menu()
        else:
            say("  No milestone selected.", "yellow", log=True)
    except KeyboardInterrupt:
        write_log("Stopped by user")
        say(
            "\n  Stopped.",
            "yellow",
            log=True,
        )
    except Exception as error:
        import traceback
        trace = traceback.format_exc()
        write_log(trace)
        if STOP_MAIL_SENT:
            write_log("Partial results were already mailed, so no second error mail was sent")
        else:
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
