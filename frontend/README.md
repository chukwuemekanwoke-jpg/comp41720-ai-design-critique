# StudentPath frontend

A responsive interface prototype: the supplied Stitch-inspired dark canvas, the supplied coat of arms of Ireland,
multilingual greeting, question composer, REST gateway connection, and a clearly
labelled administrator workspace preview.

## Preview

This directory is the repository copy of the approved hosted design. It contains
no separate Site repository metadata or hosting configuration. All frontend
backend calls must go through Gateway; see
[the integration plan](../docs/frontend-gateway-integration.md) and
[the contract inventory](../contracts/INTERFACES.md).

From the repository root, serve the frontend using a static HTTP server:

```sh
python -m http.server 8080 --directory frontend/dist
```

Open http://localhost:8080. In the connection menu, enter the REST gateway base
URL. Questions are posted to `/v1/questions` using the existing gateway contract.
Configure the gateway's CORS allowlist for the exact frontend origin. The gateway
in the project repository is currently a canned-response stub, not a complete
RAG pipeline. Stub responses are labelled in the UI.

## Admin scope

The admin dialog does not implement authentication. Its preview workspace lets
you select PDF/TXT/HTML files (10 MB maximum), supply metadata and stage draft
entries held only in memory for the current tab. It does not send files to a
server or update the collection. Closing or refreshing the tab discards drafts.

Production work requires a server-enforced administrator identity and role,
authenticated policy ingestion endpoints, file validation and durable storage,
review/publish controls, audit records and indexing status. The public browser
must never receive an administrator secret. Do not treat client-side navigation
as access control.

Proposed flow: frontend → REST gateway → authenticated ingestion service →
snapshot/outbox → RabbitMQ → indexer → versioned retrieval index. This extends
the original source-only scope to administrator-supplied policy documents and
requires a policy ingestion contract agreed with the collector/indexer owners.

The frontend identifies itself as a university project prototype, not an
official government service. No generated sample immigration advice is included.
The coat-of-arms SVG was supplied by the project owner; its use does not imply official government status.

## Design adoption

The dark interface adapts the supplied Stitch export: central blue glow, compact
header and tool rail, multilingual greeting, capsule composer and topic chips.
It retains the existing REST adapter and clearly labelled admin preview. It does
not ship the export's canned policy answers, fake voice transcription or claims
of official live synchronisation. Local CSS implements the layout without a
Tailwind CDN runtime. The previously supplied coat of arms is retained.
