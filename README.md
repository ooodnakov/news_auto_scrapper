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
Edit `main.py`:
- `INPUT_FILE` / `OUTPUT_FILE`: paths to source and generated DOCX
- `USE_LOCAL_LLM`: False to avoid sending text to an LLM; True to call a local endpoint
- `USE_PYAUTOGUI_SCREENSHOT`: True for full-window capture (needs visible browser); False for Playwright screenshots
- `USER_DATA_DIR`, `EXTENSION_PATH`, `EXTENSION_FLAGS`: optional Chromium profile/extension settings
- `MAX_TASKS`: limit for test runs; `PREVIEW_MODE`: write only a markdown preview

Place the input DOCX (with URLs) in the repo root. The parser treats the lines before a URL as metadata (source/date/snippet).

### Run
```bash
uv run main.py
```
Outputs go to `OUTPUT_FILE` plus screenshots in `temp_screenshots/`.

### Notes
- Cookie banners: scraper tries a basic “Accept/Принять” click but some sites may still show overlays.
- Telegram links: controlled by `INTERACT_WITH_TELEGRAM`; disable if you don’t want app switching.
