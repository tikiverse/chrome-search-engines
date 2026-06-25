# chrome-search-engines

Export and import Google Chrome custom search engines from Chrome's per-profile `Web Data` SQLite database.

This is mainly useful for backing up or moving the entries shown at:

```text
chrome://settings/searchEngines
```

The command installed by this package is `cse`. A longer alias, `chrome-search-engines`, is also provided.

## Run with uvx

Export from your default Chrome profile:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse export --out chrome_search_engines.json
```

Import into your default Chrome profile:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse import --in chrome_search_engines.json
```

Import without overwriting existing keywords:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse import --in chrome_search_engines.json --mode skip
```

Pin to a branch, tag, or commit:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git@main cse export --out chrome_search_engines.json
```

## Important import note

Close Chrome before importing. Chrome can rewrite the `Web Data` database while running.

Before an import modifies the destination database, `cse` creates a timestamped backup next to it, for example:

```text
Web Data.backup-20260625-142233
```

## Specific Chrome profile

Default profile paths are usually:

```text
macOS:
~/Library/Application Support/Google/Chrome/Default/Web Data

Windows:
%LOCALAPPDATA%\Google\Chrome\User Data\Default\Web Data

Linux:
~/.config/google-chrome/Default/Web Data
```

For another profile, pass `--db` explicitly.

macOS example:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse export \
  --db "$HOME/Library/Application Support/Google/Chrome/Profile 1/Web Data" \
  --out chrome_search_engines.json
```

Windows PowerShell example:

```powershell
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse export `
  --db "$env:LOCALAPPDATA\Google\Chrome\User Data\Profile 1\Web Data" `
  --out chrome_search_engines.json
```

Linux example:

```bash
uvx --from git+https://github.com/tikiverse/chrome-search-engines.git cse export \
  --db "$HOME/.config/google-chrome/Profile 1/Web Data" \
  --out chrome_search_engines.json
```

## Local development

```bash
git clone https://github.com/tikiverse/chrome-search-engines.git
cd chrome-search-engines
uv run cse export --out chrome_search_engines.json
```

## What gets exported

The export file is JSON and includes Chrome keyword/search-engine columns such as:

- `short_name`
- `keyword`
- `url`
- suggestion URL fields, if present
- timestamps and usage metadata, if present

The import matches existing rows by `keyword`. By default, it updates existing keywords and inserts missing ones.
