# Security & Privacy

## What stays local (gitignored)

These files contain real financial / personal data and are never committed:

- `.env` - All API keys (Finnhub, Twelve Data, Alpha Vantage, NewsAPI)
- `positions.json` - Live portfolio: account numbers, share counts, avg costs, stops, cash balances
- `portfolio_history.json` - Daily portfolio value history
- `trades_log.json` - Realized P&L by trade
- `tracker.html` - Generated dashboard with live numbers
- `scan_results.json` - Periodic market scan output
- `.claude/` - Local Claude Code config

See `.gitignore` for the full list.

## What's in source code

Only generic strategy and rule references:
- Position type definitions (S, L, I, Lifetime, Spec)
- Sector limits (counts, not values)
- Macro thesis text
- Algorithm formulas

No account numbers, no balances, no API keys, no PII.

## Repo visibility

This repo is **private**. The exposure surface is limited to GitHub auth.

## If making the repo public in the future

Old commits in this repo's history contain account numbers (added before this scrub). Before going public:

```bash
# Install BFG or git-filter-repo
brew install git-filter-repo

# Build a replacements file: SECRET==>REDACTED, one per line
cat > /tmp/scrub.txt <<'EOF'
your-account-number-1==>REDACTED
your-account-number-2==>REDACTED
old-email@example.com==>EMAIL_REDACTED
EOF

# Run filter-repo on both file content and commit messages
git filter-repo --replace-text /tmp/scrub.txt --replace-message /tmp/scrub.txt --force

# filter-repo strips the origin remote - re-add it
git remote add origin https://github.com/USER/REPO.git

# Force-push (rewrites history - coordinate if collaborators)
git push origin --force --all
git push origin --force --tags
```

Verify after with: `git log --all -p | grep -F "<your-account-number>"` - should return nothing.

## API key rotation

If any key is ever exposed:
1. Revoke at provider dashboard immediately
2. Generate new key
3. Update `.env`
4. Restart `morning_run.py` / dev servers

Provider dashboards:
- Finnhub: finnhub.io/dashboard
- Twelve Data: twelvedata.com/account/api-keys
- Alpha Vantage: alphavantage.co (need to email support to rotate)
- NewsAPI: newsapi.org/account
