"""AbstractAPI email reputation: retain only allowlisted assessment metadata."""
from dataclasses import dataclass
import httpx

URL = "https://emailreputation.abstractapi.com/v1/"

class AbstractUnavailable(Exception):
    pass

@dataclass(frozen=True)
class ReputationSummary:
    risk: tuple[tuple[str, str], ...] = ()
    quality: tuple[tuple[str, str], ...] = ()
    deliverability: tuple[tuple[str, str], ...] = ()
    found: int | None = None
    sources: tuple[tuple[str, str], ...] = ()

# No arbitrary API fields, email addresses, or raw breach records reach reports.
SECTIONS = {
    'email_risk': ('address_risk_status', 'domain_risk_status'),
    'email_quality': ('score', 'is_free_email', 'is_disposable_email', 'is_catchall_email',
                      'is_role_email', 'is_username_suspicious', 'is_mailbox_full'),
    'email_deliverability': ('status', 'status_detail', 'is_format_valid', 'is_smtp_valid', 'is_mx_valid'),
}

def parse_summary(data):
    if not isinstance(data, dict) or data.get('error') or not any(
            isinstance(data.get(k), dict) and data[k] for k in SECTIONS):
        raise AbstractUnavailable('invalid_response')
    groups = []
    for section, keys in SECTIONS.items():
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise AbstractUnavailable('invalid_response')
        groups.append(tuple((key, str(values[key])[:100]) for key in keys
                            if isinstance(values.get(key), (str, bool, int, float))))
    if not any(groups):
        raise AbstractUnavailable('invalid_response')
    breaches = data.get('email_breaches', {})
    if not isinstance(breaches, dict):
        raise AbstractUnavailable('invalid_response')
    count = breaches.get('total_breaches')
    count = count if type(count) is int and count >= 0 else None
    domains = breaches.get('breached_domains', [])
    sources = tuple((x[:100], '') for x in domains[:100] if isinstance(x, str)) if isinstance(domains, list) else ()
    return ReputationSummary(*groups, found=count, sources=sources)

class AbstractEmail:
    def __init__(self, api_key, transport=None):
        self._key = api_key
        self._client = httpx.AsyncClient(timeout=10, transport=transport)

    async def lookup_email(self, email):
        if not self._key:
            raise AbstractUnavailable('not_configured')
        try:
            response = await self._client.get(URL, params={'email': email},
                headers={'Authorization': f'Bearer {self._key}', 'Accept': 'application/json'})
            response.raise_for_status()
            return parse_summary(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            # Exception URLs may contain the submitted email. Never propagate them.
            raise AbstractUnavailable('request_failed') from None

    async def close(self):
        await self._client.aclose()
