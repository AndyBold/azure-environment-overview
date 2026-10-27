"""Collect a complete inventory snapshot and independent health evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid

from overview.attribution import attribute
from overview.config import validate
from overview.health import evaluate, parse_time
from checker.discovery import targets_for, serving_revisions
from checker.probes import probe

QUERY_DIR = Path(__file__).resolve().parents[1] / 'queries'


def query(name):
    return (QUERY_DIR / (name + '.kql')).read_text()


def container_health(resource, client):
    serving = serving_revisions(resource)
    if not serving or None in serving:
        return None
    revisions = client.list_arm(resource['id'] + '/revisions', '2024-03-01')
    selected = [r for r in revisions if r.get('name') in serving]
    if len(selected) != len(serving):
        return None
    states = []
    for revision in selected:
        rp = revision.get('properties', {})
        state = rp.get('healthState')
        if not rp.get('active') or not rp.get('replicas', 0):
            state = 'Unknown'
        states.append(state)
    # Do not interpret provisioning/running state as positive health evidence.
    value = 'Unavailable' if 'Unhealthy' in states else ('Available' if all(s == 'Healthy' for s in states) else 'Unknown')
    return {'availabilityState': value, 'reason': 'Serving Container Apps revisions: ' + ', '.join(str(s) for s in states)}


def collect(config, client, probe_fn=probe, now=None):
    validate(config)
    start = time.monotonic()
    clock = lambda: now or datetime.now(timezone.utc)
    snapshot_time, run_id = clock().isoformat(), str(uuid.uuid4())
    issues = []
    for subscription in config['subscriptions']:
        metadata = client.get_arm('/subscriptions/' + subscription, '2022-12-01')
        if metadata.get('tenantId', '').lower() != config['tenantId'].lower():
            raise ValueError('Subscription tenant differs from configured tenant')
    resources = client.graph(query('inventory'), config['subscriptions'])
    if len({r['id'].lower() for r in resources}) != len(resources):
        raise ValueError('Inventory returned duplicate resource IDs')
    health_complete, alerts_complete = True, True
    def optional(name):
        try:
            return client.graph(query(name), config['subscriptions']), True
        except Exception:
            issues.append(name + ' query failed; coverage unknown')
            return [], False
    groups, groups_complete = optional('resource-groups')
    platform, health_complete = optional('platform-health')
    alerts, alerts_complete = optional('alerts')
    group_map = {(r['subscriptionId'].lower(), r['name'].lower()): r.get('tags', {}) for r in groups}
    resource_map = {r['id'].lower(): r for r in resources}
    serving_map = {rid: serving_revisions(resource) for rid, resource in resource_map.items()}
    platform_map = {r['resourceId'].lower(): r for r in platform if r.get('resourceId')}
    alert_map = {}
    for alert in alerts:
        rid = alert.get('targetResource', '').lower()
        if rid in resource_map:
            alert_map.setdefault(rid, []).append(alert)
        else:
            issues.append('Unattributed active alert: ' + alert.get('id', 'unknown'))
    targets, target_issues = targets_for(resources, config)
    target_map = {}
    for target in targets:
        target_map.setdefault(target['resourceId'].lower(), []).append(target)
    observations = {}
    required_checks = {}
    obsolete_checks = set()
    for source in config.get('existingEndpointQueries', []):
        allowed = {(c['resourceId'].lower(), c['checkId']) for c in source['checks']
                   if c['resourceId'].lower() in resource_map}
        for rid, check_id in allowed:
            required_checks.setdefault(rid, set()).add(check_id)
        try:
            samples = client.logs(source['workspaceResourceId'], source['query'])
            latest = {}
            for sample in samples:
                rid, check_id = sample['ResourceId'].lower(), sample['CheckId']
                key = (rid, check_id)
                if key not in allowed:
                    continue
                serving = serving_map.get(rid)
                if sample.get('Revision') and serving is not None and sample['Revision'] not in serving:
                    obsolete_checks.add(key)
                    continue
                timestamp = parse_time(sample['TimeGenerated'])
                if key not in latest or timestamp > parse_time(latest[key]['TimeGenerated']):
                    latest[key] = {**sample, 'ResourceId': rid}
            for sample in latest.values():
                observations.setdefault(sample['ResourceId'], []).append({k: v for k, v in sample.items()
                    if k in ('ResourceId', 'CheckId', 'Outcome', 'TimeGenerated', 'Reason', 'HttpStatus', 'DurationMs', 'Revision')})
        except Exception:
            issues.append('Existing endpoint telemetry query failed; application coverage unknown')
    def check(target):
        if time.monotonic()-start > config.get('maxRunSeconds', 50)-config.get('timeoutSeconds', 10):
            return {'TimeGenerated': clock().isoformat(), 'ResourceId': target['resourceId'].lower(),
                    'CheckId': target['checkId'], 'Outcome': 'unknown', 'Reason': 'Collection time budget exhausted',
                    'DurationMs': 0, 'HttpStatus': None, 'Revision': target.get('revision', '')}
        provider = lambda scope: client.credential.get_token(scope).token
        return probe_fn(target, token_provider=provider, now=now)
    with ThreadPoolExecutor(max_workers=config.get('concurrency', 10)) as pool:
        for observation in pool.map(check, targets):
            observations.setdefault(observation['ResourceId'], []).append(observation)
    # The same logical check can be supplied by multiple sources. Newest observation wins;
    # equal-time disagreements conservatively prefer fail, then unknown, then pass.
    for rid, samples in list(observations.items()):
        latest = {}
        for sample in samples:
            key = sample['CheckId']
            rank = (parse_time(sample['TimeGenerated']), {'fail': 2, 'unknown': 1, 'pass': 0}.get(sample['Outcome'], 1))
            previous = latest.get(key)
            if previous is None or rank > previous[0]:
                latest[key] = (rank, sample)
        observations[rid] = [entry[1] for entry in latest.values()]
    for rid, check_ids in required_checks.items():
        present = {s['CheckId'] for s in observations.get(rid, [])}
        for missing in check_ids - present:
            if (rid, missing) in obsolete_checks:
                continue
            observations.setdefault(rid, []).append({'ResourceId': rid, 'CheckId': missing,
                'Outcome': 'unknown', 'TimeGenerated': clock().isoformat(), 'Reason': 'Required monitor sample missing'})
    for rid, serving in serving_map.items():
        if serving and len(serving) > 1:
            covered = {s.get('Revision') for s in observations.get(rid, [])}
            for revision in serving - covered:
                observations.setdefault(rid, []).append({'ResourceId': rid, 'CheckId': 'revision-coverage:' + revision,
                    'Outcome': 'unknown', 'TimeGenerated': clock().isoformat(), 'Revision': revision,
                    'Reason': 'No application health evidence for traffic-serving revision ' + revision})
    rows = []
    shared = {'RunId': run_id, 'ProjectId': config['projectId'], 'SnapshotTime': snapshot_time}
    for resource in resources:
        rid = resource['id'].lower()
        group_tags = group_map.get((resource.get('subscriptionId', '').lower(), resource.get('resourceGroup', '').lower()))
        parent_id = {key.lower(): value.lower() for key, value in config.get('parentOverrides', {}).items()}.get(rid)
        if not parent_id:
            if resource.get('type', '').lower() == 'microsoft.app/containerapps':
                parent_id = resource.get('properties', {}).get('managedEnvironmentId')
            elif len(resource.get('type', '').split('/')) > 2:
                parent_id = rid.rsplit('/', 2)[0]
        parent_tags = resource_map.get((parent_id or '').lower(), {}).get('tags')
        attribution = attribute(resource, parent_tags, group_tags, config)
        parent_unavailable = bool(parent_id and parent_id.lower() not in resource_map)
        if (parent_unavailable and attribution['attributionSource'] not in ('resource tag', 'resource override')) or (
            not groups_complete and attribution['attributionSource'] in ('name rule', 'unassigned')):
            attribution.update(environment='', originalEnvironment='', classification='unassigned', attributionSource='unavailable higher-precedence tags')
            attribution['attributionIssues'] += '; containing resource or resource group tags unavailable'
        phealth = platform_map.get(rid)
        resource_type = resource.get('type', '').lower()
        props = resource.get('properties', {})
        power = props.get('extended', {}).get('instanceView', {}).get('powerState', {}).get('code', '').lower()
        stopped = (resource_type == 'microsoft.compute/virtualmachines' and power in ('powerstate/stopped', 'powerstate/deallocated')) or (
            resource_type == 'microsoft.web/sites' and props.get('state', '').lower() == 'stopped')
        if stopped:
            phealth = {**(phealth or {}), 'intentionalStop': True, 'reason': 'Resource is stopped; expected state policy is not configured'}
        is_app = resource.get('type', '').lower() == 'microsoft.app/containerapps'
        if not phealth and is_app and time.monotonic()-start < config.get('maxRunSeconds', 50)-10:
            try:
                phealth = container_health(resource, client)
            except Exception:
                issues.append('Container Apps revision query failed: ' + rid)
        result = evaluate(phealth, alert_map.get(rid, []), observations.get(rid, []), clock(),
                          application_required=rid in target_map or rid in target_issues or rid in required_checks or is_app,
                          freshness=config.get('freshnessSeconds', 300),
                          platform_complete=health_complete or phealth is not None,
                          alerts_complete=alerts_complete)
        if rid in target_issues:
            result['reason'] += '; ' + target_issues[rid]
            # A successfully checked container must not hide another unroutable required check.
            if result['status'] == 'green':
                result['status'] = 'grey'
            result['applicationStatus'] = 'grey' if result['applicationStatus'] != 'red' else 'red'
        samples = observations.get(rid, [])
        row = {**shared, 'RowKind': 'resource', 'TimeGenerated': clock().isoformat(), 'ResourceId': rid,
               'Name': resource.get('name', ''), 'ResourceType': resource.get('type', ''),
               'SubscriptionId': resource.get('subscriptionId', ''), 'ResourceGroup': resource.get('resourceGroup', ''),
               'Location': resource.get('location', ''),
               'Environment': attribution['environment'], 'OriginalEnvironment': attribution['originalEnvironment'],
               'Classification': attribution['classification'], 'AttributionSource': attribution['attributionSource'],
               'AttributionIssues': attribution['attributionIssues'],
               'Status': result['status'], 'PlatformStatus': result['platformStatus'],
               'ApplicationStatus': result['applicationStatus'], 'AlertStatus': result['alertStatus'],
               'Reason': result['reason'], 'AzureEvidenceAt': clock().isoformat(),
               'ApplicationEvidenceAt': result['applicationEvidenceAt'],
               'HealthComplete': health_complete and alerts_complete, 'FreshnessSeconds': config.get('freshnessSeconds', 300)}
        rows.append(row)
    for samples in observations.values():
        rows.extend({**shared, **sample, 'RowKind': 'endpoint'} for sample in samples)
    manifest = {**shared, 'RowKind': 'run', 'TimeGenerated': clock().isoformat(),
                'ExpectedCount': len(resources), 'HealthComplete': True,
                'CollectionIssues': '; '.join(sorted(set(issues)))[:16000],
                'FreshnessSeconds': config.get('freshnessSeconds', 300)}
    return rows, manifest
