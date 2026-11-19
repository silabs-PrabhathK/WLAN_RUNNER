# WLAN Runner

Created by: Prabhath Kattupalli
Last updated: 19-Nov-2026

WLAN Runner prepares a WLAN 917 milestone and runs Connectivity, Sanity, or Regression from one script. The same folder can be copied to another PC. Lab targets stay in `sanity_config.py`. Secrets stay in `wlan_runner.local.env` on that PC.

Connectivity and Sanity mail one pytest HTML report on a pass and two on a failure. Those mail counts are the pytest summary totals in the attached reports. Regression totals the latest result of each plan and lists every plan in the mail. It does not attach pytest HTML. Runtime is the full script time.

## Start

```text
pip install -r requirements.txt
python wlan_runner.py
```

`python wlan_runner.py --check` prints configuration errors and warnings without starting a run.

`python _verify_flow.py` is a local self-check of this script. It does not talk to a setup and it does not launch pytest.

## What you choose

1. Pick an existing milestone, or clone a new one. New folder names use letters, numbers, dots, underscores, and hyphens.
2. For an existing `utf_wifi` folder, choose whether to run `git pull`. The folder is left unchanged when you decline.
3. Pick Connectivity, Sanity, or Regression.
4. Pick the product and setup. Setups, targets, markers, and plans come from `sanity_config.py`.

Regression then offers the categories configured for that setup. You can run every plan in a category, every category, or enter plan numbers such as `1,3,5-7`. A category can ask for confirmation before it starts. Stress does that today.

## Where results go

Each run creates `Reports\<run id>\`:

- `runtime.txt` stores the script runtime
- `commands.log` stores every launch command
- numbered plan folders keep a local copy of each pytest HTML file. Regression does not attach those files to the mail.

The mail **Runtime** value is the time from script start through the end of that run. The same time is printed and written to `Logs\sanity_log.txt`.

Mail is sent through Outlook on Windows. If Outlook is not available, the run still keeps the reports and says that the mail was not sent. Stopping the script with Ctrl+C does not send a failure mail.

## Change a setup or a build

Edit `sanity_config.py` for lab data: targets, harness values, firmware names, markers, manifests, plans, and mail recipients.

`BUILD_DETAILS["firmware"]` is the firmware name shown in the mail. `BUILD_CONFIG["rps_filename"]` is the latest firmware file copied into the milestone. Keep those names the same, and put the `.rps` files in `Resources\NCP` and `Resources\SoC`.

Artifactory username and password do not belong in `sanity_config.py`. Copy `wlan_runner.local.env.example` to `wlan_runner.local.env` and fill them in. Environment variables with the same names are also accepted.

The optional Pi reboot uses the setup target unless that setup sets `pi_ip`. The login is `pi` / `raspberry` unless the setup sets `pi_user` and `pi_password`, or this PC sets `RASPI_USERNAME` and `RASPI_PASSWORD`.

Leave `WORKSPACE_ROOT` empty to use the folder next to this project. Set it when the milestone clones live somewhere else. If neither place contains milestones, WLAN Runner asks once and remembers the folder.

## Harness and manifest

Harness preparation reads the file name from `EXECUTION_CONFIG`. It starts from the previous milestone harness, then from `Resources\<product>`, and applies `HARNESS_PRECONDITIONS`. A harness name that still says `Need_to_update` is reported at startup and again when that setup is selected.

The manifest step writes the standard, without-firmware, and paho manifests, then copies `.rps`, `.hex`, and `.slcp` files from `Resources\<product>`.

## Sanity and Regression commands

Sanity launches the functional suite with the `sanity` marker from `PYTEST_MARKERS` and `manifest_917_ncp.yaml`.

Regression plans use the marker and manifest configured on each category. A plan can override either one. Open-box and common single test cases run without a marker unless that plan sets one. The without-firmware manifest is `manifest_917_ncp_without_fw.yaml`.
