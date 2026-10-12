# Clinic antiviral reporting tool

Small LAN utility for recording publicly funded influenza antiviral use and producing the official SMIS Excel for manual upload.

This guide describes the v0.1.0 production host setup. The application host and the HIS host are separate Windows computers. Both computers use a workgroup.

## Safety rules

The following rules are mandatory.

- The client is a browser user. The client has no application login and no application password.
- The application host uses a local account named `svc_clinic_tool` by default.
- The HIS host uses an existing local read-only account. The example name is `svc_clinic_his_ro`.
- The HIS account may list and read the HIS share. It MUST NOT create, change, rename, or delete HIS files.
- The current HIS share may expose the whole HIS root. This setup accepts the current share. The checks still require the tables used by this application.
- The onboarding scripts MUST NOT change the HIS account, HIS share, or HIS ACL.
- A password MUST NOT appear in a BAT or PowerShell argument, `.env`, log, or Git file.
- Use an explicit UNC path. Do not use a mapped drive for the scheduled task.

中文安全說明：自動化流程只在應用程式主機建立本機服務帳號、設定應用程式工作目錄與工作排程。HIS 主機只執行唯讀驗證。若 HIS 驗證失敗，請停止流程並交回 HIS 管理員，不要用腳本強制修復。

## Host model

```text
+---------------------------+       SMB / UNC        +---------------------------+
| HIS HOST                  | <--------------------- | APPLICATION HOST         |
|                           |                        |                           |
| existing local account   |   \\HIS01\HISROOT       | svc_clinic_tool          |
| svc_clinic_his_ro         |   read and list only   | Credential Manager       |
| existing read-only share |                        | Task Scheduler + uvicorn |
+---------------------------+                        +---------------------------+
                                                              |
                                                              v
                                                clinic LAN browser clients
                                                /doctor and /pharmacy
```

`svc_clinic_his_ro` and `svc_clinic_tool` are different accounts on different hosts. The HIS password is stored in Windows Credential Manager for `svc_clinic_tool`. It is not stored in `.env`.

## Prerequisites

Perform these checks before onboarding.

1. Confirm the two computer names. Example: `HIS01` and `APP01`.
2. Confirm that both computers are in `WORKGROUP`.
3. Obtain a local administrator account for each computer.
4. Confirm that the HIS vendor or HIS administrator already provides a read-only account and a read-only share.
5. Install Python 3.12 on the application host. The Python launcher `py.exe` MUST be available.
6. Confirm that the application host can resolve the HIS computer name and reach SMB (TCP 445).
7. Copy this repository to a stable local path on the application host. Example: `C:\clinic-antiviral-tool`.

Do not put real patient data in this repository. Keep `.env`, SQLite data, exports, logs, and HIS files outside Git where possible.

## Phase 1: HIS host verification

Run this phase on the HIS host. Use an elevated PowerShell window. The verification script is read-only.

### Existing account and share check

The following commands only read configuration.

```powershell
$hisAccount = 'svc_clinic_his_ro'
$hisRoot = 'C:\HIS'

Get-CimInstance Win32_ComputerSystem | Select-Object Name, Domain, PartOfDomain
Get-LocalUser -Name $hisAccount
Get-LocalGroupMember -Group 'Administrators'
Get-SmbShare | Where-Object Path -eq $hisRoot
Get-SmbShareAccess -Name 'HISROOT'
(Get-Acl -LiteralPath $hisRoot).Access
```

The account MUST exist, be enabled, and not be a member of local `Administrators`. The share and NTFS rules MUST provide read access only.

### Manual-only account or share setup

Use the following commands only when the HIS administrator and HIS vendor approve the change. These commands can change the HIS host. They are examples for a human administrator. The automated verification script does not run them.

```powershell
# MANUAL ONLY. Run only when the account does not already exist.
$hisAccount = 'svc_clinic_his_ro'
$hisPassword = Read-Host 'Enter the HIS read-only account password' -AsSecureString
New-LocalUser -Name $hisAccount -Password $hisPassword -Description 'Clinic tool HIS read-only access'

# MANUAL ONLY. Run only when the approved read-only share does not already exist.
New-SmbShare -Name 'HISROOT' -Path 'C:\HIS' -ReadAccess "$env:COMPUTERNAME\$hisAccount"

# MANUAL ONLY. Run only after approval. Do not remove existing HIS ACL entries.
icacls.exe 'C:\HIS' /grant ("{0}\{1}:(OI)(CI)RX" -f $env:COMPUTERNAME, $hisAccount)
```

If the HIS share already exists, do not create another share. The current deployment may share the whole HIS root. Keep the existing read-only identity and verify it.

### Run the read-only verification

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\verify_his_host.ps1 `
  -HisRootPath 'C:\HIS' `
  -ShareName 'HISROOT' `
  -ReadonlyAccount 'svc_clinic_his_ro'
```

Expected result: all required tables pass. The required tables are `CH012M1.DBF`, `CH011M1.DBF`, and `PD011M1.DBF`. `H_INV.DBF` is optional. The script checks the root and the `DATA` directory.

If this check fails, stop. Do not use an automatic repair command. Ask the HIS administrator to review the failed item.

## Phase 2: application host onboarding

Run this phase on the application host from an elevated PowerShell window.

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ConfigureFirewall
```

The script performs these application-host actions:

- create `APP01\svc_clinic_tool` if it does not exist;
- prompt for the application account password without putting it in a command line;
- create `.venv` with Python 3.12 and install `requirements.txt`;
- create `C:\clinic-data\app-data` and `C:\clinic-data\uploaded`;
- set application-host permissions for the repository and runtime directories;
- set `HIS_MIRROR_PATH` to the UNC path in `.env`;
- register the `ClinicAntiviralTool` Task Scheduler task for Windows startup;
- optionally create a Private-profile inbound firewall rule for the app port.

The script does not create or modify anything on `HIS01`. The password entered here is the application account password, not the HIS password.

If Python dependencies are already installed in an offline environment, use:

```powershell
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -SkipDependencyInstall
```

### Why Task Scheduler is used

The repository starts `uvicorn` as a normal Python process. A real Windows Service is a different program type that must connect to the Windows Service Control Manager. Task Scheduler can start this normal process at Windows startup, keep a restart policy, and run it as `svc_clinic_tool`. This is the smallest setup for v0.1.0.

## Phase 3: store and verify the HIS credential

The HIS credential must be stored under the same Windows account that runs the task. Do not run these commands as an administrator.

From the application host:

```text
runas /user:APP01\svc_clinic_tool /profile powershell.exe
```

Enter the application account password in the new PowerShell window. Then run:

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\store_his_credential.ps1 `
  -Target 'HIS01' `
  -RemoteUser 'HIS01\svc_clinic_his_ro'
```

`cmdkey` prompts for the HIS password. The password is not an argument. The target must match the host part of the UNC path. Use `HIS01`, not `\\HIS01\HISROOT`.

Now verify the real access context:

```powershell
.\scripts\verify_his_access.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ExpectedAccount 'svc_clinic_tool'
```

This check lists the UNC path and opens the required DBF files for read only. It does not write a test file. A pass means that the scheduled-task identity can reach the required source files.

If the check fails, do not start the task. Check the computer name, the stored credential, the HIS share name, and the SMB firewall. Do not change the HIS host automatically.

## Phase 4: start and smoke test

Run the start script on the application host.

```text
operator
   |
   +--> scripts\start.bat
          |
          +--> Windows Task Scheduler
                 |
                 +--> APP01\svc_clinic_tool
                        |
                        +--> Credential Manager -> HIS01\svc_clinic_his_ro
                               |
                               +--> \\HIS01\HISROOT (read only)
```

The start script performs these checks before it starts the task:

- the task exists and is enabled;
- the task runs as `svc_clinic_tool`;
- the task action is this repository's `.venv` Python and `uvicorn app.main:app`;
- the local application port opens.

The script does not ask for, print, or copy a password. Windows starts the task with the password stored when onboarding registered the task. The application process then uses the HIS credential stored for `svc_clinic_tool`.

Use either command:

```powershell
Set-Location C:\clinic-antiviral-tool
.\scripts\start_app_host.ps1 -RepoPath (Get-Location)
```

or:

```text
scripts\start.bat
```

The PowerShell launcher is the detailed path. The BAT file is the operator shortcut.

Check the task and local port:

```powershell
Get-ScheduledTaskInfo -TaskName 'ClinicAntiviralTool' |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
Test-NetConnection -ComputerName '127.0.0.1' -Port 8000
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/doctor'
```

Then open these URLs from an approved clinic-LAN workstation:

- `http://APP01:8000/doctor`
- `http://APP01:8000/pharmacy`

Use a read-only HIS mirror or approved production validation window for the first clinical smoke test. Verify recent prescription lookup, MRN search, date scan, Excel generation, and manual SMIS upload handling.

## Operations

### Stop and update

`scripts\stop.bat` stops the scheduled task and the matching development process. For a production update:

```text
scripts\stop.bat
scripts\update.bat
```

Start the task again after the update:

```powershell
scripts\start.bat
```

`scripts\start.bat` is the production startup shortcut. It starts the registered task as `svc_clinic_tool`. It does not run `uvicorn` as the currently logged-in desktop user.

### Password policy

The HIS password is fixed by the current clinic policy. This onboarding does not rotate it automatically. It also does not force `PasswordNeverExpires`.

If the HIS password is changed manually, open a PowerShell window as `svc_clinic_tool`, run `store_his_credential.ps1` again, run `verify_his_access.ps1`, and restart the task.

If the application account password is changed manually, run `onboard_app_host.ps1 -SkipDependencyInstall` again with the new application password so Task Scheduler receives the new password. The script still does not change the HIS host.

### Credential and share facts

In a workgroup, a local account on one computer does not automatically provide access to a network resource on another computer. The explicit UNC path and the per-user Windows credential store are therefore part of this setup. See the Microsoft references below.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| HIS host verification fails | Stop. Ask the HIS administrator to review the account, share, NTFS rules, or required table files. |
| UNC listing fails under `svc_clinic_tool` | Recheck the exact `HIS01` target in Credential Manager. Run the store and verify scripts under the same account. |
| Required table is missing | Confirm whether the table is in the HIS root or `DATA`. Do not rename or copy production HIS files. |
| Scheduled task cannot start | Check the task history, the application account password, repository ACL, and `C:\clinic-data` ACL. |
| Browser cannot connect | Check the app host Private network profile, Windows Firewall, port 8000, and clinic LAN routing. |
| Patient data appears in Git | Stop the update. Run `python scripts\check_patient_data.py` and remove the data from Git using the repository process. |

## Official Windows references

- [Microsoft: Local User Accounts](https://learn.microsoft.com/en-us/windows/win32/ad/local-user-accounts)
- [Microsoft: Client Access to Network Resources](https://learn.microsoft.com/en-us/windows/win32/secauthz/client-access-to-network-resources)
- [Microsoft: `cmdkey`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmdkey)
- [Microsoft: `Register-ScheduledTask`](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)

## Manual smoke tests

Manual checks are limited to the real boundaries:

1. With the read-only HIS source, verify recent prescription, MRN search, and a date scan against expected HIS records.
2. Verify that the doctor page is quick and that the pharmacy table is usable for normal daily work.
3. Generate the official workbook with the real template and verify that SMIS accepts the manually uploaded file.
