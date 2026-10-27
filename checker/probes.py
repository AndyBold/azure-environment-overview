"""HTTP health observations; no response bodies or credentials are persisted."""
from datetime import datetime, timezone
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from overview.azure import NoRedirect


def http_status(url, headers, timeout):
    opener = urllib.request.build_opener(NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def probe(target, transport=None, token_provider=None, now=None):
    transport = transport or http_status
    start = time.monotonic()
    code, outcome, reason = None, 'unknown', 'Check configuration error'
    try:
        parsed = urllib.parse.urlsplit(target['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid endpoint')
        headers = dict(target.get('headers', {}))
        for key, env_name in target.get('headerEnv', {}).items():
            import os
            headers[key] = os.environ[env_name]
        if target.get('tokenScope'):
            if token_provider is None:
                raise ValueError('Token provider required')
            headers['Authorization'] = 'Bearer ' + token_provider(target['tokenScope'])
        code = transport(target['url'], headers, target.get('timeoutSeconds', 10))
        expected = target.get('expectedCodes', list(range(200, 300)))
        outcome = 'pass' if code in expected else ('unknown' if code in (401, 403) else 'fail')
        reason = 'HTTP ' + str(code)
    except (socket.timeout, TimeoutError):
        outcome, reason = 'fail', 'Endpoint request timed out'
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            outcome, reason = 'fail', 'Endpoint request timed out'
        else:
            outcome, reason = 'unknown', 'Endpoint DNS, TLS or connection error'
    except Exception:
        outcome, reason = 'unknown', 'Endpoint configuration or authentication error'
    return {'TimeGenerated': (now or datetime.now(timezone.utc)).isoformat(),
            'ResourceId': target['resourceId'].lower(), 'CheckId': target['checkId'],
            'Outcome': outcome, 'HttpStatus': code, 'DurationMs': int((time.monotonic()-start)*1000),
            'Reason': reason, 'Revision': target.get('revision', '')}
