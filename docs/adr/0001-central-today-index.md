---
status: accepted
---

# Central read-only today's index

The central clinic service builds one volatile in-memory index for today's matching HIS prescriptions at startup, reuses it for doctor lookups, and performs request-time metadata checks. Append-only DBF growth may be read incrementally; any change that cannot be proven append-safe requires a complete rebuild. This trades a one-time startup cost for fast shared lookups while preserving the non-negotiable boundary that DBF/FPT/CDX files are never written and save/export always re-reads the selected order from HIS.

The index is intentionally server-owned rather than browser- or client-owned so every workstation sees the same progress and snapshot. It is not a continuous background scanner, and the index never becomes the authority for a saved report.
