# Atlas Credentials — Multi-Credential Strategy (PR-033)

Named credential sets whose entries carry a priority and a generic scope
(vendor, platform, hostname globs, CIDRs, sites, profiles, device ids —
extensible via `kind` for future SNMP/NETCONF/API/cloud credentials).
`CredentialResolver` builds a deterministic, bounded candidate list per
device. Precedence (lockout protection — a targeted credential is never
preceded by a generic one that would burn a failed attempt):

1. previously successful reference for that device;
2. the profile's own credential — first **only for the profile's seed
   devices** (explicitly paired by the operator) and for legacy profiles
   with no credential sets;
3. scope-matching entries by match specificity — explicit device id >
   exact host/IP or exact hostname > CIDR/hostname pattern >
   vendor/platform > site/role/profile — with priority (ascending) and
   declaration order breaking ties within a class;
4. the profile's own credential where nothing better-scoped matched;
5. unrestricted "general fallback" entries last.
`MultiCredentialTransportFactory` tries candidates safely at connect time —
stop at first success, never retry a failed credential on the same device,
bounded attempts (lockout protection), abort immediately on non-auth errors.
`CredentialSuccessMemory` remembers only the *reference* that worked.

Secrets live exclusively in the secure `CredentialProvider`; sets, memory,
attempts, and history metadata store references only. The profile's own
credential is the implicit priority-0 candidate, which keeps every
pre-PR-033 profile working unchanged. Never brute-force: candidate lists
are scoped, ordered, and bounded by design.
