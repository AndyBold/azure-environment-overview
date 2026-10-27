"""Combine independent signals without treating absent evidence as success."""
from datetime import datetime, timezone

PRIORITY = {'red': 0, 'amber': 1, 'grey': 2, 'green': 3, 'notApplicable': 4}


def worst(statuses):
    meaningful = [s for s in statuses if s != 'notApplicable']
    return min(meaningful, key=lambda s: PRIORITY.get(s, 2)) if meaningful else 'grey'


def parse_time(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timestamps must include UTC offset')
    return dt.astimezone(timezone.utc)


def evaluate(platform, alerts, observations, now, application_required=False, freshness=300,
             platform_complete=True, alerts_complete=True):
    reasons = []
    platform_status = {'Available': 'green', 'Unavailable': 'red', 'Degraded': 'amber'}.get(
        (platform or {}).get('availabilityState'), 'grey') if platform_complete else 'grey'
    if (platform or {}).get('intentionalStop'):
        platform_status = 'grey'
    reasons.append((platform or {}).get('reason') or ('Platform: ' + platform_status))
    alert_status = 'notApplicable'
    if not alerts_complete:
        alert_status = 'grey'
        reasons.append('Alert query incomplete')
    for alert in alerts:
        severity = str(alert.get('severity', '')).casefold()
        status = {'sev0': 'red', 'sev1': 'red', 'sev2': 'amber', 'sev3': 'amber',
                  'sev4': 'notApplicable'}.get(severity, 'grey')
        alert_status = worst([alert_status, status]) if status != 'notApplicable' else alert_status
        if status != 'notApplicable':
            reasons.append(alert.get('reason') or severity)
    application_status = 'notApplicable'
    sample_states = []
    if application_required:
        statuses = []
        for sample in observations:
            age = (now - parse_time(sample['TimeGenerated'])).total_seconds()
            status = {'pass': 'green', 'fail': 'red'}.get(sample.get('Outcome'), 'grey')
            if age > freshness or age < -60:
                status = 'grey'
                reasons.append('Application evidence stale or future-dated')
            else:
                reasons.append(sample.get('Reason', 'Application: ' + status))
            statuses.append(status)
            sample_states.append((status, sample['TimeGenerated']))
        application_status = worst(statuses)
        if not observations:
            reasons.append('Application evidence missing')
    result = worst([platform_status, alert_status, application_status])
    evidence_time = None
    if sample_states:
        if application_status == 'red':
            evidence_time = max((stamp for status, stamp in sample_states if status == 'red'), key=parse_time)
        else:
            evidence_time = min((stamp for _, stamp in sample_states), key=parse_time)
    return {'status': result, 'platformStatus': platform_status, 'alertStatus': alert_status,
            'applicationStatus': application_status, 'applicationEvidenceAt': evidence_time,
            'reason': '; '.join(reasons)[:4000]}
