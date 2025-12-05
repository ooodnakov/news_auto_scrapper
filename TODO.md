## TODO

- [x] Configuration: move INPUT_FILE/OUTPUT_FILE, user data dir, extension paths, and flags to a config/env/CLI layer with validation and safe defaults (headless, no extension, no profile).
- [x] LLM safety: make LLM use opt-in; expose base URL/key via env; add short timeouts and fallback to non-LLM extraction; document privacy implications.
- [x] Browser reuse: reuse a single Playwright browser/context (or small pool) across URLs; avoid per-URL launch/teardown and repeated extension loading.
- [x] Screenshots cleanup: generate stable screenshot names (uuid or url-safe slug) and clear/rotate `temp_screenshots` each run to prevent buildup and collisions.
- Headless defaults: default to Playwright screenshots; gate PyAutoGUI mode behind an explicit flag for GUI environments.
- Parser robustness: add parsing rules/tests that handle blank lines, multiple URLs, hyperlink runs, and clearer metadata markers instead of assuming two lines above a URL.
