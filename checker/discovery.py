"""Discover routable HTTP readiness checks, with explicit project overrides."""


def serving_revisions(resource):
    if resource.get('type', '').lower() != 'microsoft.app/containerapps':
        return None
    properties = resource.get('properties', {})
    ingress = properties.get('configuration', {}).get('ingress') or {}
    traffic = ingress.get('traffic', [])
    if traffic:
        serving = {properties.get('latestRevisionName') if t.get('latestRevision') else t.get('revisionName')
                   for t in traffic if t.get('weight', 0) > 0}
        return None if None in serving else serving
    latest = properties.get('latestReadyRevisionName') or properties.get('latestRevisionName')
    return {latest} if latest else None


def targets_for(resources, config):
    targets, issues = {}, {}
    resource_ids = {r['id'].lower() for r in resources}
    overrides = {}
    for target in config.get('endpoints', []):
        rid = target['resourceId'].lower()
        if rid in resource_ids:
            overrides.setdefault(rid, []).append(dict(target))
    for resource in resources:
        rid = resource['id'].lower()
        serving = serving_revisions(resource)
        if rid in overrides:
            for target in overrides[rid]:
                if target.get('revision') and serving is not None and target['revision'] not in serving:
                    continue
                target.setdefault('timeoutSeconds', config.get('timeoutSeconds', 10))
                targets[(rid, target['checkId'])] = target
            continue
        if resource.get('type', '').lower() != 'microsoft.app/containerapps' or not config.get('discoverReadinessProbes', True):
            continue
        properties = resource.get('properties', {})
        ingress = properties.get('configuration', {}).get('ingress') or {}
        fqdn = ingress.get('fqdn')
        for container in properties.get('template', {}).get('containers', []):
            for probe in container.get('probes', []):
                if probe.get('type', '').lower() != 'readiness' or 'httpGet' not in probe:
                    continue
                check = probe['httpGet']
                path = check.get('path', '/')
                if not fqdn or check.get('port') != ingress.get('targetPort') or not path.startswith('/') or path.startswith('//'):
                    issues[rid] = 'Readiness probe is not routable through app ingress; configure an endpoint override'
                    continue
                # Multiple revision traffic cannot establish per-revision health via the shared FQDN.
                traffic = ingress.get('traffic', [])
                if len([t for t in traffic if t.get('weight', 0) > 0]) > 1:
                    issues[rid] = 'Multiple serving revisions require explicit revision endpoint overrides'
                    continue
                if serving and properties.get('latestRevisionName') and serving != {properties['latestRevisionName']}:
                    issues[rid] = 'Serving revision differs from latest probe template; configure an endpoint override'
                    continue
                check_id = 'readiness:' + container.get('name', 'container')
                targets[(rid, check_id)] = {'resourceId': rid, 'checkId': check_id,
                                           'url': 'https://' + fqdn + path,
                                           'headers': {h['name']: h['value'] for h in check.get('httpHeaders', [])},
                                           'expectedCodes': list(range(200, 400)),
                                           'revision': next(iter(serving)) if serving and len(serving)==1 else '',
                                           'timeoutSeconds': config.get('timeoutSeconds', 10)}
    return list(targets.values()), issues
