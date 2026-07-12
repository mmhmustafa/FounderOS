# Atlas Guided Demo (5–10 minutes)

Audience: a senior network engineer or CAB reviewer.
Setup: Hyderabad Lab and Secunderabad Lab profiles exist; both were
discovered at least once (CML: R1/SW1/SW2 + R11, or the two-lab
fixtures). Start Atlas and open http://127.0.0.1:<port>/.

## 1. Mission (1 min)

You land on **Mission — Enterprise**. Point out:
- "What are you trying to do?" — workflows, not modules.
- Enterprise Health: both labs contributing, freshness per profile.
- Today's Recommendations — each one cites its evidence; if everything
  is fresh and analysed it honestly says nothing needs attention.

## 2. Search (1 min)

Press **Ctrl+K**. Type `R11` (the device both labs can see):
- ONE canonical result — 95% identity confidence, 2 observations.
- Type an IP (`10.10.10.2`), an interface (`Gi0/1`), a site name — show
  grouped, deterministic results with the matched field named.
- Open the device: **Device Details** shows the merge WHY, every
  observation with profile/run/timestamp, interfaces with neighbors.

## 3. Enterprise Graph (1–2 min)

Topology (Enterprise scope):
- ONE federated interactive topology spanning both labs.
- Inventory: the shared device appears once, badged **merged**, with
  provenance on demand.
- Merge Decisions table: "every observation reports the same serial
  number" — engineers can audit every merge.
- Unknown Boundaries: what Atlas has NOT discovered stays visible.

## 4. Prediction (1–2 min)

Predict (Enterprise scope) → pick SW1 `Vlan1` (or any interface):
- Blast radius, documented risk factors that sum to the score,
- plane-aware impact (shutting the management SVI says **Management
  Plane: Lost — do not proceed until an alternate path is verified**),
- confidence with its factors, and what Atlas cannot see.

## 5. Path Intelligence (1–2 min)

Paths (Enterprise scope) → Source: a Hyderabad device, Destination: a
Secunderabad device:
- FLOW walks the canonical topology ACROSS labs through the merged
  gateway; every hop shows its evidence.
- (If time) shut an interface in CML, re-discover, re-run: the
  investigation stops RED at the failed hop and explains WHY.

## 6. Compass (2 min)

Compass → New Plan "Core maintenance" → add:
1. IOS upgrade of the shared gateway (rollback: no),
2. Shutdown of the uplink to an access device,
3. An ACL change on the device behind that uplink.

**Analyse Plan**:
- The ACL change is ordered BEFORE the shutdown — with the prediction's
  blast radius cited as the reason.
- Risk summary: overall risk, largest blast radius, rollback coverage
  including honest unknowns.
- Add a duplicate shutdown → a conflict WARNS but never blocks.

## 7. Close the loop (30 s)

Back to Mission: the plan, the investigation, and the prediction all
appear as resumable activity; the recommendation panel reflects
anything left undone. One product, one graph, every answer explained.

## One-line close

*"Atlas never guesses: every merge, every risk score, every ordering
cites the evidence it stands on — and when evidence is missing, Atlas
says Unknown instead of making something up."*
