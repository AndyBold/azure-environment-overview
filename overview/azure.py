"""Azure REST boundary with explicit pagination and bounded retries."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

ARM = 'https://management.azure.com'


class CoverageError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AzureClient:
    def __init__(self, transport=None, credential=None):
        self.transport = transport or self._request
        self.credential = credential

    def _request(self, method, url, payload, scope):
        if self.credential is None:
            from azure.identity import DefaultAzureCredential
            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        token = self.credential.get_token(scope).token
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method,
                                         headers={'Authorization': 'Bearer ' + token,
                                                  'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(request, timeout=10) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f'Azure request failed: HTTP {exc.code}') from None
                time.sleep(min(2 ** attempt, 4))

    def graph(self, query, subscriptions):
        rows, token, seen = [], None, set()
        while True:
            options = {'$top': 1000, 'resultFormat': 'objectArray', 'allowPartialScopes': False}
            if token:
                options['$skipToken'] = token
            result = self.transport('POST', ARM + '/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01',
                                    {'query': query, 'subscriptions': subscriptions, 'options': options}, ARM + '/.default')
            if result.get('error'):
                raise CoverageError('Resource Graph returned an error')
            rows.extend(result.get('data', []))
            token = result.get('$skipToken')
            truncated = str(result.get('resultTruncated', 'false')).lower() == 'true'
            if not token:
                if truncated:
                    raise CoverageError('Resource Graph truncated data without a continuation token')
                return rows
            if token in seen:
                raise CoverageError('Resource Graph repeated a continuation token')
            seen.add(token)

    def list_arm(self, resource_id, api_version):
        url = ARM + resource_id + '?api-version=' + api_version
        rows, seen = [], set()
        while url:
            if not url.startswith(ARM + '/') or url in seen:
                raise CoverageError('Invalid ARM pagination URL')
            seen.add(url)
            page = self.transport('GET', url, None, ARM + '/.default')
            rows.extend(page.get('value', []))
            url = page.get('nextLink')
        return rows

    def get_arm(self, resource_id, api_version):
        return self.transport('GET', ARM + resource_id + '?api-version=' + api_version, None, ARM + '/.default')

    def logs(self, workspace_id, query):
        workspace = self.get_arm(workspace_id, '2023-09-01')
        customer_id = workspace['properties']['customerId']
        result = self.transport('POST', 'https://api.loganalytics.azure.com/v1/workspaces/' +
                                urllib.parse.quote(customer_id, safe='') + '/query',
                                {'query': query, 'timespan': 'PT1H'}, 'https://api.loganalytics.io/.default')
        if result.get('error') or len(result.get('tables', [])) != 1:
            raise CoverageError('Log Analytics query failed or returned partial/multiple results')
        table = result['tables'][0]
        columns = [c['name'] for c in table['columns']]
        return [dict(zip(columns, row, strict=True)) for row in table['rows']]

    def ingest(self, rows, config, max_bytes=900_000):
        url = config['endpoint'].rstrip('/') + '/dataCollectionRules/' + urllib.parse.quote(config['ruleId'], safe='')
        url += '/streams/' + urllib.parse.quote(config['stream'], safe='') + '?api-version=2023-01-01'
        batch, size = [], 2
        for row in rows:
            length = len(json.dumps(row).encode()) + 2
            if length > max_bytes:
                raise ValueError('Observation exceeds ingestion batch size')
            if batch and size + length > max_bytes:
                self.transport('POST', url, batch, 'https://monitor.azure.com/.default')
                batch, size = [], 2
            batch.append(row)
            size += length
        if batch:
            self.transport('POST', url, batch, 'https://monitor.azure.com/.default')
