import asyncio
import hashlib
import json
import os
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class WebScraper:
    def __init__(
        self,
        headless=True,
        use_llm=False,
        capture_with_pyautogui=False,
        interact_with_telegram=True,
        user_data_dir: Optional[str] = None,
        extension_path: Optional[str] = None,
        extension_launch_flags: Optional[List[str]] = None,
        mask_automation=True,
        llm_base_url: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_timeout: float = 20.0,
    ):
        if capture_with_pyautogui and headless:
            logger.warning("PyAutoGUI screenshots require a visible browser; switching headless to False.")
            headless = False
        if extension_path and headless:
            logger.warning("Extensions require a visible browser; switching headless to False.")
            headless = False
        self.mask_automation = mask_automation
        self.headless = headless
        self.use_llm = use_llm
        self.capture_with_pyautogui = capture_with_pyautogui
        self.interact_with_telegram = interact_with_telegram
        self.user_data_dir = user_data_dir
        self.extension_path = extension_path
        self.extension_launch_flags = extension_launch_flags or []
        self.temp_dir = Path("temp_screenshots")
        self.temp_dir.mkdir(exist_ok=True)
        self._clean_temp_dir()
        self._playwright = None
        self._browser = None
        self._context = None
        
        # Setup Local LLM client (compatible with Ollama/LM Studio)
        self.llm_client = None
        if self.use_llm and llm_base_url:
            self.llm_client = AsyncOpenAI(
                base_url=llm_base_url,
                api_key=llm_api_key or "sk-local-key",
                timeout=llm_timeout,
            )
        elif self.use_llm and not llm_base_url:
            logger.warning("use_llm is enabled but no LLM base URL provided; falling back to non-LLM extraction.")

    async def __aenter__(self):
        await self._ensure_context()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _ensure_context(self):
        """
        Lazily start Playwright and a browser context for reuse across URLs.
        """
        if self._context:
            return

        self._playwright = await async_playwright().start()
        p = self._playwright
        use_persistent = bool(self.user_data_dir)

        extension_args: List[str] = []
        if self.extension_path:
            extension_args = [
                f"--disable-extensions-except={self.extension_path}",
                f"--load-extension={self.extension_path}",
            ]

        if use_persistent:
            persistent_flags = (extension_args + self.extension_launch_flags) if extension_args else self.extension_launch_flags or []
            if self.mask_automation and "--disable-blink-features=AutomationControlled" not in persistent_flags:
                persistent_flags = persistent_flags + ["--disable-blink-features=AutomationControlled"]
            self._context = await p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                viewport={'width': 1280, 'height': 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                args=persistent_flags or None
            )
        else:
            flags = (extension_args or []) + self.extension_launch_flags
            if self.mask_automation and "--disable-blink-features=AutomationControlled" not in flags:
                flags = flags + ["--disable-blink-features=AutomationControlled"]
            self._browser = await p.chromium.launch(headless=self.headless, args=flags or None)
            self._context = await self._browser.new_context(
                viewport={'width': 1280, 'height': 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        await self._apply_automation_mask(self._context)

    async def close(self):
        """
        Closes browser/context/playwright if they were opened.
        """
        try:
            if self._context:
                await self._context.close()
        finally:
            self._context = None
        try:
            if self._browser:
                await self._browser.close()
        finally:
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def _clean_temp_dir(self):
        """
        Clear previous run artifacts to avoid disk buildup and stale screenshots.
        """
        try:
            for child in self.temp_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(f"Could not clean temp dir {self.temp_dir}: {exc}")

    def _slugify_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [parsed.netloc or "", parsed.path or ""]
        raw = "_".join(p.strip("/") for p in parts if p).strip("_")
        raw = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-") or "page"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        return f"{raw[:80]}-{digest}"

    def _screenshot_path(self, url: str, prefix: str) -> Path:
        return self.temp_dir / f"{prefix}_{self._slugify_url(url)}.png"

    async def _collect_text_blocks(self, page: Page) -> List[Dict[str, str]]:
        """
        Collects DOM blocks that resemble article sections and tags them with selectors.
        """
        script = """
        () => {
            const MIN_LENGTH = 70;
            const MAX_LENGTH = 2500;
            const blacklist = ['script', 'style', 'nav', 'footer', 'header', 'form', 'noscript'];
            const describe = (node) => {
                const parts = [];
                let current = node;
                while (current && current.nodeType === 1) {
                    let part = current.tagName.toLowerCase();
                    if (current.id) {
                        part += `#${current.id}`;
                        parts.unshift(part);
                        break;
                    }
                    const parent = current.parentElement;
                    if (!parent) {
                        parts.unshift(part);
                        break;
                    }
                    const siblings = Array.from(parent.children).filter(child => child.tagName === current.tagName);
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(current);
                        part += `:nth-of-type(${index + 1})`;
                    }
                    parts.unshift(part);
                    current = parent;
                }
                return parts.join(' > ');
            };

            const candidates = [];
            const addCandidate = (element) => {
                if (!element || !element.isConnected) return;
                if (blacklist.includes(element.tagName.toLowerCase())) return;
                const text = element.innerText || "";
                const trimmed = text.trim();
                if (trimmed.length < MIN_LENGTH || trimmed.length > MAX_LENGTH) return;
                if (candidates.some(entry => entry.element.contains(element))) return;
                const trimmedLength = trimmed.length;
                const hasHeavyChild = Array.from(element.children).some(child => {
                    if (!child || !child.isConnected) return false;
                    const childText = (child.innerText || "").trim();
                    return childText.length >= trimmedLength * 0.6;
                });
                if (hasHeavyChild) return;
                candidates.push({ element, text });
            };

            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
                acceptNode(node) {
                    if (!node || !node.isConnected) return NodeFilter.FILTER_REJECT;
                    const tag = node.tagName.toLowerCase();
                    if (blacklist.includes(tag)) return NodeFilter.FILTER_REJECT;
                    if (!node.innerText || node.innerText.trim().length < MIN_LENGTH) return NodeFilter.FILTER_SKIP;
                    return NodeFilter.FILTER_ACCEPT;
                }
            });

            while (walker.nextNode()) {
                addCandidate(walker.currentNode);
                if (candidates.length >= 50) break;
            }

            if (!candidates.length) {
                document.querySelectorAll('p').forEach(addCandidate);
            }

            const blocks = [];
            for (let i = 0; i < candidates.length && blocks.length < 30; i++) {
                const entry = candidates[i];
                blocks.push({
                    id: `block-${i + 1}`,
                    selector: describe(entry.element),
                    text: entry.text
                });
            }

            return blocks;
        }
        """
        try:
            return await page.evaluate(script)
        except Exception:
            logger.warning("Unable to collect structured text blocks from the page.")
            return []

    async def _filter_blocks_with_llm(self, blocks: List[Dict[str, str]], entry_title: str | None = None) -> List[str]:
        """
        Ask the LLM to select the most relevant blocks without rewriting the text.
        """
        if not blocks:
            return []
        if not self.llm_client:
            logger.debug("LLM client not configured; returning raw blocks.")
            return [block["text"] for block in sorted(blocks, key=lambda b: len(b.get("text", "")), reverse=True)[:5]]

        sorted_blocks = sorted(blocks, key=lambda block: len(block.get("text", "")), reverse=True)
        preview_blocks = []
        for block in sorted_blocks[:10]:
            snippet = block["text"].replace("\n", " ")
            preview_blocks.append({
                "id": block["id"],
                "selector": block["selector"],
                "snippet": snippet[:500]
            })

        block_payload = "\n\n".join(
            f'{block["id"]} | {block["selector"]}\n{block["snippet"]}'
            for block in preview_blocks
        )

        try:
            response = await self.llm_client.chat.completions.create(
                model="llama3",
                temperature=0.2,
                max_tokens=800,
                messages=[
                    {"role": "system", "content": "You are a fact-aware content editor. Given DOM blocks with selectors and snippets, tell me which ones belong to the main article body and return only JSON. Ignore unrelated nav, captions, and preview cards."},
                    {"role": "user", "content": (
                        f"Article title: {entry_title or 'unknown'}\n"
                        f"Blocks:\n{block_payload}\n\n"
                        "Respond with JSON in the format {\"selected\": [\"block-1\", ...], \"notes\": {\"block-1\": \"why\"}}. "
                        "Do not rewrite the snippets; just flag the blocks that belong to this article."
                    )}
                ]
            )

            llm_output = response.choices[0].message.content.strip()
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start == -1 or end == -1:
                raise json.JSONDecodeError("No JSON object found", llm_output, 0)
            parsed = json.loads(llm_output[start:end + 1])
        except Exception as exc:
            logger.error(f"⚠️ LLM block filter failed: {exc}. Using raw block candidates.")
            return [block["text"] for block in sorted_blocks[:5]]

        selected_ids = []
        for key in ("selected", "keep", "blocks"):
            value = parsed.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        selected_ids.append(item)
                    elif isinstance(item, dict) and "id" in item:
                        selected_ids.append(item["id"])
                if selected_ids:
                    break

        selected_ids = set(selected_ids)
        filtered = [block["text"] for block in blocks if block["id"] in selected_ids]
        if not filtered:
            filtered = [block["text"] for block in sorted_blocks[:5]]

        return filtered

    def _activate_browser_window(self, pyautogui, title: Optional[str]):
        if not title:
            return None

        try:
            windows = pyautogui.getWindowsWithTitle(title)
            if not windows:
                return None
            window = windows[0]
            window.activate()
            window.moveTo(0, 0)
            return window
        except Exception as exc:
            logger.debug(f"Could not manipulate browser window: {exc}")
            return None

    def _capture_screen_with_pyautogui(self, path: str, page_title: Optional[str]) -> bool:
        try:
            import pyautogui
        except ImportError:
            logger.error("PyAutoGUI is not installed; cannot capture full browser window.")
            return self._capture_with_imagegrab(path)

        try:
            window = self._activate_browser_window(pyautogui, page_title)
            time.sleep(1)
            if window:
                region = (
                    window.left,
                    window.top,
                    window.width,
                    window.height
                )
                pyautogui.screenshot(path, region=region)
            else:
                pyautogui.screenshot(path)
            return True
        except Exception as exc:
            logger.error(f"PyAutoGUI capture failed: {exc}")
            return self._capture_with_imagegrab(path)

    def _capture_with_imagegrab(self, path: str) -> bool:
        try:
            from PIL import ImageGrab
        except ImportError:
            logger.error("Pillow is required for ImageGrab fallback; install `Pillow` or enable PyAutoGUI.")
            return False

        try:
            screenshot = ImageGrab.grab()
            screenshot.save(path)
            return True
        except Exception as exc:
            logger.error(f"ImageGrab capture failed: {exc}")
            return False

    async def _dismiss_telegram_prompt(self, page: Page):
        """
        Hides overlays that try to open Telegram or other external apps.
        """
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        script = """
        () => {
            const keywords = ['open telegram', 'open in app', 'telegram app', 'download telegram', 'launch telegram', 'view in channel'];
            const elements = document.querySelectorAll('button, a, div, span');
            elements.forEach(el => {
                const text = (el.innerText || '').toLowerCase();
                if (!text) return;
                if (keywords.some(keyword => text.includes(keyword))) {
                    const container = el.closest('div[role="dialog"], div[class*="modal"], div[class*="popup"], section, article') || el;
                    container.style.display = 'none';
                }
            });
        }
        """
        try:
            await page.evaluate(script)
        except Exception as exc:
            logger.debug(f"Could not dismiss Telegram prompt: {exc}")

    async def _click_open_in_telegram(self, page: Page) -> bool:
        """
        Clicks the 'Open in Telegram' prompt if present.
        """
        script = """
        () => {
            const keywords = ['open in telegram', 'open telegram', 'launch telegram', 'use telegram app', 'view in channel'];
            const elements = document.querySelectorAll('button, a');
            const isTelegramHref = (href) => {
                if (!href) return false;
                const lower = href.toLowerCase();
                return lower.startsWith('tg:') || lower.includes('t.me');
            };

            for (const el of elements) {
                const text = (el.innerText || '').toLowerCase();
                const href = el.getAttribute('href') || '';
                if (keywords.some(keyword => text.includes(keyword)) || isTelegramHref(href)) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
        """
        try:
            return await page.evaluate(script)
        except Exception as exc:
            logger.debug(f"Could not trigger Telegram link: {exc}")
            return False

    def _capture_telegram_app_window(self, path: str) -> bool:
        try:
            import pyautogui
        except ImportError:
            logger.error("PyAutoGUI is required for Telegram app capture.")
            return False

        windows = pyautogui.getWindowsWithTitle("Telegram")
        if not windows:
            logger.warning("No Telegram window detected for capture.")
            return False

        window = windows[0]
        try:
            region = (
                window.left,
                window.top,
                window.width,
                window.height
            )
            pyautogui.screenshot(path, region=region)
            return True
        except Exception as exc:
            logger.error(f"Telegram window capture failed: {exc}")
            return False

    async def _apply_automation_mask(self, context):
        if not self.mask_automation:
            return
        script = """
        () => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
            window.navigator.permissions.query = (parameters) => {
                if (parameters.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission });
                }
                return window.navigator.permissions.__proto__.query.call(navigator.permissions, parameters);
            };
        }
        """
        try:
            await context.add_init_script(script)
        except Exception as exc:
            logger.debug(f"Unable to inject automation mask script: {exc}")

    async def _hide_automation_banner(self, page: Page):
        script = """
        () => {
            const selector = '#automationBanner, .automation-popup, .browser-under-control';
            const styles = [
                'body::before',
                '#automationBanner',
            ];
            styles.forEach(sel => {
                const element = document.querySelector(sel);
                if (element) {
                    element.style.display = 'none';
                }
            });
            const hideBanner = () => {
                document.querySelectorAll('div, span, p').forEach(el => {
                    const text = (el.innerText || '').toLowerCase();
                    if (text.includes('automated test software') || text.includes('контролируется программным обеспечением')) {
                        el.style.display = 'none';
                        if (el.parentElement) el.parentElement.style.display = 'none';
                    }
                });
            };
            hideBanner();
            new MutationObserver(hideBanner).observe(document.body, { childList: true, subtree: true });
        }
        """
        try:
            await page.evaluate(script)
        except Exception as exc:
            logger.debug(f"Unable to hide automation banner: {exc}")

    async def _mask_screenshot_area(self, path: str):
        if not self.mask_automation:
            return
        try:
            from PIL import Image, ImageDraw
            image = Image.open(path)
            draw = ImageDraw.Draw(image)
            height = 85+min(45, image.height)
            draw.rectangle([(6, 85), (image.width-11, height)], fill=(53, 54, 58))
            image.save(path)
        except ImportError:
            logger.warning("Pillow not available for masking screenshot area.")
        except Exception as exc:
            logger.debug(f"Failed to mask screenshot area: {exc}")

    async def process_url(self, entry: Dict) -> Dict:
        """
        Takes a task entry, visits URL, takes screenshot, extracts text.
        """
        url = entry['url']
        screenshot_path = os.path.join(self.temp_dir, f"screen_{hash(url)}.png")
        extracted_text = ""
        
        logger.info(f"🌍 Processing: {url}")

        async with async_playwright() as p:
            logger.debug("Launching browser...")
            browser = None
            context = None
            page = None
            use_persistent = bool(self.user_data_dir)

            extension_args = []
            if self.extension_path:
                extension_args = [
                    f"--disable-extensions-except={self.extension_path}",
                    f"--load-extension={self.extension_path}",
                ]

            if use_persistent and self.user_data_dir:
                persistent_flags = (extension_args + self.extension_launch_flags) if extension_args else self.extension_launch_flags or []
                if self.mask_automation and "--disable-blink-features=AutomationControlled" not in persistent_flags:
                    persistent_flags = persistent_flags + ["--disable-blink-features=AutomationControlled"]
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    headless=self.headless,
                    viewport={'width': 1280, 'height': 1024},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    args=persistent_flags or None
                )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                flags = (extension_args or []) + self.extension_launch_flags
                if self.mask_automation and "--disable-blink-features=AutomationControlled" not in flags:
                    flags = flags + ["--disable-blink-features=AutomationControlled"]
                browser = await p.chromium.launch(headless=self.headless, args=flags or None)
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 1024},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

            await self._apply_automation_mask(context)

            page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
            
            try:
                # Go to page
                logger.debug(f"Navigating to {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000) # Slight wait for dynamic content (VK/Dzen)

                # --- Attempt to cleanup cookie banners (Simple heuristic) ---
                try:
                    logger.debug("Attempting to close cookie banners...")
                    await page.evaluate("""() => {
                        const buttons = Array.from(document.querySelectorAll('button, a'));
                        const acceptBtn = buttons.find(b => b.innerText.toLowerCase().includes('accept') || b.innerText.toLowerCase().includes('принять'));
                        if (acceptBtn) acceptBtn.click();
                    }""")
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    pass

                if self.interact_with_telegram:
                    await self._dismiss_telegram_prompt(page)
                telegram_prompt_opened = False
                if self.capture_with_pyautogui and self.interact_with_telegram:
                    telegram_prompt_opened = await self._click_open_in_telegram(page)
                    if telegram_prompt_opened:
                        await page.wait_for_timeout(1500)

                # --- Screenshot ---
                # We take a screenshot of the visible viewport (top of page with title/link)
                logger.debug(f"Taking screenshot: {screenshot_path}")
                await self._hide_automation_banner(page)
                if self.capture_with_pyautogui:
                    page_title = await page.title()
                    if not self._capture_screen_with_pyautogui(screenshot_path, page_title):
                        logger.debug("PyAutoGUI capture failed; falling back to Playwright viewport screenshot.")
                        await page.screenshot(path=screenshot_path, full_page=False)
                else:
                    await page.screenshot(path=screenshot_path, full_page=False)
                await self._mask_screenshot_area(screenshot_path)

                if self.capture_with_pyautogui and telegram_prompt_opened and self.interact_with_telegram:
                    telegram_screenshot_path = os.path.join(self.temp_dir, f"telegram_{hash(url)}.png")
                    if self._capture_telegram_app_window(telegram_screenshot_path):
                        entry['telegram_screenshot_path'] = telegram_screenshot_path

                # --- Text Extraction ---
                logger.debug("Extracting structured text blocks...")
                text_blocks = await self._collect_text_blocks(page)

                if text_blocks:
                    if self.use_llm:
                        logger.debug("Filtering blocks through the LLM...")
                        filtered_blocks = await self._filter_blocks_with_llm(text_blocks, entry.get("title"))
                    else:
                        filtered_blocks = [block['text'] for block in text_blocks]

                    extracted_text = "\n\n".join(block for block in filtered_blocks if block)
                    entry['text_blocks'] = filtered_blocks
                else:
                    logger.debug("Falling back to raw HTML text extraction.")
                    content_html = await page.content()
                    soup = BeautifulSoup(content_html, 'html.parser')
                    
                    for script in soup(["script", "style", "nav", "footer"]):
                        script.extract()

                    raw_text = soup.get_text(separator='\n')
                    lines = (line.strip() for line in raw_text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    extracted_text = '\n'.join(chunk for chunk in chunks if chunk)
                    entry['text_blocks'] = [raw_text]
                
                entry['screenshot_path'] = screenshot_path
                entry['full_text'] = extracted_text
                entry['status'] = 'success'
                logger.info(f"Successfully processed {url}")

            except Exception as e:
                logger.error(f"❌ Error scraping {url}: {e}")
                entry['status'] = 'failed'
                entry['error'] = str(e)
            
            finally:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
        
        return entry
