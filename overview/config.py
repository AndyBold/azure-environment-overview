"""Validation shared by the collector and Workbook generator."""
import re
from urllib.parse import urlsplit


def validate(config):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', config.get('projectId', '')):
        raise ValueError('projectId must contain 1–64 letters, digits, underscores or hyphens')
    if not config.get('tenantId') or not config.get('subscriptions'):
        raise ValueError('tenantId and nonempty subscriptions are required')
    if not all(isinstance(s, str) and s for s in config['subscriptions']):
        raise ValueError('subscriptions must contain strings')
    if len(set(config['subscriptions'])) != len(config['subscriptions']):
        raise ValueError('subscriptions must be unique')
    for key, default, lo, hi in [('freshnessSeconds', 300, 60, 3600), ('concurrency', 10, 1, 50),
                                  ('timeoutSeconds', 10, 1, 20), ('maxRunSeconds', 50, 10, 50)]:
        if type(config.get(key, default)) is not int or not lo <= config.get(key, default) <= hi:
            raise ValueError('Invalid ' + key)
    for value in config.get('classificationOverrides', {}).values():
        if value not in ('production', 'nonproduction', 'shared', 'unclassified'):
            raise ValueError('Invalid classification override')
    for mapping_name in ('parentOverrides', 'resourceOverrides'):
        normalised = {}
        for key, value in config.get(mapping_name, {}).items():
            nk, nv = key.strip().casefold(), value.strip().casefold()
            if nk in normalised and normalised[nk] != nv:
                raise ValueError('Conflicting case-insensitive ' + mapping_name)
            normalised[nk] = nv
    targets = {}
    for target in config.get('endpoints', []):
        url = urlsplit(target.get('url', ''))
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Endpoints require HTTP(S) URLs without embedded credentials or fragments')
        if not target.get('resourceId', '').lower().startswith('/subscriptions/') or not target.get('checkId'):
            raise ValueError('Endpoints require ARM resourceId and checkId')
        if 'headers' in target:
            raise ValueError('Use headerEnv secret references rather than inline endpoint headers')
        key = (target['resourceId'].lower(), target['checkId'])
        if key in targets and targets[key] != target:
            raise ValueError('Conflicting duplicate endpoint check IDs')
        targets[key] = target
        codes = target.get('expectedCodes', list(range(200, 300)))
        if not codes or any(type(c) is not int or c < 100 or c > 599 for c in codes):
            raise ValueError('Invalid expectedCodes')
        if not 1 <= target.get('timeoutSeconds', config.get('timeoutSeconds', 10)) <= 20:
            raise ValueError('Endpoint timeout outside 1–20 seconds')
    for rule in config.get('namingRules', []):
        if not rule.get('token', '').strip() or not rule.get('environment', '').strip():
            raise ValueError('Naming rules require token and environment')
    for source in config.get('existingEndpointQueries', []):
        if not source.get('workspaceResourceId', '').lower().startswith('/subscriptions/') or not source.get('query') or not source.get('checks'):
            raise ValueError('Existing endpoint queries require workspaceResourceId, query and explicit required checks')
        for check in source['checks']:
            if not check.get('resourceId', '').lower().startswith('/subscriptions/') or not check.get('checkId'):
                raise ValueError('Monitor checks require resourceId and checkId')
    return config
