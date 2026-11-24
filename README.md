# WLAN Runner

Created by: Prabhath Kattupalli
Last updated: 24-Nov-2026

WLAN Runner prepares a WLAN 917 milestone and runs Connectivity, Sanity, Regression or a Custom run from one script, for NCP and SoC setups. The same folder can be copied to another PC. Lab targets stay in `sanity_config.py`. Secrets stay in `wlan_runner.local.env` on that PC.

## Start

```text
pip install -r requirements.txt
python wlan_runner.py
```

- `python wlan_runner.py --check` prints configuration errors and warnings without starting a run.
- `python _verify_flow.py` is a local self-check. It does not talk to a setup and it does not launch pytest.

## What you choose

1. Pick an existing milestone, or clone a new one. New folder names use letters, numbers, dots, underscores and hyphens.
2. For an existing `utf_wifi` folder, choose whether to run `git pull`. The folder is left unchanged when you decline.
3. Pick **Connectivity**, **Sanity**, **Regression** or **Custom run**.
4. Pick the product (NCP or SoC) and the setup. Setups, targets, markers and plans come from `sanity_config.py`.

Regression then offers the categories of that setup. Run every plan of a category, every category, or enter plan numbers such as `1,3,5-7`. Custom run asks for pasted case ids, stamps a temporary marker on those cases, runs them and removes the marker again.

Once a campaign starts it does not wait for input. A failing prepare step is reported and the run goes on.

**Leaving the script:** every menu has `x  Exit script`, and `x` (or `exit`) works at any prompt, including Y/N questions and the case-id paste. `q` goes back one menu where that is allowed. **Ctrl+C** stops a running command at once, ends everything it started (including the launch and its children), and a running campaign mails its partial results. You may see `Terminate batch job (Y/N)?` for up to 3 seconds, which needs no answer.

The console's QuickEdit mode is switched off while the script runs, because a click inside the window would freeze the output and block Ctrl+C. It is switched back on when the script ends.

## Resources layout

Everything a product needs is kept inside this project, so it runs on any PC. These three folders are git-ignored (keys and generated files do not belong in git), so copy them by hand to a new PC.

```text
Resources\NCP    you place: tests folder, "default" test agents, firmware .rps
Resources\SoC    you place: tests folder, mem_config_3 test agents, firmware .rps
SoC_Secure\      stays as it is (SoC signing only):
                   keys\                  ta_private_key_<id>.pem, m4_private_key_<id>.pem
                   Simplicity Commander\  version 1v15p3b2
                   the secure script      (.txt or .bat)
Output\          created by the script, take what you need from here:
                   <milestone>\<product>_<setup>\
                     manifests\     the manifests of that setup
                     harness\       the harness of that setup
                     secure_files\  secure_*.rps firmware and test agents (SoC)
```

`Resources` is never written to by the script, so it stays as clean as you left it. The firmware names that are expected come from `BUILD_CONFIG` (NCP) and `SOC_BUILD_CONFIG` (SoC) in `sanity_config.py`. `--check` and the startup warnings list what is missing.

## Preparing a setup

Before a run the script prepares the milestone in this order:

1. **SoC only: secure files** (`soc_secure.py`). The secure script in `SoC_Secure` is read. The firmware and test agents from `Resources\SoC` are signed with the keys in `SoC_Secure\keys` for the chosen setup and written to `Output\<milestone>\SoC_<setup>\secure_files` as `secure_<name>_<id>.rps`. Commander output is printed with secrets hidden. Newer Commander versions (1.25) refuse to sign the SiWG917 firmware, so the one in `SoC_Secure\Simplicity Commander` is used (override with `SOC_COMMANDER_FOLDER`).
2. **Harness** (`harness_updater.py`). The source is the previous milestone harness (M101 uses M100), else a harness you placed in `Resources\<product>`, else the newest one this script exported to `Output` for that setup. Keys that are new in the milestone default harness are added, then `HARNESS_PRECONDITIONS` are applied, and the config wins. The result is written to the milestone and copied to `Output`. `HARNESS_SKIP_KEYS` lists keys that must not be added for a setup.
3. **Manifest**
   - NCP (`manifest_updater.py`): the default manifest gets the firmware and the `default` test agents. It writes the standard, `_paho` and `_without_fw` manifests.
   - SoC (`soc_manifest_updater.py`): the default manifest gets the secure firmware and the `mem_config_3` test agents (the newest file wins when several fit, so changing names are fine). It writes `manifest_917_soc_<setup>.yaml`, `_PAHO`, `_MEM2` and `manifest_917_soc_secure_<setup>.yaml`.
4. Firmware (the secure firmware for SoC) and the tests folder are copied into the milestone, then settings, the test agent CLI and the rerun preconditions are applied.

Copies of the manifests and the harness (and the secure files for SoC) are in `Output\<milestone>\<product>_<setup>`, so they can be taken offline without opening the milestone. The script prints that folder at the end of the preparation.

## Markers

Each product has its own markers (`NCP_SANITY_RUN`, `SOC_REGRESSION_RUN`, ...). `MARKER_CASES` in `sanity_config.py` lists the case ids per marker. The runner offers to stamp them into the tests folder of a milestone that has none yet.

## Launch, rerun and results

Plans launch `launch_utf_tests.bat` with the setup target and harness, `--pytest_command="pytest ... -m <marker> <path> --manifest ..."`, and `--rerun_failed_tests 1`. After the first pass, every case that is not `passed` is run once more through a temporary custom marker, and the final result of each case is the one reported.

Each run creates `Reports\<run id>\`:

- `runtime.txt` stores the script runtime
- `commands.log` stores every launch command
- numbered plan folders keep a copy of each pytest HTML report

Connectivity and Sanity mail one pytest HTML report on a pass and two on a failure. Regression mails the totals of every plan and does not attach pytest HTML. Runtime is the full script time and is also written to `Logs\sanity_log.txt`.

Mail is sent through Outlook on Windows. If Outlook is not available the reports are kept and the script says that the mail was not sent. If a run is stopped (Ctrl+C or an error), one mail with the partial results and what did not run is sent.

## Change a setup or a build

Edit `sanity_config.py` for lab data: targets, harness values, firmware names, markers, manifests, plans and mail recipients. Keep `BUILD_DETAILS["firmware"]` and the latest firmware name the same.

Artifactory username and password and the Vault token do not belong in `sanity_config.py`. Copy `wlan_runner.local.env.example` to `wlan_runner.local.env` and fill them in. Environment variables with the same names are also accepted. That file is git-ignored.

The optional Pi reboot uses the setup target unless that setup sets `pi_ip`. The login is `pi` / `raspberry` unless the setup sets `pi_user` and `pi_password`, or this PC sets `RASPI_USERNAME` and `RASPI_PASSWORD`.

Leave `WORKSPACE_ROOT` empty to use the folder next to this project. Set it when the milestone clones live somewhere else. If neither place contains milestones, the script asks once and remembers the folder.
