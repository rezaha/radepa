# Email reputation integration

Set `ABSTRACT_API_KEY` securely in environment settings. No key is stored in the
repository. Requests use GET https://emailreputation.abstractapi.com/v1/ with only
`email` in the query and `Authorization: Bearer <key>` in the header.
Allow HTTPS egress to `emailreputation.abstractapi.com` in addition to LeakCheck.
Missing configuration or a provider outage keeps the other provider's result.

The parser retains allowlisted metadata from `email_risk`, `email_quality`,
`email_deliverability`, and `email_breaches` (`total_breaches`, `breached_domains`).
Unrecognized or malformed assessments count as unavailable, never as a clean
result. Raw records are discarded. Counts stay provider-specific and are not
summed. Source names are deduplicated by whitespace normalization and casefolding;
provider attribution and distinct reported dates are retained. This name matching
does not establish that differently named breaches are distinct incidents.

One email credit reservation covers both providers. A successfully delivered
report from either provider completes that single reservation, including zero
results. Total provider failure, cancellation, or Telegram delivery failure refunds
it, using the existing idempotent credit transaction logic.

Run from this directory:

```bash
/workspace/.venvs/radepa/bin/python -m unittest discover -s tests -v
```

Tests use synthetic payloads and mocked HTTP. Live AbstractAPI access and its
response schema have not been verified: the onboarding proxy denied access and
no key was configured. Validate against the account's actual response before
production rollout. No deployment or polling startup is performed by these tests.
