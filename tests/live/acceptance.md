# Azure acceptance checklist

Run only in an explicitly selected, authorised non-production test scope. This checklist is not a record of successful validation.

1. Generate Workbook JSON from the same configuration supplied to Bicep. Compile Bicep; review what-if for workspace, table, DCR/DCE, identity, lock storage, job and Workbook only. Optional subscription role assignments must be deliberately enabled.
2. Build/publish the checker image. Grant registry pull and required discovery/query permissions. Confirm the supplied private-network environment can resolve/reach health endpoints and Azure ingestion/lease services. Deploy only after the user requests it.
3. Run the opt-in read-only tests documented in README. Verify ARG returns expected tags/properties, both resource group and health queries compile, and tenant access matches configuration. Include >1,000 resources or a paged fixture scope if available.
4. Enable the collector. Confirm resource, endpoint and completion rows arrive in EnvironmentOverview_CL and the marker's ExpectedCount equals distinct resource IDs for its RunId. Ingestion is asynchronous: a marker arriving first must not expose an incomplete snapshot.
5. Configure a known healthy private endpoint. Verify platform healthy + endpoint success yields green, a confirmed endpoint 503 yields red, and missing authentication/DNS gives unknown with a useful reason. Do not break a real service; use a test-only endpoint whose response is controllable.
6. Stop collection for more than five minutes. Refresh the Workbook: old platform/endpoint signals must turn grey, with a stale coverage indication. Resume collection and verify recovery. Browser closure must not stop collection.
7. Exercise actual Sev 0–4 alerts in a disposable scope; confirm only currently fired alerts with matching target IDs affect the relevant resources. Resolve an alert and confirm it stops affecting health. Broad/unattributed alerts must be visible in collection issues.
8. Validate Environment/env case variants, conflicting tags, resource/group disagreement, shared parent tags, non-token naming matches and explicit overrides using disposable tagged resources. Unknown classifications stay visible; production is excluded from summaries by default; direct inventory is clearly labelled as including production.
9. Test an app with multiple serving revisions. Shared-FQDN probe inference must remain unknown unless revision checks can be explicitly mapped. Confirm inactive revisions do not affect active application status.
10. Open the generated Workbook in read mode. Check all colour formatting, counts, environment row selection, dropdown filters, search, separate shared/unassigned areas, attribution issues and portal timestamps. Verify auto-refresh is off on reopen and the instructions are visible.
11. Limit one health source's permissions. Inventory rows must survive; known endpoint failures must still be red; unaffected sources remain distinguishable. Compare inventory under a known full-read identity to detect RBAC-hidden resources.
12. Trigger two collectors together. Verify only one acquires the lock, a failed run cannot publish a completion marker, and a hard timeout cannot ingest after the lease expires. Test ingestion failure and ensure the old snapshot remains visible with its real age.

Record Azure region, API versions, permissions, exact commands, dates and results in docs/verification.md. Mark unavailable cases unverified rather than passing them with local mocks.
