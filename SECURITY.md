# Security

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Report privately via [GitHub Security Advisories](https://github.com/tuirk/LitKit/security/advisories/new) (preferred) or by opening a minimal issue asking for a private channel and tagging `@tuirk`.

We will acknowledge within a few days and work on a fix before public disclosure when possible.

## Secrets

LitKit reads optional API keys from a local `.env` file (gitignored). Never commit `.env` or paste keys into issues or project YAML.
