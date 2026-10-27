"""One-shot collection entrypoint; deliberately no Azure deployment operations."""
import argparse
import json
import os
import signal
import sys
from pathlib import Path

from overview.azure import AzureClient
from overview.config import validate
from checker.collector import collect
from checker.lease import Busy, exclusive


def execute(config, client):
    try:
        rows, manifest = collect(config, client)
        client.ingest(rows, config.get('ingestion', {}))
        # A run is usable only after all resource rows are accepted.
        client.ingest([manifest], config.get('ingestion', {}))
        return 0
    except Exception as exc:
        # Do not emit URLs, request bodies, authentication details or exception strings.
        print(json.dumps({'event': 'collection_failed', 'errorType': type(exc).__name__}), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Collect and print results without ingestion; still queries Azure')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text() if args.config else os.environ['PROJECT_CONFIG_JSON'])
        validate(config)
        config['ingestion'] = {key: os.getenv(env, config.get('ingestion', {}).get(key, '')) for key, env in
                                [('endpoint', 'INGESTION_ENDPOINT'), ('ruleId', 'DCR_IMMUTABLE_ID')]}
        config['ingestion']['stream'] = 'Custom-EnvironmentOverview'
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        client = AzureClient(credential=credential)
        if args.dry_run:
            rows, manifest = collect(config, client)
            print(json.dumps({'manifest': manifest, 'rows': rows}, indent=2))
            return 0
        # Terminate the process (including worker threads) before its 60-second lease expires.
        # os._exit is intentional: no late ingestion is permitted after another run starts.
        signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
        signal.alarm(55)
        from azure.storage.blob import BlobClient
        blob = BlobClient.from_blob_url(os.environ['LEASE_BLOB_URL'], credential=credential,
                                       connection_timeout=5, read_timeout=5, retry_total=1)
        with exclusive(blob):
            return execute(config, client)
    except Busy:
        print(json.dumps({'event': 'collection_skipped', 'reason': 'lease held'}))
        return 0
    except Exception as exc:
        print(json.dumps({'event': 'startup_failed', 'errorType': type(exc).__name__}), file=sys.stderr)
        return 1
    finally:
        if hasattr(signal, 'alarm'):
            signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
