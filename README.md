# WLAN Runner

WLAN Runner prepares a WLAN 917 milestone and runs Connectivity, Sanity, or Regression from one script.

Connectivity and Sanity mail one pytest HTML report on a pass and two on a failure. Those mail counts are the pytest summary totals in the attached reports. Regression totals the latest result of each plan, lists every plan in the mail, and still attaches one pytest HTML on a pass or two on a failure. Runtime is the full script time.

## Start

```text
pip install -r requirements.txt
python wlan_ncp_sanity.py
```

`python wlan_runner.py` starts the same tool.

## What you choose

1. Pick an existing milestone, or clone a new one.
2. For an existing `utf_wifi` folder, choose whether to run `git pull`. The folder is left unchanged when you decline.
3. Pick Connectivity, Sanity, or Regression.
4. Pick the product and setup. Setups, targets, markers, and plans come from `sanity_config.py`.

Regression then offers the categories configured for that setup:

- 23A: Regression (closed environment), Open box (open environment), Stress
- 23B: Regression (closed environment), Common cases (closed environment)

You can run every plan in a category or enter plan numbers such as `1,3,5-7`.

## Where results go

Each run creates `Reports\<run id>\`:

- `runtime.txt` stores the script runtime
- `commands.log` stores every launch command
- numbered plan folders keep the pytest HTML files that are mailed

The mail **Runtime** value is the time from script start through the end of that run. The same time is printed and written to `Logs\sanity_log.txt`. There is only one log file.

## Change a setup or a build

Edit `sanity_config.py` only for lab data: targets, harness values, firmware names, markers, manifests, plans, and mail recipients.

Artifactory username and password do not belong in that file. Copy `wlan_runner.local.env.example` to `wlan_runner.local.env` and fill them in. Environment variables with the same names are also accepted.

Leave `WORKSPACE_ROOT` empty to use the folder next to this project. Set it when the milestone clones live somewhere else. If neither place contains milestones, WLAN Runner asks once and remembers the folder.

## Sanity and Regression commands

Sanity launches the functional suite with marker `WLAN_Dev_sanity_917` and `manifest_917_ncp.yaml`.

Regression plans use the marker and manifest configured on each category. Firmware plans use their own marker and `manifest_917_ncp.yaml`. Open-box and common single test cases run without a marker. The without-firmware manifest is written as both `manifest_917_ncp_without_fw.yaml` and `manifest_917_ncp_without_firmware.yaml`.
