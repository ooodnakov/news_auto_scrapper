## News Screenshot + Text Extractor

Automates pulling links from a DOCX, visiting each page, taking a screenshot, extracting text, and writing a formatted DOCX report.

### Requirements
- Python 3.10 (matches `pyproject.toml`)
- uv package manager (`pip install uv`) and Playwright browsers (`uv run playwright install chromium`)
- Optional: local LLM endpoint (Ollama/LM Studio compatible) if `USE_LOCAL_LLM=True`
- Optional: PyAutoGUI + GUI session if you enable full-window screenshots

### Setup
```bash
uv sync
uv run playwright install chromium
```

### Configure
- Place the input DOCX (with URLs) in the repo root. The parser treats the lines before a URL as metadata (source/date/snippet).
- Configure via CLI flags or env vars (defaults are safe: headless browser, no profile, no extension, LLM off, PyAutoGUI off):
  - `--input-file` / `INPUT_FILE` (required)
  - `--output-file` / `OUTPUT_FILE` (default: `Report_Result.docx`)
  - `--use-local-llm` / `USE_LOCAL_LLM` (default: false)
  - `--pyautogui-screenshot` / `USE_PYAUTOGUI_SCREENSHOT` (default: false; sets headless false)
  - `--user-data-dir` / `USER_DATA_DIR` (optional Chromium profile; validated)
  - `--extension-path` / `EXTENSION_PATH` and `--extension-flag` / `EXTENSION_FLAGS` (optional; validated)
  - `--max-tasks` / `MAX_TASKS` (limit for test runs)
  - `--preview` / `PREVIEW_MODE` and `--preview-output` / `PREVIEW_OUTPUT`
  - LLM (off by default): `--use-local-llm` / `USE_LOCAL_LLM`, `--llm-base-url` / `LLM_BASE_URL` (defaulted to localhost when enabled), `--llm-api-key` / `LLM_API_KEY`, `--llm-timeout` / `LLM_TIMEOUT` (seconds, default 20). Enabling LLM sends extracted text snippets to your specified endpoint.

### Run
```bash
uv run main.py
```
Outputs go to `OUTPUT_FILE` plus screenshots in `temp_screenshots/`.

### Notes
- Screenshot files are cleaned at startup and named with a URL slug + hash to avoid collisions.
- Cookie banners: scraper tries a basic “Accept/Принять” click but some sites may still show overlays.
- Telegram links: controlled by `INTERACT_WITH_TELEGRAM`; disable if you don’t want app switching.
- A single browser/context is reused across URLs during a run; close happens automatically when the script exits.
