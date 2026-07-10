# Atlas Sites — Evidence-Based Inference Foundation (PR-033)

A site is a location/administrative concept — never "a subnet". Assignment
weighs independent signals: explicit user mapping (high, decisive),
hostname conventions and seed-origin profile hints (assigning: one signal =
low, agreement = medium), and declared network ranges (corroborating only —
they raise confidence one step but can never assign by themselves, because
a site may hold many subnets and one supernet may span many sites).
Conflicting assigning signals yield **ambiguous**; no assigning signal
yields **unknown**. Every `SiteAssignment` carries status, confidence, the
explicit flag, and the full evidence list. The user-defined catalog lives
at `<workspace>/sites.json`.
