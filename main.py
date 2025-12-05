import asyncio
import logging
import sys
from pathlib import Path

from src.parser import TaskParser
from src.scraper import WebScraper
from src.writer import ReportGenerator

# CONFIG
INPUT_FILE = "Восход_скрины_СМИ.docx"
OUTPUT_FILE = "Восход_скрины_СМИ_рез.docx"
USE_LOCAL_LLM = True  # Set to True if you have Ollama running
MAX_TASKS =  None  # Set to an integer (e.g., 3) for testing, or None to process all
PREVIEW_MODE = False  # Set to True to only generate a Markdown preview of parsed tasks
PREVIEW_OUTPUT = "task_preview.md"
USE_PYAUTOGUI_SCREENSHOT = True  # Requires non-headless browser and PyAutoGUI
INTERACT_WITH_TELEGRAM = False  # Set to False to skip Telegram handling
USER_DATA_DIR = r"C:\Users\user\AppData\Local\Chromium\User Data\Default"
EXTENSION_PATH = r"C:\Users\user\Downloads\uBlock0_1.68.0.chromium\uBlock0.chromium" #r"C:/Users/user/Downloads/uBOLite_2025.1130.1739.chromium" #
EXTENSION_FLAGS = None #["--allow-legacy-mv2-extensions",]

# Setup Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def write_task_preview(tasks, destination: str):
    """
    Saves a lightweight Markdown preview summarizing each parsed task so
    you can review the list before scraping.
    """
    if not tasks:
        return

    lines = ["# Task Preview", ""]
    for index, task in enumerate(tasks, start=1):
        title = task.get("title", "Untitled")
        source = task.get("source", "Unknown Source")
        date = task.get("date", "Unknown Date")
        url = task.get("url", "No URL")
        snippet = task.get("original_snippet", "").strip()

        lines.extend([
            f"## {index}. {title}",
            f"- **Date:** {date}",
            f"- **Source:** {source}",
        ])
        if snippet:
            lines.append(f"- **Snippet:** {snippet}")
        lines.append(f"- **URL:** {url}")
        lines.append("")

    Path(destination).write_text("\n".join(lines), encoding="utf-8")

async def main():
    logger.info("🚀 Starting News Monitoring Task...")
    
    # 1. Parse Inputs
    try:
        parser = TaskParser(INPUT_FILE)
        tasks = parser.parse()
    except Exception as e:
        logger.error(f"Error parsing input file: {e}")
        sys.exit(1)

    if not tasks:
        logger.warning("No tasks found.")
        sys.exit(0)

    # Apply testing limit if configured
    if MAX_TASKS is not None:
        logger.warning(f"⚠️  TEST MODE: Processing only the first {MAX_TASKS} tasks.")
        tasks = tasks[:MAX_TASKS]

    if PREVIEW_MODE:
        write_task_preview(tasks, PREVIEW_OUTPUT)
        logger.info(f"🧾 Task preview saved to {PREVIEW_OUTPUT}. Skipping scraping.")
        sys.exit(0)

    # 2. Scrape Data (Screenshots + Text)
    scraper = WebScraper(
        headless=not USE_PYAUTOGUI_SCREENSHOT,
        use_llm=USE_LOCAL_LLM,
        capture_with_pyautogui=USE_PYAUTOGUI_SCREENSHOT,
        interact_with_telegram=INTERACT_WITH_TELEGRAM,
        user_data_dir=USER_DATA_DIR,
        extension_path=EXTENSION_PATH,
        extension_launch_flags=EXTENSION_FLAGS,
        mask_automation=True,
    )
    processed_tasks = []

    # Process sequentially to avoid rate limiting or memory explosion, 
    # but scraping can be parallelized in chunks if needed.
    for i, task in enumerate(tasks):
        logger.info(f"[{i+1}/{len(tasks)}] Processing {task['source']}...")
        result = await scraper.process_url(task)
        processed_tasks.append(result)

    # 3. Generate Report
    writer = ReportGenerator(OUTPUT_FILE)
    for task in processed_tasks:
        writer.add_entry(task)
    
    writer.save()
    logger.info("✨ Task Complete!")

if __name__ == "__main__":
    asyncio.run(main())
