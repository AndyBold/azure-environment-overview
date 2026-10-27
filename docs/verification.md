# Verification evidence — 2026-10-27

## Local checks

Executed from `/home/andyb/azure-environment-overview` using Python 3.14.8:

- `python -m unittest discover -s tests -v`: 46 discovered; 45 passed, one Bicep compilation test skipped because Azure CLI/Bicep are absent.
- `python -m unittest discover -s tests/live -v`: four tests skipped because live Azure validation was not enabled and no deployment scope/configuration was provided.
- `python -m workbook.build --config config/project.example.json --output dist/workbook.json`: generated the importable Workbook artifact.
- `python -m compileall -q overview checker workbook tests`: Python modules compile locally.
- JSON parsing checks cover project example/schema, ingestion columns and generated Workbook.
- `python -m checker.main --help`: entrypoint is available without importing Azure SDKs until a live operation is requested.

These checks do not prove Azure API compatibility or Workbook rendering. No Azure deployments, role assignments, image publication, external messages or remote changes were performed.

## Environment limitations

- Azure CLI and Bicep are not installed. Template compilation and deployment what-if were not run successfully.
- Shell DNS/network access is unavailable, so required Azure dependencies could not be installed and provider API requests could not be exercised.
- Docker exists, but access to `/var/run/docker.sock` is denied. No successful image build was performed.
- Local socket binding is denied. Probe tests inject the HTTP transport; actual private DNS, TLS and endpoint reachability remain unverified.
- There is no Git repository in the project folder. Files were left in place without implicit repository creation, commits, pushes or worktrees.

## Independent review and corrections

A separate read-only reviewer examined the design, implementation, tests and explicit implementation decisions. Eight important findings were identified. The implementation addresses them as follows:

1. Application status carries evidence time from its controlling checks: freshest still-valid failure for red, oldest required observation for healthy/unknown. Regression observed failing, then passing.
2. Proven obsolete revision checks are excluded, latest-template probe inference is blocked when an older revision serves traffic, and multiple serving revisions require individual coverage. Regression cases observed failing, then passing.
3. Unavailable higher-precedence tags prevent confident lower-precedence attribution. Regression observed failing, then passing.
4. Parent override IDs are matched case-insensitively; conflicting case-equivalent override keys are rejected. Regressions observed failing, then passing.
5. SelectedEnvironment is a single global parameter declared before the environment summary exports to it. Generated-artifact regression observed failing, then passing; actual browser interaction remains unverified.
6. Endpoint results are reduced globally by resource/check and parsed observation timestamp. At equal timestamps, fail wins over unknown, then pass. Regression observed failing, then passing.
7. Known VM stopped/deallocated states and stopped App Service states are mapped to unknown platform health. A representative deallocated-VM regression observed failing, then passing. Other provider stop semantics remain unsupported rather than inferred.
8. Coverage compares the selected complete snapshot against the newest observed run across all row kinds, including partial rows without a manifest. The actual-KQL datatable regression is written, but execution is **unverified** because it requires Azure Log Analytics. This correction has been statically inspected only.

There was no second independent review of the corrections. Local regressions and the full suite were rerun by the implementer.

## Deferred minor findings

- Status/type dropdowns currently filter the environment-resource grid; shared, unassigned and attribution-issue grids retain their own grid search and are not affected by those dropdowns.
- Each health panel currently queries/materializes two days of snapshots. Large-estate performance has not been benchmarked; optimise candidate-run selection before claiming large-scale support. Configured one-minute inventory ingestion also carries volume-dependent costs.

## Implementation decisions and their practical limits

1. Keep work in the dedicated local folder without Git/worktree creation. There is no commit history until the user establishes a repository.
2. Use a normalised collector snapshot plus direct Workbook Resource Graph inventory, rather than native cross-source merges for the entire model. The health view depends on collector ingestion and explicitly reports age/coverage.
3. Use REST for management/query/ingestion boundaries, with Azure Identity and Blob Storage SDKs for authentication/locking. Real API contracts still need Azure validation.
4. Inject transports for local tests because the sandbox cannot bind sockets. Those tests do not prove networking.
5. Use a 60-second blob lease and hard 55-second execution lifetime to avoid overlap. Estates that exceed the window need narrower deployments or a future renewing lease.
6. Preserve Azure Container Apps' configured probe semantics: inferred probes accept 200–399; explicit endpoints default to 200–299. Neither follows redirects. A project requiring 200-only success should configure an explicit check.

Metrics-based adapters, cost/history, missing-deployment detection and automatic remediation remain outside the approved first-version scope. Deployment readiness, RBAC completeness, ingestion latency, private networking and portal rendering require the [Azure acceptance checks](../tests/live/acceptance.md).
