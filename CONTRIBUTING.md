# Contributing to DeepThinkTrader

Thanks for your interest in contributing! This document covers the basics.

## Getting Started

1. Fork the repo and clone your fork
2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.template` to `.env` and add your API keys
4. Run a single cycle to verify setup: `python main.py once`

## Making Changes

1. Create a branch from `main`: `git checkout -b feature/your-feature`
2. Make your changes
3. Test your changes with paper trading (never commit live trading config)
4. Commit with a descriptive message using conventional commits:
   - `feat: add VIX sentiment edge`
   - `fix: trailing stop not triggering on gap down`
   - `refactor: simplify risk manager checks`
5. Push and open a pull request

## What We're Looking For

Check the GitHub Issues for `good first issue` and `help wanted` labels. High-impact areas:

- **New edges** — Additional data sources for the multi-edge validation (VIX, breadth, options flow)
- **Risk improvements** — Better position sizing, new exit strategies, drawdown recovery
- **Dashboard enhancements** — New visualizations, trade detail views, performance analytics
- **Documentation** — Tutorials, architecture diagrams, configuration guides
- **Bug fixes** — Especially around order management and exit monitoring

## Code Style

- Python 3.10+
- Use type hints for function signatures
- Keep functions focused — one responsibility per function
- Add docstrings to public methods
- Follow existing patterns in the codebase

## Important Rules

- **Never commit API keys, secrets, or personal data**
- **Never commit `.env` files** — use `.env.template` for new variables
- **Paper trading only** — all PRs should default to paper trading mode
- **Risk disclaimers** — any user-facing text about performance must include appropriate disclaimers
- **Test with paper trading** before submitting PRs that touch execution logic

## Reporting Issues

- Use the GitHub Issue templates (bug report or feature request)
- Include relevant logs (redact any API keys or personal data)
- For bugs: include your Python version, OS, and steps to reproduce

## Questions?

Open a Discussion on GitHub — we're happy to help.
