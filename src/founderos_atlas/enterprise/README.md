# Atlas Enterprise Topology (PR-033)

Aggregates every profile's latest scoped snapshot into one enterprise view
with per-observation provenance (profile id, run id, timestamp). Canonical
identity across profiles is strictly evidence-based: serial numbers always
merge; hostname+IP agreement merges only when both profiles declare the
same administrative domain; hostname alone or IP alone never merges. Site
assignment comes from the sites inference engine and may honestly be
unknown. Because the view aggregates rather than compares, absence from one
profile's run can never mark another profile's device as removed —
per-profile baselines (PR-031A) are untouched.
