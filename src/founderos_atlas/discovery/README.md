# Atlas Discovery

## Adapter Architecture

`DiscoveryAdapter` is a transport-free normalization interface. It accepts an already-collected command-to-text mapping and returns vendor-neutral inventory, interface, and neighbor models. `DiscoveryEngine` checks required inputs, delegates parsing, and assembles one immutable `DiscoveryResult` with provenance facts.

Parsing and network transport are deliberately separate. Parsers are deterministic pure local transformations; SSH, SNMP, credentials, timeouts, retries, authorization, and durable side effects belong to future collection Activities outside this package.

## Vendor-Neutral Models

- `NetworkDevice` describes identity, management address, platform, OS, serial, and metadata.
- `NetworkInterface` describes normalized address and operational state.
- `NetworkNeighbor` describes one CDP, LLDP, manual, or inferred adjacency.
- `DiscoveryFact` retains typed source-command provenance.
- `DiscoveryResult` groups one normalized observation set.

Cisco IOS is only the reference adapter and fixture set. It cannot leak transport behavior or become the interface expected by Atlas consumers. Future vendors implement the same adapter contract and produce the same domain models.

## Risks and Next Step

Text parsers are intentionally bounded to known fixture shapes. Before live use, Atlas needs explicit collection Activities, parser-version provenance, fixture expansion, partial-result policy, and reconciliation rules. PR-014 must not be interpreted as production device support.
