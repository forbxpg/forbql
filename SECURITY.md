# Security policy

forbql stands between AI agents and databases, so a bypass is the most serious bug it
can have. Thank you for reporting one privately.

## Reporting

Report through GitHub: **Security → Report a vulnerability** on this repository. Do not
open a public issue, discussion or pull request for a bypass.

Please include the engine and its version, the forbql version or commit, the policy and
the query, and what the agent could do that the policy should have stopped.

## What counts

- A query the firewall allows that writes, locks, reads a hidden table or column, reads a
  PII column outside its class, or escapes the row, byte or time limits.
- A way to run SQL other than the SQL the firewall checked.
- A way to alter the audit log without detection.
- Anything else that breaks a promise listed in the README.

Prompt injection through data is a known limit, not a vulnerability; the threat model
explains why.

## What happens next

We confirm receipt within 7 days and agree on a fix and a date. Disclosure is coordinated
and happens at the latest 90 days after the report, or earlier once a fixed release is
out. Reporters are credited in the advisory unless they ask otherwise.

## Supported versions

Until 1.0 only the latest release receives security fixes.
