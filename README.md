# StudentPath: a RAG assistant for Irish immigration guidance

COMP 41720 Distributed Systems, Group 17

**Team:** Chukwuemeka Nwoke, Kezhen Zhang, Jordan Hennessy, Sunmin Lee

---

## Project statement

International students in Ireland, and recent graduates, regularly need to find
official answers to questions such as *"Where are the requirements for moving
from Stamp 2 to graduate Stamp 1G?"* The answers exist on the Irish Immigration
Service Delivery (ISD) website (irishimmigration.ie), but they are spread across
student FAQs, permission-stamp pages, renewal guidance, required-document lists
and graduate policy.

StudentPath is a focused information assistant that answers these questions in
plain language **and shows its evidence**. Every answer carries:

- a plain explanation of the answer,
- an evidence-based checklist,
- links to the official source passages used, and
- the date the collection was last checked.

### Initial scope

| In scope | Out of scope |
| --- | --- |
| Stamp 2 registration and renewal, and the transition to graduate Stamp 1G | Eligibility decisions about an individual |
| English only for the first version | Personal documents or uploads |
| 15-25 selected official sources | Application submission |
| Fictional test questions | Legal advice |

StudentPath helps people **find and understand official guidance**. It does not
decide anyone's immigration status.

---

## The brief

This project is Option B of the COMP 41720 group project: **an AI-native
distributed system.**

| Requirement | What it means for us |
| --- | --- |
| Working system | At least four independent services, with one service and one ADR owned by each member |
| Demonstrated behaviour | A useful asynchronous path, explicit consistency decisions, and recovery under injected failure |
| Reproducible demonstration | One-command startup, local or free infrastructure, synthetic data, and offline fallbacks for dependencies |
| Assessment evidence | Eight-page report, five separate one-page ADRs, AI disclosure, contributions, and an individual viva |

### Common demonstration baseline

The same acceptance checks apply whichever topic a group selects.

- **Answer quality:** 30-40 questions with expected evidence, including cases
  with missing evidence, conflicting sources and prompt-injection attempts.
- **Versioning:** record model, prompt and index versions, and test what users
  see during a delayed document update.
- **Failure and consistency:** inject model timeouts and duplicate update
  events, and show recovery, retry limits and idempotent processing.
- **Operations:** export rate, errors, latency and token usage or cost; cap
  generation and demonstrate the local fallback.

### Selection gate

Before committing to the build, we check ten source documents against ten
questions. We continue only if the evidence supports reliable answers.

---

## Why RAG suits this project

### 1. The answers must come from official, current sources

Immigration rules change, and a wrong answer can have real consequences for a
student's status. A language model answering from its training data cannot be
trusted here: it may be out of date, and it has no way to point at the rule it
relied on. RAG grounds each answer in a selected set of ISD documents, so the
system answers from what the official pages say today rather than from memory.

### 2. Evidence is part of the product

Users need to verify what they are told before acting on it. RAG naturally
produces source links and the collection version used for each answer, which
is exactly the answer format StudentPath needs. Fine-tuning a model on the
same material would bake the knowledge in and lose that traceability.

### 3. The corpus changes, and the system has to keep up

ISD guidance is updated over time. With RAG, a changed page is re-fetched,
re-split and re-indexed, and the model itself stays untouched. That update path
is cheap, and it is also where the distributed-systems material lives:

- a **source collector** detects and snapshots changed documents,
- updates enter an **indexing queue**,
- an **indexing worker** builds a new, versioned index, and
- a **retrieval API** and **answer service** serve queries against a known
  index version.

### 4. The architecture is a natural distributed system

The RAG pipeline splits into independent services with real boundaries, so the
Option B requirements arise from the problem instead of being bolted on:

| Brief requirement | Where it appears in StudentPath |
| --- | --- |
| Asynchronous path | Document updates flow through a queue to the indexer |
| Explicit consistency decisions | What a user sees while a re-index is in flight, and which index version an answer cites |
| Recovery under injected failure | Model timeouts, duplicate update events, retries and idempotent indexing |
| Local fallback | A simulated or local model when the hosted one is unavailable |
| Independent services, one per member | Collector, indexer, retrieval API, answer service, and a fifth service for the gateway or evaluation |

### 5. Its limits can be tested

Retrieval does not guarantee correctness. The topic gives us concrete failure
modes to test and report, which is what the assessment asks for:

- **Freshness:** is the answer based on a page that has since changed?
- **Unsupported eligibility claims:** does the system refuse to make a
  decision when the evidence only describes a general rule?
- **Missing evidence:** does it say it does not know instead of guessing?
- **Malicious source instructions:** does text inside a retrieved document get
  treated as an instruction?

### 6. The scope is small and bounded

A corpus of 15-25 public official sources, fictional questions only and no
personal data keeps the prototype feasible, avoids privacy problems, and lets
the team build a trustworthy evaluation set within the project timeline.

---

## Why StudentPath over the other options

The group considered eight topics and shortlisted three:

| Candidate | Main attraction | Main burden |
| --- | --- | --- |
| **StudentPath** | Focused audience and official source collection | Freshness, uncertainty and consequential errors |
| UCD student handbook | Familiar users and tightly bounded questions | Programme coverage and policy precedence |
| Technical documentation | Answers can often be checked by running examples | Version compatibility and safe example testing |

StudentPath is the best fit for the requested student-focused public-sector
project, and its main burden (freshness and the cost of a wrong answer) is the
one that makes RAG, versioning and failure handling matter most.

---

## Architecture

Branching, mandatory review, automated checks and the deployment boundary are
documented in [the development workflow](docs/development-workflow.md).

The approved interface is in [frontend/](frontend/README.md). Its REST integration,
repository data sources and proposed administrator ingestion flow are documented
in [the frontend/Gateway integration plan](docs/frontend-gateway-integration.md).
The [contract inventory](contracts/INTERFACES.md) distinguishes existing APIs from
proposed endpoints. The Gateway now calls Retrieval and Answer over REST; admin
authentication and uploads are not implemented. See [Gateway run instructions](docs/gateway-api.md).

The Source Collector implementation, RabbitMQ demo and relay delivery contract
are documented in [SOURCE_COLLECTOR.md](SOURCE_COLLECTOR.md).

The draft service split, with a candidate ADR for each service and the open
decisions, is in [docs/architecture.md](docs/architecture.md).

## Status

The standalone [Retrieval API prototype](docs/retrieval-api.md) implements
`POST /v1/retrieve` with ranked keyword search, pinned index versions, provenance
and synthetic demo data. SQLite integration awaits an agreed index read contract.

Topic selected on 17 October 2026. The next steps are the source-validation
gate, the service split with an owner for each, and the five ADRs.
