# Code Review Standards

**Trigger:** after writing/modifying code, before commits, security-sensitive changes, architectural changes
**Why:** catch bugs and security issues before they reach production

## Enforced by

- `enforce-review.py` (PreToolUse Bash git commit) — blocks commit without code-reviewer/security-reviewer

## When to review

- After writing or modifying code → **code-reviewer** agent
- Security-sensitive code (auth, payments, user data, DB queries) → **security-reviewer** agent
- Before merging PRs

## Severity levels

| Level | Action |
|-------|--------|
| CRITICAL | **BLOCK** — must fix |
| HIGH | **WARN** — should fix |
| MEDIUM | **INFO** — consider |
| LOW | **NOTE** — optional |

## Agents

| Agent | Purpose |
|-------|---------|
| **code-reviewer** | General quality, patterns |
| **security-reviewer** | OWASP Top 10, vulnerabilities |
| **python-reviewer** | Python-specific |
