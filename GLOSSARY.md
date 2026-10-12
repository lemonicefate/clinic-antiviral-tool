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
