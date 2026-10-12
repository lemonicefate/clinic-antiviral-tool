# Clinic antiviral reporting tool / 流感抗病毒用藥通報工具

[English](#english) | [繁體中文](#繁體中文)

This README contains English and Traditional Chinese instructions. The English text is the controlled operational text. The Traditional Chinese text is the operator reference.

本 README 同時提供英文與繁體中文。英文內容是受控的操作文本；繁體中文內容提供給現場操作人員參考。

## English

Small LAN utility for recording publicly funded influenza antiviral use and producing the official SMIS Excel for manual upload.

This guide describes the v0.1.0 production host setup. The application host and the HIS host are separate Windows computers. Both computers use a workgroup.

### Safety rules

The following rules are mandatory.

- The client is a browser user. The client has no application login and no application password.
- The application host uses a local account named `svc_clinic_tool` by default.
- The HIS host uses an existing local read-only account. The example name is `svc_clinic_his_ro`.
- The HIS account may list and read the HIS share. It MUST NOT create, change, rename, or delete HIS files.
- The current HIS share may expose the whole HIS root. This setup accepts the current share. The checks still require the tables used by this application.
- The onboarding scripts MUST NOT change the HIS account, HIS share, or HIS ACL.
- A password MUST NOT appear in a BAT or PowerShell argument, `.env`, log, or Git file.
- Use an explicit UNC path. Do not use a mapped drive for the scheduled task.

### Host model

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

### Prerequisites

Perform these checks before onboarding.

1. Confirm the two computer names. Example: `HIS01` and `APP01`.
2. Confirm that both computers are in `WORKGROUP`.
3. Obtain a local administrator account for each computer.
4. Confirm that the HIS vendor or HIS administrator already provides a read-only account and a read-only share.
5. Install Python 3.12 on the application host. The Python launcher `py.exe` MUST be available.
6. Confirm that the application host can resolve the HIS computer name and reach SMB (TCP 445).
7. Copy this repository to a stable local path on the application host. Example: `C:\clinic-antiviral-tool`.

Do not put real patient data in this repository. Keep `.env`, SQLite data, exports, logs, and HIS files outside Git where possible.

### Phase 1: HIS host verification

Run this phase on the HIS host. Use an elevated PowerShell window. The verification script is read-only.

#### Existing account and share check

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

#### Manual-only account or share setup

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

#### Run the read-only verification

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

### Phase 2: application host onboarding

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

#### Why Task Scheduler is used

The repository starts `uvicorn` as a normal Python process. A real Windows Service is a different program type that must connect to the Windows Service Control Manager. Task Scheduler can start this normal process at Windows startup, keep a restart policy, and run it as `svc_clinic_tool`. This is the smallest setup for v0.1.0.

### Phase 3: store and verify the HIS credential

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

### Phase 4: start and smoke test

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

### Operations

#### Stop and update

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

#### Password policy

The HIS password is fixed by the current clinic policy. This onboarding does not rotate it automatically. It also does not force `PasswordNeverExpires`.

If the HIS password is changed manually, open a PowerShell window as `svc_clinic_tool`, run `store_his_credential.ps1` again, run `verify_his_access.ps1`, and restart the task.

If the application account password is changed manually, run `onboard_app_host.ps1 -SkipDependencyInstall` again with the new application password so Task Scheduler receives the new password. The script still does not change the HIS host.

#### Credential and share facts

In a workgroup, a local account on one computer does not automatically provide access to a network resource on another computer. The explicit UNC path and the per-user Windows credential store are therefore part of this setup. See the Microsoft references below.

### Troubleshooting

| Symptom | Action |
| --- | --- |
| HIS host verification fails | Stop. Ask the HIS administrator to review the account, share, NTFS rules, or required table files. |
| UNC listing fails under `svc_clinic_tool` | Recheck the exact `HIS01` target in Credential Manager. Run the store and verify scripts under the same account. |
| Required table is missing | Confirm whether the table is in the HIS root or `DATA`. Do not rename or copy production HIS files. |
| Scheduled task cannot start | Check the task history, the application account password, repository ACL, and `C:\clinic-data` ACL. |
| Browser cannot connect | Check the app host Private network profile, Windows Firewall, port 8000, and clinic LAN routing. |
| Patient data appears in Git | Stop the update. Run `python scripts\check_patient_data.py` and remove the data from Git using the repository process. |

### Official Windows references

- [Microsoft: Local User Accounts](https://learn.microsoft.com/en-us/windows/win32/ad/local-user-accounts)
- [Microsoft: Client Access to Network Resources](https://learn.microsoft.com/en-us/windows/win32/secauthz/client-access-to-network-resources)
- [Microsoft: `cmdkey`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmdkey)
- [Microsoft: `Register-ScheduledTask`](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)

### Manual smoke tests

Manual checks are limited to the real boundaries:

1. With the read-only HIS source, verify recent prescription, MRN search, and a date scan against expected HIS records.
2. Verify that the doctor page is quick and that the pharmacy table is usable for normal daily work.
3. Generate the official workbook with the real template and verify that SMIS accepts the manually uploaded file.

## 繁體中文

這是一個在診所區域網路執行的小工具。它記錄公費流感抗病毒藥品使用資料，並產生官方 SMIS Excel 檔案供人工上傳。

本指南說明 v0.1.0 的正式主機設定。應用程式主機與 HIS 主機是兩台不同的 Windows 電腦。兩台電腦都使用工作組 `WORKGROUP`。

### 安全規則

以下規則是必要規則。

- 客戶端是瀏覽器使用者。客戶端沒有應用程式登入，也沒有應用程式密碼。
- 應用程式主機預設使用名為 `svc_clinic_tool` 的本機帳號。
- HIS 主機使用既有的本機唯讀帳號。範例名稱是 `svc_clinic_his_ro`。
- HIS 帳號可以列出並讀取 HIS 分享。它不得建立、修改、重新命名或刪除 HIS 檔案。
- 目前的 HIS 分享可以分享整個 HIS 主目錄。本設定接受目前的分享方式，但檢查仍會確認本工具需要的資料表。
- Onboarding 腳本不得修改 HIS 帳號、HIS 分享或 HIS ACL。
- 密碼不得出現在 BAT 或 PowerShell 參數、`.env`、記錄檔或 Git 檔案中。
- 必須使用明確的 UNC 路徑。排程工作不得使用網路磁碟機代號。

### 主機模型

```text
+---------------------------+       SMB / UNC        +---------------------------+
| HIS 主機                  | <--------------------- | 應用程式主機              |
|                           |                        |                           |
| 既有本機帳號              |   \\HIS01\HISROOT       | svc_clinic_tool          |
| svc_clinic_his_ro         |   僅讀取及列出         | Credential Manager       |
| 既有唯讀分享              |                        | Task Scheduler + uvicorn |
+---------------------------+                        +---------------------------+
                                                              |
                                                              v
                                                診所區域網路瀏覽器客戶端
                                                /doctor 及 /pharmacy
```

`svc_clinic_his_ro` 與 `svc_clinic_tool` 是不同主機上的不同帳號。HIS 密碼會儲存在 `svc_clinic_tool` 的 Windows Credential Manager。密碼不會儲存在 `.env`。

### 前置條件

開始 onboarding 前，請完成以下確認。

1. 確認兩台電腦名稱。例如 `HIS01` 與 `APP01`。
2. 確認兩台電腦都屬於 `WORKGROUP`。
3. 為每台電腦準備本機系統管理員帳號。
4. 確認 HIS 廠商或 HIS 管理員已提供唯讀帳號及唯讀分享。
5. 在應用程式主機安裝 Python 3.12。Python 啟動器 `py.exe` 必須可用。
6. 確認應用程式主機可以解析 HIS 電腦名稱，並可連線至 SMB TCP 445 埠。
7. 將本 repository 複製到應用程式主機的固定路徑。例如 `C:\clinic-antiviral-tool`。

不要把真實病人資料放進本 repository。`.env`、SQLite 資料、匯出檔、記錄檔及 HIS 檔案應盡量放在 Git 之外。

### 第 1 階段：驗證 HIS 主機

在 HIS 主機執行本階段。請使用提升權限的 PowerShell 視窗。驗證腳本只讀取設定，不會修改 HIS。

#### 確認既有帳號及分享

以下指令只讀取設定。

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

請將 `$hisAccount` 設為既有的 HIS 唯讀帳號，將 `$hisRoot` 設為 HIS 主目錄。

帳號必須存在、已啟用，且不得屬於本機 `Administrators`。分享權限與 NTFS 權限都必須只有讀取權限。

#### 只限人工執行的帳號或分享設定

只有在 HIS 管理員與 HIS 廠商同意後，才可使用 English 區段的 `New-LocalUser`、`New-SmbShare` 及 `icacls.exe` 範例。這些指令會修改 HIS 主機，只能由人工管理員執行。自動驗證腳本不會執行這些指令。

如果 HIS 分享已經存在，不要再建立另一個分享。目前部署可以分享整個 HIS 主目錄。請保留現有唯讀身分，並先執行驗證。

#### 執行唯讀驗證

請在 HIS 主機執行以下指令。指令中的路徑與帳號請依現場設定修改：

- `-HisRootPath` 是 HIS 主機上的實際 HIS 主目錄。
- `-ShareName` 是現有的 SMB 分享名稱。
- `-ReadonlyAccount` 是現有的 HIS 唯讀帳號。

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\verify_his_host.ps1 `
  -HisRootPath 'C:\HIS' `
  -ShareName 'HISROOT' `
  -ReadonlyAccount 'svc_clinic_his_ro'
```

預期結果是所有必要資料表通過。必要資料表是 `CH012M1.DBF`、`CH011M1.DBF` 及 `PD011M1.DBF`。`H_INV.DBF` 是選用資料表。腳本會檢查根目錄及 `DATA` 目錄。

如果驗證失敗，請停止。不要使用自動修復指令。請交由 HIS 管理員檢查失敗項目。

### 第 2 階段：應用程式主機 onboarding

在應用程式主機使用提升權限的 PowerShell 視窗執行本階段。請將 `-HisPath` 改成現場的 UNC 路徑。

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ConfigureFirewall
```

此腳本只會在應用程式主機執行以下動作：

- 如果不存在，建立 `APP01\svc_clinic_tool`。
- 提示輸入應用程式帳號密碼。密碼不會放在命令列。
- 使用 Python 3.12 建立 `.venv`，並安裝 `requirements.txt`。
- 建立 `C:\clinic-data\app-data` 與 `C:\clinic-data\uploaded`。
- 設定 repository 及執行資料夾的應用程式主機權限。
- 將 `.env` 的 `HIS_MIRROR_PATH` 設為 UNC 路徑。
- 建立 Windows 啟動時執行的 `ClinicAntiviralTool` Task Scheduler 工作。
- 如果指定 `-ConfigureFirewall`，建立應用程式埠的 Private 網路設定檔入站防火牆規則。

此腳本不會在 `HIS01` 建立或修改任何設定。此階段輸入的是應用程式帳號密碼，不是 HIS 密碼。

如果離線環境已經安裝 Python 套件，請使用以下版本：

```powershell
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -SkipDependencyInstall
```

#### 為什麼使用 Task Scheduler

本 repository 是以一般 Python 程序啟動 `uvicorn`。真正的 Windows Service 是另一種程式類型，必須連接 Windows Service Control Manager。Task Scheduler 可以在 Windows 啟動時執行一般程序、設定重新啟動規則，並以 `svc_clinic_tool` 執行。這是 v0.1.0 最小的設定方式。

### 第 3 階段：儲存並驗證 HIS 憑證

HIS 憑證必須儲存在執行排程工作的同一個 Windows 帳號下。不要以系統管理員執行這些指令。

在應用程式主機先執行：

```text
runas /user:APP01\svc_clinic_tool /profile powershell.exe
```

在新的 PowerShell 視窗輸入應用程式帳號密碼，再執行：

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\store_his_credential.ps1 `
  -Target 'HIS01' `
  -RemoteUser 'HIS01\svc_clinic_his_ro'
```

`cmdkey` 會互動式要求輸入 HIS 密碼。密碼不是命令列參數。`-Target` 必須與 UNC 路徑中的主機部分相同。請使用 `HIS01`，不要使用 `\\HIS01\HISROOT`。

接著執行以下指令：

```powershell
.\scripts\verify_his_access.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ExpectedAccount 'svc_clinic_tool'
```

此檢查會列出 UNC 路徑，並以唯讀方式開啟必要 DBF 檔案。它不會寫入測試檔案。驗證通過表示排程工作的身分可以存取必要來源檔案。

如果驗證失敗，不要啟動排程工作。請檢查電腦名稱、已儲存的憑證、HIS 分享名稱及 SMB 防火牆。不要自動修改 HIS 主機。

### 第 4 階段：啟動及冒煙測試

在應用程式主機執行啟動腳本。

```text
操作人員
   |
   +--> scripts\start.bat
          |
          +--> Windows Task Scheduler
                 |
                 +--> APP01\svc_clinic_tool
                        |
                        +--> Credential Manager -> HIS01\svc_clinic_his_ro
                               |
                               +--> \\HIS01\HISROOT（唯讀）
```

啟動腳本在啟動排程工作前會檢查：

- 排程工作存在且已啟用。
- 排程工作以 `svc_clinic_tool` 執行。
- 排程工作使用本 repository 的 `.venv` Python 及 `uvicorn app.main:app`。
- 本機應用程式埠已開啟。

腳本不會要求、列印或複製密碼。Windows 會使用 onboarding 建立排程工作時儲存的密碼啟動工作。應用程式程序接著使用 `svc_clinic_tool` 的 HIS Credential Manager 憑證。

可以使用以下任一方式啟動：

```powershell
Set-Location C:\clinic-antiviral-tool
.\scripts\start_app_host.ps1 -RepoPath (Get-Location)
```

或：

```text
scripts\start.bat
```

PowerShell 是詳細啟動方式。BAT 是操作人員的快捷方式。

確認排程工作及本機埠：

```powershell
Get-ScheduledTaskInfo -TaskName 'ClinicAntiviralTool' |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
Test-NetConnection -ComputerName '127.0.0.1' -Port 8000
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/doctor'
```

再從核准的診所區域網路工作站開啟：

- `http://APP01:8000/doctor`
- `http://APP01:8000/pharmacy`

第一次臨床冒煙測試請使用唯讀 HIS mirror，或在已核准的正式環境驗證時段執行。請確認近期處方查詢、身分證號查詢、日期掃描、Excel 產生及人工 SMIS 上傳流程。

### 維運操作

#### 停止及更新

`scripts\stop.bat` 會停止排程工作及符合條件的開發程序。正式更新使用：

```text
scripts\stop.bat
scripts\update.bat
```

更新後重新啟動：

```powershell
scripts\start.bat
```

`scripts\start.bat` 是正式啟動快捷方式。它會讓排程工作以 `svc_clinic_tool` 執行，不會以目前登入桌面的使用者直接執行 `uvicorn`。

#### 密碼政策

依目前診所政策，HIS 密碼固定使用。此 onboarding 不會自動輪替密碼，也不會強制設定 `PasswordNeverExpires`。

如果 HIS 密碼由人工變更，請以 `svc_clinic_tool` 開啟 PowerShell，再次執行 `store_his_credential.ps1`、`verify_his_access.ps1`，然後重新啟動排程工作。

如果應用程式帳號密碼由人工變更，請使用新密碼再次執行 `onboard_app_host.ps1 -SkipDependencyInstall`，讓 Task Scheduler 取得新的帳號密碼。此腳本仍不會修改 HIS 主機。

#### 憑證及分享的重點

在工作組環境中，一台電腦的本機帳號不會自動提供另一台電腦網路資源的存取權。因此本設定需要明確的 UNC 路徑，以及每個使用者自己的 Windows 憑證儲存區。請參考下方 Microsoft 文件。

### 疑難排解

| 問題 | 處理方式 |
| --- | --- |
| HIS 主機驗證失敗 | 停止流程。請 HIS 管理員檢查帳號、分享、NTFS 權限或必要資料表。 |
| `svc_clinic_tool` 無法列出 UNC 路徑 | 檢查 Credential Manager 中的 `HIS01` 目標是否完全相同。以同一帳號重新執行儲存及驗證腳本。 |
| 找不到必要資料表 | 確認資料表位於 HIS 根目錄或 `DATA`。不要重新命名或複製正式 HIS 檔案。 |
| 排程工作無法啟動 | 檢查工作歷程、應用程式帳號密碼、repository ACL 及 `C:\clinic-data` ACL。 |
| 瀏覽器無法連線 | 檢查應用程式主機的 Private 網路設定檔、Windows Firewall、8000 埠及診所 LAN 路由。 |
| Git 出現病人資料 | 停止更新。執行 `python scripts\check_patient_data.py`，並依 repository 流程從 Git 移除資料。 |

### Microsoft Windows 官方參考

- [Microsoft：Local User Accounts](https://learn.microsoft.com/en-us/windows/win32/ad/local-user-accounts)
- [Microsoft：Client Access to Network Resources](https://learn.microsoft.com/en-us/windows/win32/secauthz/client-access-to-network-resources)
- [Microsoft：`cmdkey`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmdkey)
- [Microsoft：`Register-ScheduledTask`](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)

### 人工冒煙測試

人工檢查只限於實際系統邊界：

1. 使用唯讀 HIS 來源，依預期 HIS 紀錄確認近期處方、身分證號查詢及日期掃描。
2. 確認醫師頁面反應正常，且藥師表格可支援日常工作。
3. 使用正式範本產生官方工作簿，並確認 SMIS 接受人工上傳的檔案。
