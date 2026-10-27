import argparse
import json
from pathlib import Path
import uuid
from overview.config import validate

ROOT = Path(__file__).resolve().parents[1]


def status_formatter(column):
    return {'columnMatch': column, 'formatter': 18, 'formatOptions': {
        'thresholdsOptions': 'colors', 'thresholdsGrid': [
            {'operator': '==', 'thresholdValue': value, 'representation': colour, 'text': '{0}{1}'}
            for value, colour in [('red', 'redBright'), ('amber', 'yellow'), ('green', 'green'),
                                  ('grey', 'gray'), ('notApplicable', 'gray')]]}}


def build(config):
    validate(config)
    preamble = (ROOT/'queries/snapshot.kql').read_text().replace('__PROJECT__', config['projectId'])
    def text(name, content):
        return {'type': 1, 'name': name, 'content': {'json': content}}
    def parameter(name, kind, **kwargs):
        return {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'overview:' + name)), 'version': 'KqlParameterItem/1.0',
                'name': name, 'type': kind, 'isRequired': True, **kwargs}
    def dropdown(name, values):
        return parameter(name, 2, value=values[0], jsonData=json.dumps([{'value': v, 'label': v} for v in values]))
    def log_query(name, title, query, summary=False):
        item = {'type': 3, 'name': name, 'content': {'version': 'KqlItem/1.0', 'title': title,
            'query': preamble + '\n' + query, 'queryType': 0,
            'resourceType': 'microsoft.operationalinsights/workspaces',
            'crossComponentResources': ['{Workspaces}'], 'timeContext': {'durationMs': 172800000},
            'visualization': 'table', 'size': 0, 'noDataMessage': 'No rows. Check collection coverage and filters; this does not mean healthy.',
            'gridSettings': {'filter': True, 'rowLimit': 10000, 'formatters': [status_formatter(c) for c in
                ['Status', 'PlatformStatus', 'ApplicationStatus', 'AlertStatus']]}}}
        if summary:
            item['content']['exportParameterName'] = 'SelectedEnvironment'
            item['content']['exportFieldName'] = 'Environment'
            item['content']['exportDefaultValue'] = '*'
        return item
    scope = " | where SubscriptionId in~ ({Subscriptions})"
    classification = " | where Classification != 'production' or base64_decode_tostring('{Visibility:base64}') == 'all'"
    detail_filters = """
| where base64_decode_tostring('{Environment:base64}') == '*' or Environment == base64_decode_tostring('{Environment:base64}')
| where base64_decode_tostring('{SelectedEnvironment:base64}') == '*' or Environment == base64_decode_tostring('{SelectedEnvironment:base64}')
| where base64_decode_tostring('{StatusFilter:base64}') == '*' or Status == base64_decode_tostring('{StatusFilter:base64}')
| where base64_decode_tostring('{ResourceTypeFilter:base64}') == '*' or ResourceType =~ base64_decode_tostring('{ResourceTypeFilter:base64}')
"""
    fields = " | order by StatusRank asc, Name asc | project Name, ResourceType, Environment, Classification, Status, PlatformStatus, ApplicationStatus, AlertStatus, Reason, AzureEvidenceAt, ApplicationEvidenceAt, AttributionSource, AttributionIssues, ResourceId"
    params = [
        parameter('Subscriptions', 6, multiSelect=True, quote="'", delimiter=',', value=config['subscriptions']),
        parameter('Workspaces', 5, multiSelect=True, quote="'", delimiter=',', value=config.get('workspaces', []),
                  typeSettings={'resourceTypeFilter': {'microsoft.operationalinsights/workspaces': True}}),
        dropdown('Visibility', ['nonproduction', 'all']),
        parameter('SelectedEnvironment', 1, value='*', label='Selected environment (* for all)', isGlobal=True),
        parameter('Environment', 2, value='*', query=preamble+"\nunion (print value='*', label='All environments'), (resources | where isnotempty(Environment) | distinct Environment | project value=Environment, label=Environment)",
                  queryType=0, resourceType='microsoft.operationalinsights/workspaces', crossComponentResources=['{Workspaces}']),
        dropdown('StatusFilter', ['*', 'red', 'amber', 'grey', 'green']),
        parameter('ResourceTypeFilter', 2, value='*', query=preamble+"\nunion (print value='*', label='All types'), (resources | distinct ResourceType | project value=ResourceType, label=ResourceType)",
                  queryType=0, resourceType='microsoft.operationalinsights/workspaces', crossComponentResources=['{Workspaces}']),
    ]
    items = [text('intro', '# Non-production environment overview\nDiscovered resources and evidence-based health. '
        '**Grey means unknown.** Red, amber, grey and green have equal resource weighting. '
        'Production classifications are inferred: review overrides before relying on exclusions.\n\n'
        'Enable **Auto refresh → 5 minutes** each time you open this Workbook. Checks run independently every minute. '
        'Use the grid search to find a resource. Clear the environment selection by selecting All in SelectedEnvironment.'),
        {'type': 9, 'name': 'parameters', 'content': {'version': 'KqlParameterItem/1.0', 'parameters': params, 'style': 'above'}},
        log_query('coverage', 'Collection coverage — inspect before interpreting status', """
let lastPublished = toscalar(allData | summarize max(SnapshotTime));
completeRuns | top 1 by SnapshotTime desc
| project SnapshotTime, LastPublished=lastPublished, ExpectedCount, ActualCount,
    Coverage=case(SnapshotTime < lastPublished, 'PARTIAL LATEST RUN — showing previous complete snapshot',
                  datetime_diff('second', now(), SnapshotTime) > FreshnessSeconds, 'STALE — health is unknown', 'Complete inventory snapshot'),
    CollectionIssues, QueryTime=now()
"""),
        log_query('environment-summary', 'Environments — select a row to inspect resources',
            'resources'+scope+classification+" | where Classification !in ('shared', 'unassigned')\n"
            "| summarize Resources=count(), Red=countif(Status=='red'), Amber=countif(Status=='amber'), Unknown=countif(Status=='grey'), Green=countif(Status=='green'), LastSnapshot=min(SnapshotTime) by Environment, Classification\n"
            "| extend Status=case(Red>0, 'red', Amber>0, 'amber', Unknown>0, 'grey', 'green') | order by Environment asc", summary=True),
        log_query('resources', 'Environment resources', 'resources'+scope+classification+
                  " | where Classification !in ('shared', 'unassigned')"+detail_filters+fields),
        log_query('shared', 'Shared resources', 'resources'+scope+" | where Classification == 'shared'"+fields),
        log_query('unassigned', 'Unassigned resources', 'resources'+scope+" | where Classification == 'unassigned'"+fields),
        log_query('attribution-issues', 'Tagging gaps and classification review', 'resources'+scope+classification+
                  " | where isnotempty(AttributionIssues) or Classification == 'unclassified'"+fields),
        text('inventory-note', '### Direct Azure inventory\nIndependent Resource Graph visibility for the selected subscriptions. '
             'This includes production and is not the health rollup. The count is authoritative for the query scope; '
             'the list below is deliberately capped at 1,000 rows. Narrow the scope for larger estates. '
             'Azure only returns resources the querying identity can read; a successful query cannot prove full RBAC coverage.'),
        {'type': 3, 'name': 'live-inventory-count', 'content': {'version': 'KqlItem/1.0',
            'query': 'Resources | summarize VisibleResources=count() by subscriptionId', 'queryType': 1,
            'resourceType': 'microsoft.resourcegraph/resources', 'crossComponentResources': ['{Subscriptions}'], 'visualization': 'table'}},
        {'type': 3, 'name': 'live-inventory', 'content': {'version': 'KqlItem/1.0',
            'query': 'Resources | project id, name, type, resourceGroup, subscriptionId, tags | order by id asc | take 1000',
            'queryType': 1, 'resourceType': 'microsoft.resourcegraph/resources',
            'crossComponentResources': ['{Subscriptions}'], 'visualization': 'table',
            'gridSettings': {'filter': True, 'rowLimit': 1000}}},
        text('limits', 'Health is based on configured checks, not an expected deployment manifest. '
             'All discovered types appear; unsupported health sources remain unknown. Health grids display up to 10,000 rows: '
             'use filters or exported queries for larger sets. Environment summaries count the full snapshot. '
             'Snapshots are queried over the past two days; an empty result is a monitoring gap, not a healthy environment.')]
    return {'version': 'Notebook/1.0', 'items': items, 'isLocked': True,
            'defaultResourceIds': config.get('workspaces', []),
            '$schema': 'https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'dist/workbook.json')
    args = parser.parse_args()
    workbook = build(json.loads(args.config.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(workbook, indent=2)+'\n')
    print(args.output)


if __name__ == '__main__':
    main()
