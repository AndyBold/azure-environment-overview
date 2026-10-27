# Azure environment overview — approved design

Approved in conversation on 2026-10-27. Implementation defaults below were presented as proposals with that design.

## Intent
Provide a reusable Azure Workbook showing resource and environment health across projects with inconsistent tagging. Discover deployed resources, rather than checking an expected deployment manifest.

## Scope and constraints
- One Entra tenant per deployment; multiple selected subscriptions and Log Analytics workspaces.
- Include every discovered ARM resource type. Resource Graph is not an exhaustive inventory of data-plane objects; expose query and permission limitations.
- Query Azure Resource Graph for inventory, ARM for additional current state, and Azure Monitor for alerts, logs and metrics. Microsoft Graph is not the inventory API.
- Use private endpoint checks where applicable; assume network access can be supplied.
- No remediation, missing-deployment detection, cost analysis or historical trend views in the first version.

## Attribution
Use resource environment tags first, containing-resource tags next, then resource group tags, then configured naming rules. Match keys case-insensitively; recognise Environment and env plus configurable aliases. Trim and normalise values for grouping, preserving originals. Conflicting aliases at the same precedence are unassigned; show lower-precedence discrepancies as attribution issues.

Discover values dynamically. Infer common production, non-production and shared labels, showing classifications and allowing project overrides. Unrecognised values stay visible as unclassified environments. Production is excluded by default but can be inspected. Shared resources have a separate section; unresolved attribution belongs in Unassigned, not Shared. Show fallback attribution as a tagging gap.

## Health
Combine suitable resource-type-specific Azure health evidence, active Monitor alerts and applicable endpoint results. Sev 0–1 alerts are red, Sev 2–3 amber, Sev 4 informational. Confirmed platform unavailability or application failure is red; degradation is amber. Missing, stale or insufficient evidence is grey. Green requires meaningful, fresh healthy evidence; provisioning success and absence of alerts do not suffice. An inapplicable application check is distinct from a missing check.

Resource and environment rollups use red > amber > grey > green. All resources contribute equally; show counts alongside the summary. An empty group is unknown. Unsupported resource health remains grey. Preserve inventory rows when health queries fail. Consider traffic-serving Container Apps revisions for application health. Intentional shutdowns remain unknown unless a project policy defines expected behaviour.

## Collection and freshness
Reuse existing endpoint telemetry where it provides equivalent evidence, otherwise use a scheduled private-network checker writing resource-linked results to Log Analytics. Checks run every minute; samples older than five minutes become unknown. Endpoint targets come from explicit configuration or supported probe definitions, not arbitrary URL guesses.

For current-state APIs, successful query time establishes freshness; state-change and alert-fired timestamps are not heartbeats. Display observation time and query status separately. Configure per-source freshness thresholds, with five minutes as the initial health default.

Workbook refresh target is five minutes. Native Workbook auto-refresh is off on opening, is not saved, and must be enabled each session. The checker runs independently of the Workbook.

## Presentation
Follow ../../../workbook-mockup.html: environment summaries, resource details, Shared resources and Unassigned resources/attribution issues. Each resource shows overall colour, Azure health, application health, reason, timestamp and attribution. Filters select subscriptions, environments, resource types and status. Show coverage, stale data and collection failures.

## Approaches
Considered Azure Workbook, a custom dashboard with background collection, and a generated static dashboard. User selected Workbook to use Azure's monitoring experience. Some supporting collection is still required for private checks.

## Builder choices
Proposed implementation: Bicep templates, Workbook JSON generated from KQL query files, Python checker and Azure Monitor Logs ingestion. Keep project configuration separate from reusable components. Network topology and project-specific health policies are deployment inputs. Resource-type health adapters can be extended without hiding unsupported resources.

## References
- https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-data-sources
- https://learn.microsoft.com/en-us/azure/azure-monitor/visualize/workbooks-configurations#set-up-auto-refresh
- https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview
- https://learn.microsoft.com/en-us/azure/container-apps/health-probes
