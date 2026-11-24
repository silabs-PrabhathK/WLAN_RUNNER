"""Create the secure (signed and encrypted) SoC firmware and test agents.

Usage: python soc_secure.py <milestone> <workspace> SoC <setup>

Where things are:
  Resources\\SoC        firmware and test agents (you place them, like NCP)
  SoC_Secure          the secure script (SOC_SECURE["script"], .txt or .bat),
                      keys\\ with the .pem files, and Simplicity Commander
  Output\\<milestone>\\SoC_<setup>\\secure_files
                      the secure_*.rps files that are created

commander.exe comes from SoC_Secure\\Simplicity Commander
(SOC_SECURE["commander_folder"], or SOC_COMMANDER_FOLDER in
wlan_runner.local.env). Newer commander versions refuse to sign the firmware.

The script holds one block of "commander rps convert ..." lines per setup,
under a "REM <setup>" line. For each setup:

  firmware    : the latest and old firmware of SOC_BUILD_CONFIG, signed with
                the --mic / --encrypt / --sign values of the script's
                SiWG917 line for that setup
  test agents : every other line of the block, as written in the script

Keys are never copied, printed or logged.

Exit code 1 only when the secure latest firmware is missing at the end.
"""

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

from product_common import (
    PROJECT_ROOT,
    SOC_SECURE_ROOT,
    console_utf8,
    output_folder,
    resources_folder,
)
from sanity_config import SOC_SECURE, file_stem, firmware_names

RESOURCES_FOLDER = resources_folder("SoC")
KEYS_FOLDER = os.path.join(SOC_SECURE_ROOT, "keys")
COMMANDER_TIMEOUT = 300

REM_LINE = re.compile(r"^\s*@?REM\s+(\d+[A-Za-z])\b", re.IGNORECASE)
HEX_SECRET = re.compile(r"\b[0-9A-Fa-f]{32,}\b")

_COMMANDER = None


def commander_folder():
    """The Simplicity Commander folder, or None when it is not on this PC."""
    configured = os.environ.get("SOC_COMMANDER_FOLDER", "").strip().strip('"')
    configured = configured or str(SOC_SECURE.get("commander_folder") or "").strip()
    if not configured:
        return None
    folder = os.path.expanduser(configured)
    if not os.path.isabs(folder):
        folder = os.path.join(PROJECT_ROOT, folder)
    return folder if os.path.isdir(folder) else None


def script_path():
    """The secure script in SoC_Secure, as .txt or .bat."""
    name = os.path.basename(str(SOC_SECURE.get("script") or "").strip())
    if not name:
        return None
    stem_name = os.path.splitext(name)[0]
    for candidate in (name, stem_name + ".bat", stem_name + ".txt"):
        path = os.path.join(SOC_SECURE_ROOT, candidate)
        if os.path.isfile(path):
            return path
    return None


def find_commander():
    """Simplicity Commander, found once per process without deep folder walks."""
    global _COMMANDER
    if _COMMANDER:
        return _COMMANDER
    candidates = []
    folder = commander_folder()
    if folder:
        candidates += [os.path.join(folder, "commander.exe"), os.path.join(folder, "commander-cli.exe")]
    configured = os.environ.get("COMMANDER_PATH", "").strip().strip('"')
    if configured:
        candidates.append(configured)
    candidates += [shutil.which(name) for name in ("commander-cli", "commander")]
    installs = os.path.join(os.path.expanduser("~"), ".silabs", "slt", "installs")
    studio = r"C:\SiliconLabs\SimplicityStudio\v5\developer\adapter_packs\commander"
    candidates += [
        os.path.join(installs, "archive", "Simplicity Commander", "commander.exe"),
        os.path.join(studio, "commander.exe"),
        os.path.join(studio, "commander-cli.exe"),
    ]
    for pattern in (
        os.path.join(installs, "*", "commander*.exe"),
        os.path.join(installs, "*", "*", "commander*.exe"),
    ):
        candidates += sorted(glob.glob(pattern))
    for path in candidates:
        if path and os.path.isfile(path):
            _COMMANDER = path
            return path
    return None


def parse_script(text):
    """Return {setup: [job]} for every complete "commander rps convert" line."""
    blocks = {}
    current = None
    for line in text.splitlines():
        match = REM_LINE.match(line)
        if match:
            current = match.group(1).upper()
            continue
        if current is None or not line.strip().lower().startswith("commander rps convert"):
            continue
        try:
            tokens = shlex.split(line.strip(), posix=False)
        except ValueError:
            continue
        if len(tokens) < 4:
            continue
        job = {"out": tokens[3].strip('"')}
        index = 4
        while index + 1 < len(tokens):
            if tokens[index].startswith("--"):
                job[tokens[index][2:]] = tokens[index + 1].strip('"')
                index += 2
            else:
                index += 1
        if all(job.get(key) for key in ("app", "mic", "encrypt", "sign")):
            blocks.setdefault(current, []).append(job)
    return blocks


def build_jobs(script_jobs, secure_id):
    """Firmware jobs (latest, old) first, then the test agents of the block."""
    template = None
    agents = []
    seen = set()
    for job in script_jobs:
        if os.path.basename(job["app"]).lower().startswith("siwg917"):
            template = template or job
            continue
        if job["out"].lower() in seen:
            continue
        seen.add(job["out"].lower())
        agents.append(dict(job, kind="test agent"))
    firmware = []
    if template:
        for name, kind in zip(firmware_names("SoC"), ("latest firmware", "old firmware")):
            if name:
                firmware.append(dict(template, app=name, out=f"secure_{file_stem(name)}_{secure_id}.rps", kind=kind))
    return firmware + agents


def find_input(name):
    """Firmware or test agent in Resources\\SoC."""
    path = os.path.join(RESOURCES_FOLDER, os.path.basename(name))
    return path if os.path.isfile(path) else None


def find_key(name):
    """Signing key in SoC_Secure\\keys (or SoC_Secure itself)."""
    for folder in (KEYS_FOLDER, SOC_SECURE_ROOT):
        path = os.path.join(folder, os.path.basename(name))
        if os.path.isfile(path):
            return path
    return None


def hide_secrets(text):
    return HEX_SECRET.sub("<hidden>", text or "")


def run_commander(commander, job, app_path, out_path, sign_path):
    command = [
        commander, "rps", "convert", out_path,
        "--app", app_path,
        "--mic", job["mic"],
        "--encrypt", job["encrypt"],
        "--sign", sign_path,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=SOC_SECURE_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=COMMANDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, f"commander did not finish in {COMMANDER_TIMEOUT} seconds"
    except OSError as error:
        return None, str(error)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part and part.strip())
    return result.returncode, hide_secrets(output.strip())


def create_secure_files(milestone, setup):
    """Create the secure files of one setup in Output. Returns (ready, problems)."""
    ready = []
    problems = []
    path = script_path()
    if not path:
        problems.append(
            "Secure script not found in SoC_Secure: "
            + os.path.basename(str(SOC_SECURE.get("script") or ""))
        )
        return ready, problems
    secure_id = SOC_SECURE["setup_ids"].get(setup)
    if not secure_id:
        problems.append(f"{setup} has no id in SOC_SECURE['setup_ids'].")
        return ready, problems
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        script_jobs = parse_script(handle.read()).get(setup.upper())
    if not script_jobs:
        problems.append(f"{os.path.basename(path)} has no commands under REM {setup}.")
        return ready, problems

    jobs = build_jobs(script_jobs, secure_id)
    commander = find_commander()
    print(f"Secure script : {path}")
    print(f"Setup         : {setup} (id {secure_id}), {len(jobs)} files")
    print(f"Commander     : {commander or 'not found (set SOC_COMMANDER_FOLDER in wlan_runner.local.env)'}")
    out_folder = output_folder(milestone, "SoC", setup, "secure_files")
    print(f"Output folder : {out_folder}")
    os.makedirs(out_folder, exist_ok=True)

    for job in jobs:
        out_path = os.path.join(out_folder, job["out"])
        app_path = find_input(job["app"])
        label = f"{job['out']} ({job['kind']})"
        if not app_path:
            if os.path.isfile(out_path):
                print(f"  Existing : {label}, {job['app']} is not in Resources\\SoC")
                ready.append(job["out"])
            else:
                print(f"  Missing  : {job['app']} is not in Resources\\SoC")
                problems.append(f"{job['out']} not created: {job['app']} is missing")
            continue
        if os.path.isfile(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(app_path):
            print(f"  Current  : {label}")
            ready.append(job["out"])
            continue
        sign_path = find_key(job["sign"])
        if not sign_path:
            print(f"  No key   : {job['sign']} for {job['out']}")
            problems.append(f"{job['out']} not created: {job['sign']} is not in SoC_Secure\\keys")
            continue
        if not commander:
            problems.append(f"{job['out']} not created: Simplicity Commander was not found")
            continue
        code, output = run_commander(commander, job, app_path, out_path, sign_path)
        if code == 0 and os.path.isfile(out_path):
            print(f"  Secured  : {label}")
            ready.append(job["out"])
            continue
        print(f"  Failed   : {label}, commander exit code {code}")
        for line in (output or "no output").splitlines():
            print(f"             {line}")
        problems.append(f"{job['out']} failed (exit code {code})")
    return ready, problems


def main():
    console_utf8()
    milestone = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    product = sys.argv[3].strip() if len(sys.argv) > 3 else "SoC"
    setup = sys.argv[4].strip() if len(sys.argv) > 4 else ""
    if product != "SoC":
        print("Secure files are only needed for SoC.")
        return 0
    if not setup or not milestone:
        print("Usage: python soc_secure.py <milestone> <workspace> SoC <setup>")
        return 1

    print(f"\nSoC secure files for {setup}")
    ready, problems = create_secure_files(milestone, setup)
    if problems:
        print(f"\nProblems ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")

    secure_id = SOC_SECURE["setup_ids"].get(setup, "")
    required = f"secure_{file_stem(firmware_names('SoC')[0])}_{secure_id}.rps"
    if not os.path.isfile(os.path.join(output_folder(milestone, "SoC", setup, "secure_files"), required)):
        print(f"\nRequired file is missing: {required}")
        return 1
    print(f"\nSecure files ready: {len(ready)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
