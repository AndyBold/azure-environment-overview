"""Deterministic environment attribution; never equate unknown with shared."""
import re

LABELS = {
    'production': {'prod', 'production', 'prd', 'live'},
    'nonproduction': {'dev', 'development', 'test', 'testing', 'qa', 'uat', 'stage',
                      'staging', 'sandbox', 'nonprod', 'non-production', 'sit', 'integration'},
    'shared': {'shared', 'common'},
}


def normalise(value):
    return str(value).strip().casefold()


def tag_values(tags, aliases):
    return [str(v) for k, v in (tags or {}).items()
            if normalise(k) in aliases and v is not None and normalise(v)]


def classify(environment, config):
    overrides = {normalise(k): v for k, v in config.get('classificationOverrides', {}).items()}
    if environment in overrides:
        return overrides[environment]
    return next((kind for kind, values in LABELS.items() if environment in values), 'unclassified')


def attribute(resource, parent_tags=None, group_tags=None, config=None):
    config = config or {}
    aliases = {normalise(k) for k in ['Environment', 'env', *config.get('tagAliases', [])]}
    overrides = {normalise(k): v for k, v in config.get('resourceOverrides', {}).items()}
    sources = [('resource tag', resource.get('tags')), ('containing resource tag', parent_tags),
               ('resource group tag', group_tags)]
    issues, chosen, original, source = [], None, '', 'unassigned'
    override = overrides.get(normalise(resource['id']))
    if override:
        chosen, original, source = normalise(override), override, 'resource override'
    else:
        for candidate_source, tags in sources:
            values = tag_values(tags, aliases)
            distinct = {normalise(v) for v in values}
            if not distinct:
                continue
            if len(distinct) > 1:
                issues.append('conflicting environment aliases in ' + candidate_source)
                source = candidate_source + ' conflict'
                break
            chosen, original, source = next(iter(distinct)), values[0], candidate_source
            break
        else:
            matches = {normalise(rule['environment']) for rule in config.get('namingRules', [])
                       if re.search(r'(?<![a-z0-9])' + re.escape(normalise(rule['token'])) +
                                    r'(?![a-z0-9])', normalise(resource.get('name', '')))}
            if len(matches) == 1:
                chosen, source = matches.pop(), 'name rule'
                original = chosen
            elif len(matches) > 1:
                issues.append('conflicting name rules')
    if chosen:
        for candidate_source, tags in sources:
            distinct = {normalise(v) for v in tag_values(tags, aliases)}
            if distinct and distinct != {chosen}:
                issues.append(candidate_source + ' values disagree with selected environment')
    if not tag_values(resource.get('tags'), aliases):
        issues.append('missing direct environment tag')
    return {'environment': chosen or '', 'originalEnvironment': original,
            'classification': classify(chosen, config) if chosen else 'unassigned',
            'attributionSource': source, 'attributionIssues': '; '.join(issues)}
