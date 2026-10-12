# Clinic Antiviral Tool

This context covers the safe selection and confirmation of publicly funded antiviral prescriptions from the read-only HIS source.

## Prescription lookup

**HIS 可見時間**:
The date and time at which a prescription is readable in HIS. It is the time used to decide which same-day prescription is newest.

**今日完整搜尋**:
A lookup limited to prescriptions whose HIS report date is today, regardless of how early in today's clinic session they became visible. It never silently searches a previous date.

**近期快徑窗口**:
A short, time-bounded lookup window near the current HIS-visible time used to find a newly visible prescription before offering a broader same-day lookup.

**最新處方**:
The same-day matching antiviral prescription with the greatest HIS visible time. If multiple candidates cannot be ordered safely, they remain candidates for user selection.

**候選處方**:
A same-day prescription that matches the selected doctor and configured antiviral medication rules and is presented for confirmation before it becomes the selected prescription.

**今日索引**:
A derived view of the prescriptions visible in HIS for today's report date, organized so a doctor lookup can find matching candidates without repeating the same full-day read.

**索引可複用**:
The property that a today's index may serve later doctor lookups while its source data remains unchanged and the clinic date has not rolled over.

**索引預熱**:
Building the today's index before a doctor lookup so the first search does not pay the full indexing cost.

**增量尾端更新**:
Extending today's index by reading only DBF records appended after the last safe cursor; it is allowed only when the earlier bytes and table layout are unchanged.

**完整重建**:
Discarding the in-memory today's index and reading the known source tables again when a change cannot be proven append-safe.

## Safety boundary

**HIS 重新確認**:
A fresh read of the selected prescription from the read-only HIS source before saving or exporting, so a cached or indexed candidate cannot silently become stale authority.

**客戶端**:
A clinic-LAN browser user who operates the `/doctor` or `/pharmacy` workflow; this context has no application login, password, or role-based access control.
_Avoid_: 應用程式帳號, 使用者登入

**伺服器端 HIS 唯讀服務帳號**:
An operating-system account on the HIS host whose credential is used by the central application host to read the HIS source, separate from client users and restricted to the required HIS data only.
_Avoid_: 醫師帳號, 藥師帳號, 共用管理員帳號

**應用程式主機工作帳號**:
An operating-system account local to the application host that runs the scheduled task and owns the stored HIS credential; it is not the HIS account and is not a client identity.
_Avoid_: HIS 帳號, 客戶端帳號, 管理員帳號

**HIS 唯讀資料分享**:
The network-accessible HIS data boundary from which the server may list and read reporting source files but may not create, modify, rename, or delete them.
_Avoid_: HIS 主機登入, HIS 管理分享

**HIS 主機引導式驗證**:
A read-only onboarding procedure that checks the existing HIS account, share, permissions, and source tables, then tells an administrator what to do next without changing HIS settings.
_Avoid_: 自動 Provision, 遠端修復 HIS, 自動調整 ACL
