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
5. Install a shared Python 3.12 runtime on the application host and note its `python.exe` path. It must include its matching standard library, `venv`, and `ensurepip`, be outside an administrator's private profile, and be accessible to `svc_clinic_tool`. Onboarding checks these runtime files before it creates the account, `.venv`, or task. Example: `C:\Program Files\Python312\python.exe`.
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
Get-LocalGroupMember -SID ([System.Security.Principal.SecurityIdentifier]'S-1-5-32-544')
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

Expected result: the required tables pass. The required tables are `CH012M1.DBF`, `CH011M1.DBF`, and `PD011M1.DBF`. `H_INV.DBF` is optional. The script checks ACL metadata for the selected share, HIS root, `DATA` directory when present, and each required table. It resolves the read-only account and local group membership by SID, requires an Allow-read entry, and rejects matching Deny or write-capable entries. If group membership or an ACL principal cannot be resolved, the result fails for HIS administrator review. This limited metadata check does not claim to prove permissions for every file in the shared root.

If this check fails, stop. Do not use an automatic repair command. Ask the HIS administrator to review the failed item.

### Phase 2: application host onboarding

Run this phase on the application host from an elevated PowerShell window.

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -PythonPath 'C:\Program Files\Python312\python.exe'
```

The script follows this order on the application host:

- before changing host state, check the selected shared Python 3.12 runtime and confirm that any existing `.venv` matches it;
- securely prompt for the application account password without placing it in a command line, then create `APP01\svc_clinic_tool` if it does not exist or reuse the existing account;
- verify that the application account can launch the shared Python runtime, create `C:\clinic-data\app-data`, `C:\clinic-data\uploaded`, and `.venv` if needed, grant repository access, and verify that account can launch the venv Python;
- install `requirements.txt` unless `-SkipDependencyInstall` is used;
- update the managed `.env` settings, including `HIS_MIRROR_PATH`, grant access to the runtime directories, and register the `ClinicAntiviralTool` Task Scheduler task for Windows startup;
- create a Private-profile inbound firewall rule for the app port only when `-ConfigureFirewall` is supplied.

The script does not create or modify anything on `HIS01`. The password entered here is the application account password, not the HIS password. An existing `.venv` is kept when its interpreter and `pyvenv.cfg` match the selected Python 3.12. If it does not match, onboarding stops with instructions to review and rebuild only `.venv`; it does not delete SQLite, exports, or logs. The shared-runtime and `.venv` account-context launch checks must pass before `.env` or the task is updated. A successful run means the application-host build completed; it does not mean the HIS credential or read-only access has been verified. The startup preflight blocks the listener unless those checks pass, and the task is started only in Phase 4.

The example leaves the firewall unchanged. If the application host's active network profile is confirmed as Private and a host firewall rule is needed, add `-ConfigureFirewall` to this command. The switch creates an inbound rule for the app port on the Private profile only; it does not provide application authentication.

If the account-context Python launch fails, the error includes the underlying cause and the numeric Win32 error code when available. To collect that diagnostic without repeating onboarding, run this probe in Windows PowerShell 5.1 from the same working directory as the failed run. Set the module path to a checkout containing this diagnostic change. Use the failing local application account and the configured shared Python path (or the venv Python path if that is the failing interpreter):

```powershell
Import-Module 'C:\clinic-antiviral-tool\scripts\ClinicAntiviral.Onboarding.psm1' -Force
$accountProbeCredential = Get-Credential -UserName "$env:COMPUTERNAME\svc_clinic_tool" -Message 'Enter the application account password for the Python probe'
try {
  Write-Host ("Probe working directory: {0}" -f (Get-Location).Path)
  Assert-ClinicPythonCanRunAsUser -PythonPath 'C:\Program Files\Python312\python.exe' -Credential $accountProbeCredential
  Write-Host 'PASS: the application account launched Python 3.12.'
}
finally {
  if ($null -ne $accountProbeCredential) { $accountProbeCredential.Password.Dispose() }
  Remove-Variable accountProbeCredential -ErrorAction SilentlyContinue
}
```

This only probes Python startup and version; it does not create accounts, rebuild `.venv`, change tasks or credentials, or access HIS. A passing probe does not verify dependency imports or the full onboarding flow. Share the error text and code with sensitive values redacted; never share the password.

The onboarding task has an AtStartup trigger, an unlimited execution time, and a three-restart failure policy. Its Python action runs `app.startup`, which checks the task account SID, confirms that account has a domain-password credential for the exact UNC host in Credential Manager, and opens the required HIS DBF files read-only before it starts uvicorn. Until the credential is present and those files can be read, the task exits without opening the application listener.

To repeat setup or update the port/path settings, run the same command with the selected shared Python path. Existing comments, unrelated settings, and an existing `SMIS_TEMPLATE_PATH` are retained; each managed key is updated once. If the script detects joined or invalid UTF-8 settings, stop and recreate `.env` from confirmed values rather than trying to split or repair the old value.

If Python dependencies are already installed in an offline environment, use:

```powershell
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -PythonPath 'C:\Program Files\Python312\python.exe' `
  -SkipDependencyInstall
```

#### Why Task Scheduler is used

The repository starts `uvicorn` as a normal Python process. A real Windows Service is a different program type that must connect to the Windows Service Control Manager. Task Scheduler runs the checked startup entry point as `svc_clinic_tool` at Windows startup. The entry point validates the task identity and read-only access to the required HIS tables before starting uvicorn. This is the smallest setup for v0.1.0.

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
  -RemoteUser 'HIS01\svc_clinic_his_ro' `
  -ExpectedAccount 'APP01\svc_clinic_tool'
```

The script checks the current Windows account SID against the local `APP01\svc_clinic_tool` SID before displaying its secure password prompt. It stores a domain-password credential with local-machine persistence in that account's Credential Manager. The target must be exactly the host part of the UNC path, without the share. If the UNC uses an IP address, use that IP for `-Target` and keep the real HIS computer prefix in `-RemoteUser`, for example `-Target '192.0.2.10' -RemoteUser 'HIS01\svc_clinic_his_ro'`. A `[PASS]` here means only that Credential Manager accepted the write; it does not confirm that the password works on HIS.

Now verify the real access context:

```powershell
.\scripts\verify_his_access.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ExpectedAccount 'APP01\svc_clinic_tool'
```

This check requires the exact application-account SID, confirms the matching domain-password entry exists in that account's Credential Manager, lists the UNC path, and opens the required DBF files for read only. It does not write a test file. A pass proves that the credential entry is present and these required files are readable from this account at verification time; it does not claim that the entire share is readable.

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
- the task principal SID matches the local `svc_clinic_tool` account and its logon type is `Password`, which supports network access;
- the task keeps its AtStartup trigger, failure-restart policy, and unlimited execution time;
- the task action is this repository's `.venv` Python running `app.startup` from this repository;
- the local application port opens.

The scheduled startup entry point repeats the SID check under the task account, verifies the matching Credential Manager entry, and opens the required HIS tables read-only before importing the application or starting uvicorn. Missing credentials, a wrong task identity, or an unreadable required table stops startup without opening the listener. The start script's success message reports only that the local listener check passed; it does not verify LAN clients, the official Excel template, or SMIS.

LAN client access, the official workbook template, and manual SMIS upload remain external deployment checks. Keep them marked pending until an operator completes those checks on the clinic network with the approved template.

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

`scripts\stop.bat` stops the scheduled task and application processes that use this repository's `.venv` Python. Processes from another checkout are left alone. For a production update:

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

If the application account password is changed manually, run `onboard_app_host.ps1 -PythonPath 'C:\Program Files\Python312\python.exe' -SkipDependencyInstall` again with the new application password so Task Scheduler receives the new password. The script still does not change the HIS host.

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

If the task starts but no local listener opens, read `C:\clinic-data\app-data\application.log` for a startup preflight failure. Confirm the task account SID, its stored HIS credential, and read access to all three required DBF files. This startup check does not modify HIS.

- [Microsoft: Local User Accounts](https://learn.microsoft.com/en-us/windows/win32/ad/local-user-accounts)
- [Microsoft: Client Access to Network Resources](https://learn.microsoft.com/en-us/windows/win32/secauthz/client-access-to-network-resources)
- [Microsoft: `CredWriteW`](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
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
5. 在應用程式主機安裝共用的 Python 3.12，記下 `python.exe` 路徑。安裝目錄必須包含相符的標準函式庫、`venv` 與 `ensurepip`，不得只位於管理員的個人目錄，且 `svc_clinic_tool` 必須能執行它。onboarding 會在建立帳號、`.venv` 或排程前檢查這些 runtime 檔案。範例：`C:\Program Files\Python312\python.exe`。
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
Get-LocalGroupMember -SID ([System.Security.Principal.SecurityIdentifier]'S-1-5-32-544')
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

預期結果是必要資料表通過。必要資料表是 `CH012M1.DBF`、`CH011M1.DBF` 及 `PD011M1.DBF`。`H_INV.DBF` 是選用資料表。腳本會檢查指定分享、HIS 根目錄、存在時的 `DATA` 目錄及必要資料表的 ACL 中繼資料。它以 SID 解析唯讀帳號與本機群組成員關係，要求明確的 Allow-read，並拒絕匹配到的 Deny 或可寫入權限。若群組成員關係或 ACL 主體無法解析，會停止並要求 HIS 管理員確認。這項有限的中繼資料檢查不代表已證明分享根目錄內每個檔案的權限。

如果驗證失敗，請停止。不要使用自動修復指令。請交由 HIS 管理員檢查失敗項目。

### 第 2 階段：應用程式主機 onboarding

在應用程式主機使用提升權限的 PowerShell 視窗執行本階段。請將 `-HisPath` 改成現場的 UNC 路徑。

```powershell
Set-Location C:\clinic-antiviral-tool
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -PythonPath 'C:\Program Files\Python312\python.exe'
```

此腳本在應用程式主機依以下順序執行：

- 在修改主機狀態前，檢查指定的共用 Python 3.12 runtime，並確認既有 `.venv` 與它相符。
- 以安全提示輸入應用程式帳號密碼，密碼不會放在命令列；若 `APP01\svc_clinic_tool` 不存在就建立，否則沿用既有帳號。
- 確認工作帳號能啟動共用 Python；建立 `C:\clinic-data\app-data`、`C:\clinic-data\uploaded` 與需要的 `.venv`，設定 repository 權限，並確認工作帳號能啟動 venv 的 Python。
- 除非使用 `-SkipDependencyInstall`，否則安裝 `requirements.txt`。
- 更新 `.env` 中由腳本管理的設定（包含 `HIS_MIRROR_PATH`），設定執行資料夾權限，並註冊 Windows 啟動時執行的 `ClinicAntiviralTool` Task Scheduler 工作。
- 只有指定 `-ConfigureFirewall` 時，才建立應用程式埠的 Private 網路設定檔入站防火牆規則。

此腳本不會在 `HIS01` 建立或修改任何設定。此階段輸入的是應用程式帳號密碼，不是 HIS 密碼。既有 `.venv` 若與指定 Python 3.12 的 `pyvenv.cfg` 及實際直譯器版本相符，就會保留；不相符時流程會停止，並指示檢查後只重建 `.venv`，不刪除 SQLite、匯出檔或記錄檔。共用 runtime 與 venv 的工作帳號啟動檢查都通過後，腳本才會更新 `.env` 或排程。執行成功代表應用程式主機建置完成，不代表 HIS 憑證或唯讀存取已驗證；啟動前置檢查會在這些檢查通過前阻擋 listener，排程工作要到第 4 階段才會啟動。

以上範例不會更動防火牆。只有確認應用程式主機目前使用 Private 網路設定檔，而且需要主機防火牆規則時，才在命令中加上 `-ConfigureFirewall`。此開關只會建立 Private 設定檔的應用程式埠入站規則，不提供應用程式登入驗證。

工作帳號啟動 Python 失敗時，錯誤會保留底層原因，並在可取得時顯示數字形式的 Win32 錯誤碼。若要取得診斷資訊而不重跑 onboarding，請在 Windows PowerShell 5.1 中，從失敗時相同的工作目錄執行以下探測。模組路徑須指向已包含此診斷修正的 checkout。帳號須改為發生失敗的本機應用程式工作帳號，Python 路徑須使用當時指定的共用路徑（若失敗的是 venv，則使用其 Python 路徑）：

```powershell
Import-Module 'C:\clinic-antiviral-tool\scripts\ClinicAntiviral.Onboarding.psm1' -Force
$accountProbeCredential = Get-Credential -UserName "$env:COMPUTERNAME\svc_clinic_tool" -Message 'Enter the application account password for the Python probe'
try {
  Write-Host ("Probe working directory: {0}" -f (Get-Location).Path)
  Assert-ClinicPythonCanRunAsUser -PythonPath 'C:\Program Files\Python312\python.exe' -Credential $accountProbeCredential
  Write-Host 'PASS: the application account launched Python 3.12.'
}
finally {
  if ($null -ne $accountProbeCredential) { $accountProbeCredential.Password.Dispose() }
  Remove-Variable accountProbeCredential -ErrorAction SilentlyContinue
}
```

這只檢查 Python 能否啟動及版本，不會建立帳號、重建 `.venv`、更改排程或憑證，也不會存取 HIS。探測通過不代表相依套件匯入或整體 onboarding 已驗收。回報時請提供已遮蔽敏感資訊的錯誤文字與錯誤碼，不要提供密碼。

排程工作使用 Windows 啟動觸發、無執行時間上限，並在失敗時最多依既定政策重啟三次。它先以 `.venv` Python 執行 `app.startup`；該程式會用排程工作帳號檢查 SID、確認 Credential Manager 有 UNC 主機對應的 domain-password 憑證，並以唯讀方式開啟必要 HIS DBF，全部通過後才啟動 uvicorn。尚未儲存憑證或無法讀取 HIS 時，工作會結束且不會開啟應用程式 listener。

重新執行相同命令即可重設路徑或埠號，並須再次提供共用 Python 路徑。既有註解、不相關設定與 `SMIS_TEMPLATE_PATH` 會保留；每個由腳本管理的 key 只更新一筆。若腳本發現設定被串接或不是有效 UTF-8，請停止並依已確認的值重建 `.env`，不要猜測原值或自動拆分修復。

如果離線環境已經安裝 Python 套件，請使用以下版本：

```powershell
.\scripts\onboard_app_host.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -PythonPath 'C:\Program Files\Python312\python.exe' `
  -SkipDependencyInstall
```

#### 為什麼使用 Task Scheduler

本 repository 以一般 Python 程序啟動 `uvicorn`。真正的 Windows Service 是另一種程式類型，必須連接 Windows Service Control Manager。Task Scheduler 在 Windows 啟動時以 `svc_clinic_tool` 執行受檢查的啟動入口；入口會先驗證工作身分與必要 HIS 資料表的唯讀存取，再啟動 uvicorn。這是 v0.1.0 最小的設定方式。

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
  -RemoteUser 'HIS01\svc_clinic_his_ro' `
  -ExpectedAccount 'APP01\svc_clinic_tool'
```

腳本會先以 SID 確認目前帳號正是本機 `APP01\svc_clinic_tool`，再顯示安全密碼提示。密碼會以 domain-password 類型及本機持續性存入該帳號的 Credential Manager。`-Target` 必須完全等於 UNC 路徑的主機部分，不包含分享名稱。若 UNC 使用 IP，`-Target` 請使用該 IP，而 `-RemoteUser` 仍保留 HIS 電腦的真實名稱前綴，例如 `-Target '192.0.2.10' -RemoteUser 'HIS01\svc_clinic_his_ro'`。此處的 `[PASS]` 只表示 Credential Manager 接受寫入，不表示密碼已通過 HIS 存取驗證。

接著執行以下指令：

```powershell
.\scripts\verify_his_access.ps1 `
  -HisPath '\\HIS01\HISROOT' `
  -ExpectedAccount 'APP01\svc_clinic_tool'
```

此檢查要求目前帳號 SID 完全符合應用程式帳號，確認該帳號的 Credential Manager 有對應的 domain-password 憑證，列出 UNC 路徑，並以唯讀方式開啟必要 DBF。它不會寫入測試檔案。通過證明憑證項目存在且此帳號在檢查當下能讀取這些必要檔案，不代表整個分享都可讀。

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
- 排程主體 SID 符合本機 `svc_clinic_tool`，且登入類型為支援網路存取的 `Password`。
- 排程工作保留 Windows 啟動觸發、失敗重啟政策及無限執行時間。
- 排程工作由本 repository 的 `.venv` Python 在正確工作目錄執行 `app.startup`。
- 本機應用程式埠已開啟。

排程啟動入口會在工作帳號脈絡再次檢查 SID、確認該帳號 Credential Manager 有對應 UNC 主機的憑證，並在匯入應用程式或啟動 uvicorn 前唯讀開啟必要 HIS 資料表。缺少憑證、工作身分錯誤或資料表不可讀時，listener 不會啟動。啟動腳本的成功訊息只代表本機 listener 檢查通過，不代表 LAN 客戶端、官方 Excel 範本或 SMIS 已驗收。

LAN 客戶端連線、官方 Excel 範本及人工 SMIS 上傳仍是部署時的外部驗收項目。操作人員在診所網路使用核准範本完成檢查前，請持續標記為待驗收。

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

`scripts\stop.bat` 會停止排程工作及使用本 repository `.venv` Python 的應用程式程序，不會停止其他 checkout 的程序。正式更新使用：

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

如果應用程式帳號密碼由人工變更，請帶上 `-PythonPath 'C:\Program Files\Python312\python.exe' -SkipDependencyInstall` 再次執行 `onboard_app_host.ps1`，並輸入新密碼，讓 Task Scheduler 取得新的帳號密碼。此腳本仍不會修改 HIS 主機。

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

如果排程已啟動但本機 listener 沒有開啟，請查看 `C:\clinic-data\app-data\application.log` 的啟動前檢查錯誤。確認排程帳號 SID、該帳號儲存的 HIS 憑證，以及三個必要 DBF 的讀取權限。此啟動檢查不會修改 HIS。

- [Microsoft：Local User Accounts](https://learn.microsoft.com/en-us/windows/win32/ad/local-user-accounts)
- [Microsoft：Client Access to Network Resources](https://learn.microsoft.com/en-us/windows/win32/secauthz/client-access-to-network-resources)
- [Microsoft：`CredWriteW`](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
- [Microsoft：`Register-ScheduledTask`](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)

### 人工冒煙測試

人工檢查只限於實際系統邊界：

1. 使用唯讀 HIS 來源，依預期 HIS 紀錄確認近期處方、身分證號查詢及日期掃描。
2. 確認醫師頁面反應正常，且藥師表格可支援日常工作。
3. 使用正式範本產生官方工作簿，並確認 SMIS 接受人工上傳的檔案。
