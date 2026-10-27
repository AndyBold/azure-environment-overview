# Azure Environment Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Azure Workbook discovering non-production resources and showing evidence-based platform and application health.

**Architecture:** Workbook queries Resource Graph and Azure Monitor, merging evidence by normalised ARM resource ID. A scheduled Python checker inside the private network publishes endpoint observations to Log Analytics. Bicep deploys the Workbook and supporting collection resources; project parameters supply scope, attribution overrides and endpoint policies.

**Tech Stack:** Azure Workbook JSON, Resource Graph KQL, Log Analytics KQL, Bicep, Python 3.12+, azure-identity, azure-monitor-ingestion, azure-mgmt-resourcegraph, standard-library unittest and HTTP client. Pin supported dependency versions during implementation.

**Spec:** `docs/superpowers/specs/2026-10-27-environment-overview-design.md`

## Global Constraints
- All discovered resource types appear and contribute equally.
- Resource and environment rollups use red > amber > grey > green.
- Sev 0–1 alerts are red, Sev 2–3 amber, Sev 4 informational.
- Checks run every minute; samples older than five minutes become unknown.
- Green requires meaningful, fresh healthy evidence; provisioning success and absence of alerts do not suffice.
- Shared resources have a separate section; unresolved attribution belongs in Unassigned, not Shared.
- One Entra tenant per deployment; multiple selected subscriptions and Log Analytics workspaces.
- No remediation, missing-deployment detection, cost analysis or historical trend views in the first version.
- Never deploy or change Azure resources during planning. Use a dedicated non-production test scope for live validation.

## Review Focus
- Large or partially readable inventories must show coverage gaps, never silently truncate (Task 1, Task 5).
- Conflicting tags, mixed case and ambiguous names must not assign resources confidently to the wrong environment (Task 1).
- Failed joins, stale samples and long-lived healthy states must preserve inventory and distinguish unknown from healthy (Task 2).
- Private DNS, authentication failures, redirects and overlapping checker executions must not fabricate application success (Task 3).
- Alert scopes, traffic revisions and independent shared resources must not contaminate unrelated environment status (Task 2, Task 5).

## File map and contracts
- `config/project.example.json`, `config/project.schema.json`: subscriptions, workspace IDs, tag aliases, classification overrides, naming rules, parent relationships, health policies and endpoint overrides. Config contains secret references, never credentials.
- `queries/inventory.kql`, `queries/attribution.kql`: resource inventory and attribution.
- `queries/alerts.kql`, `queries/platform-health.kql`, `queries/endpoints.kql`: normalised health evidence.
- `queries/resource-status.kql`: final status calculations applied within supported Workbook query/merge capabilities.
- `workbook/build.py`, `workbook/template.json`: reproducible deployable Workbook generation.
- `checker/models.py`, `checker/discovery.py`, `checker/probes.py`, `checker/ingest.py`, `checker/main.py`: private checks, resource discovery, ingestion and execution.
- `infra/main.bicep`, `infra/workbook.bicep`, `infra/monitoring.bicep`, `infra/checker.bicep`: deployment and least-privilege identities.
- `tests/fixtures/`, `tests/test_*.py`, `tests/live/`: synthetic fixtures, executable contract checks and opt-in Azure tests.
- `README.md`, `requirements.txt`, `Dockerfile`: setup, dependencies and checker packaging.

**InventoryRow:** resourceId (lowercase), name, type, subscriptionId, resourceGroup, environment (nullable), classification (nonproduction/production/shared/unclassified/unassigned), attributionSource, attributionIssues.

**HealthEvidence:** resourceId, signal (platform/alert/application), status (red/amber/grey/green/notApplicable), reason, observedAt, retrievedAt, source, freshnessSeconds. All times UTC.

**EndpointObservation:** TimeGenerated (completion time), ResourceId, CheckId, Outcome (pass/fail/unknown), HttpStatus (nullable), DurationMs, Reason, Revision (nullable). Log table `EnvironmentEndpointHealth_CL`; ResourceId identifies the monitored resource, not the checker.

## Task 1: Discovery, configuration and attribution
**Files:** config files; inventory and attribution queries; `tests/test_attribution.py`; `tests/fixtures/inventory.json`; `tests/live/test_inventory.py`.

**Interfaces:** Consume project JSON. Produce InventoryRow. Explicit overrides win classification inference; direct-tag conflicts remain unresolved until a resource override is supplied.

- [ ] Define and validate configuration schema, including resource attribution overrides and health freshness policies. Add fixtures for mixed-case keys, aliases, whitespace, conflicting values, shared parents, unknown labels and production overrides.
- [ ] Write failing contract tests: `Environment=DEV` groups as dev; conflicting Environment=dev/env=test is unassigned; explicit resource tags beat parent tags; unmatched labels stay visible; prod is excluded only by classification filter. Run `python -m unittest tests.test_attribution -v`; verify missing implementation failures.
- [ ] Implement inventory and attribution KQL using ResourceContainers for resource group joins. Only infer actual configured ARM parent relationships, never arbitrary name substrings. Match naming rules on explicit token boundaries; ambiguous matches are unassigned.
- [ ] Implement opt-in live query checks that run the actual KQL against fixtures in a disposable Azure scope. Validate schema, all returned pages/count reconciliation, inaccessible scopes and unsupported resource visibility. Test helpers execute queries through Azure CLI; no separate Python imitation of KQL logic counts as proof.
- [ ] Run local schema/fixture tests and the live suite when Azure access exists. Record unavailable live validation explicitly. Commit the task if the project is in a Git repository.

## Task 2: Health evidence and rollups
**Files:** health queries, resource-status query, `tests/fixtures/health.json`, `tests/test_health_contract.py`, `tests/live/test_health_queries.py`.

**Interfaces:** Consume InventoryRow and EndpointObservation. Produce HealthEvidence and resource/environment status rows with separate reason and coverage fields.

- [ ] Write failing fixtures/assertions: Sev 0/1→red; Sev 2/3→amber; Sev 4 alone→grey without positive health; fresh healthy applicable signals→green; fresh red plus stale signal→red; healthy plus missing required signal→grey; application notApplicable does not block green. Run `python -m unittest tests.test_health_contract -v` and confirm failures.
- [ ] Implement active fired alert queries, excluding resolved alerts. Associate affected ARM IDs only; show unattributable broad alerts separately rather than applying them to every resource. Preserve inventory with left joins.
- [ ] Implement initial positive platform adapters for available Azure Resource Health states and Container Apps serving revision/replica evidence. Treat provisioning state as supplementary. Explicitly mark unsupported signals unknown; do not claim uniform Resource Health support.
- [ ] Implement latest endpoint result by resource/check and observation time, with five-minute staleness. Ignore obsolete revision checks only when current traffic routing confirms they are no longer relevant. Query success time, not old state-change time, establishes current-state freshness.
- [ ] Implement ordered worst-status rollup, empty-group unknown and resource counts. Include shared/unassigned grouping without double counting. A failed health source produces unknown coverage while preserving independently known failures.
- [ ] Run actual KQL through live tests, including failed health joins, old-but-current platform states, multiple workspaces, multiple revisions, resolved alerts and scope contamination cases. Commit after checks.

## Task 3: Private endpoint checker
**Files:** checker modules, dependency file, Dockerfile, `tests/test_checker.py`.

**Interfaces:** `discover_targets(config: dict) -> list[dict]`; `probe(target: dict, now: datetime) -> dict` returns EndpointObservation; `publish(observations: list[dict], config: dict) -> None`; `run(config: dict) -> int`.

- [ ] Write failing unit tests using a local HTTP fixture and mocked ingestion: 200 configured success→pass; 503→fail; DNS/TLS/authentication configuration error→unknown with reason; timeout→fail with timeout reason; redirect not accepted by default; no configured application target→no fabricated pass. Run `python -m unittest tests.test_checker -v`; confirm missing implementation failures.
- [ ] Implement discovery through paginated Resource Graph queries. Use configured endpoints or supported HTTP probe configurations with routable ingress; otherwise report inability to establish a target. Do not guess URLs or expose secrets in results.
- [ ] Implement bounded concurrency (10), request timeout (10 seconds), TLS verification, no redirects by default and configurable expected HTTP codes (default 200–299). Authentication comes from managed identity or secret references. Discovery checks current serving revisions and deduplicates resource/check pairs.
- [ ] Implement ingestion using managed identity, bounded retry for transient ingestion failures and nonzero exit on unreported results. Timestamp observations at completion, not ingestion. Never write credentials or full endpoint bodies to logs.
- [ ] Implement `run` and an idempotent one-shot entrypoint for scheduled execution. Configure the deployment to prevent overlapping runs; tolerate duplicate observations by query-side resource/check/time reduction. Record collection failures independently of endpoint failures.
- [ ] Run unit suite, build container and run against local fixture. Verify ingestion contract with the real data collection rule in the later deployment test. Commit after checks.

## Task 4: Deployment and collection identity
**Files:** infra templates and `tests/test_deployment_contract.py`.

**Interfaces:** Inputs: selected subscriptions, workspace, existing Container Apps environment with private connectivity, image reference, project configuration and optional checker enablement. Outputs: workbook ID, DCR immutable ID, ingestion endpoint and checker identity. Existing telemetry can replace checker deployment.

- [ ] Write failing deployment contract tests for table schema matching EndpointObservation, checker cron `* * * * *`, one execution at a time, managed identity and restricted ingestion scope. Run `python -m unittest tests.test_deployment_contract -v`.
- [ ] Implement Bicep for custom table, DCR/ingestion endpoint and scheduled Container Apps Job in the supplied network-enabled environment. Use runtime timeout/replica settings that prevent overlapping minute jobs; verify the service's supported settings rather than assuming Kubernetes concurrency policy exists.
- [ ] Grant the checker only required discovery and ingestion access. Document Workbook viewer permissions for inventory, health, alerts and workspace logs. Account for separately scoped subscription RBAC deployment prerequisites.
- [ ] Run `az bicep build --file infra/main.bicep` and contract tests. Run `az deployment group what-if` against the chosen test scope only when credentials and parameters are available. Expect no broad role assignments, public application endpoint exposure or unrelated resource deletion. Commit after checks.

## Task 5: Workbook generation and interaction
**Files:** workbook files, `tests/test_workbook.py`, `tests/live/test_workbook.md`.

**Interfaces:** `build(config: dict) -> dict` in workbook/build.py returns Workbook serializedData JSON; `python -m workbook.build --config config/project.example.json --output dist/workbook.json` writes the artifact. Consume query contracts from Tasks 1–2; Bicep loads the generated artifact.

- [ ] Write failing structural tests asserting subscription/workspace/environment/type/status parameters, resource-ID normalisation, left joins, every status label, separate shared/unassigned sections, coverage notices and no embedded secrets. Run `python -m unittest tests.test_workbook -v`.
- [ ] Generate Workbook JSON with native query, merge, tile and grid controls matching the approved mockup's hierarchy. Check supported merge expressions against current Microsoft documentation; do not assume ARG queries can join workspace tables directly.
- [ ] Add environment selection drilldown, status counts, separate Azure/application columns, reasons, freshness and attribution. Display production classification controls, tagging gaps and unknown/partial inventory warnings. Never silently present truncated query results as complete; detect result limits and require narrower scopes where native query pagination is insufficient.
- [ ] Add visible auto-refresh instructions and last successful retrieval time. Independent collection does not imply the browser view is fresh. Preserve unknown resources when filters and health joins change.
- [ ] Run generation and tests. Import into the test subscription and manually verify environment selection, search/filtering, shared/unassigned separation, unknown coverage and refresh behaviour. Commit after checks.

## Task 6: End-to-end verification and project handoff
**Files:** README.md, `tests/live/test_end_to_end.py`, example configuration and deployment runbook.

**Interfaces:** Consume generated Workbook, compiled Bicep and packaged checker. Produce a reusable source package and an evidence report identifying completed checks versus unverified Azure behaviour.

- [ ] Write an opt-in integration test: discover known tagged test resources; ingest healthy then failed endpoint observations; assert green→red; age the last observation beyond five minutes and assert grey; retain unrelated shared/unassigned rows. Verify no endpoint check depends on an open Workbook.
- [ ] Run `python -m unittest discover -s tests -v`, Workbook generation and Bicep compilation. Validate real query schemas, DCR ingestion latency, permissions and refresh with Azure tests when access exists; do not substitute mocks for service validation.
- [ ] Document quick start, per-project overrides, production inference review, endpoint onboarding, signal coverage by type, RBAC, freshness, query limits, ingestion/network requirements and a checker-free mode using existing telemetry. State that all discovered types appear but some health remains unknown.
- [ ] Review artifacts for secrets and unintended production inclusion. Record unresolved constraints and exact verification evidence. Commit if in a repository; otherwise hand over files without creating a repository implicitly.

## Execution prerequisites and handoff
Before live deployment obtain the intended Azure tenant/test subscriptions, resource group, workspace, existing private-network Container Apps environment and deployment identity. These are not needed to author reusable artifacts. Deploying into an external Azure subscription requires explicit user instruction; plan approval alone is not deployment approval.

Recommended execution: Native, because attribution, health queries, ingestion schema and Workbook merges share contracts and benefit from one consistent implementation context. A final independent review should check the complete result. Subagent-driven execution is available if requested.
