"""Create the secure (signed and encrypted) SoC firmware and test agent files.

Usage: python soc_secure.py <milestone> <workspace> SoC <setup>

The commands come from SOC_SECURE["script"]: one block of
"commander rps convert ..." lines per setup, under a "REM <setup>" line.
Original files are read from Resources\\SoC and the secure_*.rps files are
written next to them. Keys in the script are never printed or logged.
"""

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

from sanity_config import SOC_BUILD_CONFIG, SOC_SECURE

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RESOURCES_FOLDER = os.path.join(PROJECT_ROOT, "Resources", "SoC")

REM_LINE = re.compile(r"^\s*@?REM\s+(\d+[A-Za-z])\b", re.IGNORECASE)


def script_path():
    configured = str(SOC_SECURE.get("script") or "").strip()
    local = os.path.join(RESOURCES_FOLDER, os.path.basename(configured)) if configured else ""
    for path in (local, configured):
        if path and os.path.isfile(path):
            return path
    return None


def parse_script(text):
    """Return {setup: [job]} for every "commander rps convert" line."""
    blocks = {}
    current = None
    for line in text.splitlines():
        match = REM_LINE.match(line)
        if match:
            current = match.group(1).upper()
            continue
        if not line.strip().lower().startswith("commander rps convert"):
            continue
        if current is None:
            continue
        try:
            tokens = shlex.split(line.strip())
        except ValueError:
            continue
        if len(tokens) < 4:
            continue
        job = {"out": tokens[3]}
        index = 4
        while index + 1 < len(tokens):
            option = tokens[index]
            if option.startswith("--"):
                job[option[2:]] = tokens[index + 1]
                index += 2
            else:
                index += 1
        if job.get("app") and job.get("mic") and job.get("encrypt") and job.get("sign"):
            blocks.setdefault(current, []).append(job)
    return blocks


def find_commander():
    configured = os.environ.get("COMMANDER_PATH", "").strip().strip('"')
    if configured and os.path.isfile(configured):
        return configured
    for name in ("commander-cli", "commander"):
        found = shutil.which(name)
        if found:
            return found
    home = os.path.expanduser("~")
    patterns = [
        os.path.join(home, ".silabs", "slt", "installs", "**", "commander*.exe"),
        r"C:\SiliconLabs\SimplicityStudio\v5\developer\adapter_packs\commander\commander*.exe",
        r"C:\SiliconLabs\SimplicityStudio\v5\developer\adapter_packs\commander\commander-cli*.exe",
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern, recursive=True))
        if matches:
            return matches[0]
    return None


def stem(name):
    base = os.path.basename(str(name or "").strip().strip("/\\"))
    return base[:-4] if base.lower().endswith(".rps") else base


def firmware_jobs(template, secure_id):
    """One job per firmware (latest and old), using the template's keys."""
    jobs = []
    for key in ("rps_filename", "http_url"):
        name = os.path.basename(str(SOC_BUILD_CONFIG.get(key) or "").strip("/\\"))
        if not name:
            continue
        job = dict(template)
        job["app"] = name
        job["out"] = f"secure_{stem(name)}_{secure_id}.rps"
        job["kind"] = "latest firmware" if key == "rps_filename" else "old firmware"
        jobs.append(job)
    return jobs


def build_jobs(setup, script_jobs, secure_id):
    jobs = []
    seen = set()
    template = None
    for job in script_jobs:
        if os.path.basename(job["app"]).lower().startswith("siwg917"):
            template = template or job
            continue
        if job["out"].lower() in seen:
            continue
        seen.add(job["out"].lower())
        jobs.append(dict(job, kind="test agent"))
    if template:
        jobs = firmware_jobs(template, secure_id) + jobs
    return jobs


def find_key(name):
    for folder in (RESOURCES_FOLDER, os.path.join(RESOURCES_FOLDER, "secure_firmware_keys")):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def run_commander(commander, job, sign_path):
    command = [
        commander, "rps", "convert", job["out"],
        "--app", job["app"],
        "--mic", job["mic"],
        "--encrypt", job["encrypt"],
        "--sign", sign_path,
    ]
    result = subprocess.run(
        command,
        cwd=RESOURCES_FOLDER,
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stderr or result.stdout or "").strip()


def create_secure_files(setup):
    """Create the secure files for one setup. Returns (made, problems)."""
    made = []
    problems = []
    path = script_path()
    if not path:
        problems.append(f"Secure script not found: {SOC_SECURE.get('script')}")
        return made, problems
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        blocks = parse_script(handle.read())
    secure_id = SOC_SECURE["setup_ids"].get(setup)
    if not secure_id:
        problems.append(f"{setup} has no id in SOC_SECURE['setup_ids'].")
        return made, problems
    script_jobs = blocks.get(setup.upper())
    if not script_jobs:
        problems.append(f"{os.path.basename(path)} has no commands for {setup}.")
        return made, problems
    commander = find_commander()
    jobs = build_jobs(setup, script_jobs, secure_id)
    print(f"Secure script : {os.path.basename(path)}")
    print(f"Setup         : {setup} (id {secure_id}), {len(jobs)} files")
    if not commander:
        print("Commander     : not found, only existing secure files can be used")
    else:
        print(f"Commander     : {commander}")
    for job in jobs:
        out_path = os.path.join(RESOURCES_FOLDER, job["out"])
        app_path = os.path.join(RESOURCES_FOLDER, job["app"])
        if not re.search(rf"_{re.escape(secure_id)}\.rps$", job["out"]):
            problems.append(f"{job['out']} does not end with _{secure_id}.rps")
        if not os.path.isfile(app_path):
            print(f"  Missing  : {job['app']} (not in Resources\\SoC)")
            if not os.path.isfile(out_path):
                problems.append(f"{job['app']} is missing, so {job['out']} cannot be created")
            continue
        if os.path.isfile(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(app_path):
            print(f"  Current  : {job['out']}")
            made.append(job["out"])
            continue
        sign_path = find_key(job["sign"])
        if not sign_path:
            problems.append(f"Signing key {job['sign']} is not in Resources\\SoC")
            print(f"  No key   : {job['sign']}")
            continue
        if not commander:
            problems.append(f"Commander was not found, {job['out']} was not created")
            continue
        code, message = run_commander(commander, job, sign_path)
        if code == 0 and os.path.isfile(out_path):
            print(f"  Secured  : {job['out']}")
            made.append(job["out"])
        else:
            last = message.splitlines()[-1] if message else "no output"
            problems.append(f"{job['out']} failed (code {code}): {last}")
            print(f"  Failed   : {job['out']} (code {code})")
    return made, problems


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    product = sys.argv[3].strip() if len(sys.argv) > 3 else "SoC"
    setup = sys.argv[4].strip() if len(sys.argv) > 4 else ""
    if product != "SoC":
        print("Secure files are only needed for SoC.")
        return 0
    if not setup:
        print("Usage: python soc_secure.py <milestone> <workspace> SoC <setup>")
        return 1
    print(f"\nSoC secure files for {setup}")
    made, problems = create_secure_files(setup)
    latest = os.path.basename(str(SOC_BUILD_CONFIG.get("rps_filename") or "").strip("/\\"))
    secure_id = SOC_SECURE["setup_ids"].get(setup, "")
    required = f"secure_{stem(latest)}_{secure_id}.rps"
    for problem in problems:
        print(f"  Problem  : {problem}")
    if not os.path.isfile(os.path.join(RESOURCES_FOLDER, required)):
        print(f"\nRequired file is missing: {required}")
        return 1
    print(f"\nSecure files ready: {len(made)}" + (f", {len(problems)} problem(s) above" if problems else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
