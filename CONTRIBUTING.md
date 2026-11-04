# Contributing to Siphon

Thank you for improving the project. Bug reports that include a reproducible
URL and precise application version are especially valuable because supported
sites and CDNs can change independently of the application.

## Development setup

Use Python 3.12 or newer; release builds use Python 3.12.10. This matches the
minimum Python version supported by the pinned NumPy dependency.

```bash
git clone <your fork>
cd Siphon
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest tests -q
```

On macOS or Linux, activate the virtual environment with
`source .venv/bin/activate` and install Tk through the operating system when it
is not bundled with Python.

## Pull requests

- Keep site-specific parsing in `src/siphon/sites`.
- Put shared configuration, network and update behavior in `core`.
- Add regression tests for crawler changes and user-visible bug fixes.
- Preserve public CLI options and the saved-data format unless a documented
  major-version decision explicitly replaces them.
- Never commit API keys, cookies, proxy credentials, downloaded videos, or personally identifying logs.
- Run the full test suite before requesting review.

Windows executable releases are created only by the pinned GitHub Actions
workflow. Do not attach locally built executables to project releases.
