import argparse
import asyncio
import logging
import os
import shlex
import sys
from pathlib import Path

from src.parser import TaskParser
from src.scraper import WebScraper
from src.writer import ReportGenerator

# Setup Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def _str_to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in ("1", "true", "t", "yes", "y", "on"):
        return True
    if lowered in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("boolean value expected")

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return _str_to_bool(value)
    except argparse.ArgumentTypeError:
        logger.warning(f"Invalid boolean in env {name}: {value!r}; using default {default}")
        return default

def _env_int(name: str, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid integer in env {name}: {value!r}; using default {default}")
        return default

def _env_list(name: str):
    value = os.getenv(name)
    if not value:
        return []
    return shlex.split(value)

def parse_args() -> argparse.Namespace:
    env_input = os.getenv("INPUT_FILE")
    env_output = os.getenv("OUTPUT_FILE", "Report_Result.docx")

    parser = argparse.ArgumentParser(description="News screenshot + text extractor")
    parser.add_argument("--input-file", default=env_input, required=env_input is None, help="Path to input DOCX with URLs")
    parser.add_argument("--output-file", default=env_output, help="Path for generated DOCX report")
    parser.add_argument("--use-local-llm", type=_str_to_bool, default=_env_bool("USE_LOCAL_LLM", False), help="Enable local LLM filtering")
    parser.add_argument("--max-tasks", type=int, default=_env_int("MAX_TASKS"), help="Process only the first N tasks")
    parser.add_argument("--preview", dest="preview_mode", type=_str_to_bool, default=_env_bool("PREVIEW_MODE", False), help="If true, only write the markdown preview")
    parser.add_argument("--preview-output", default=os.getenv("PREVIEW_OUTPUT", "task_preview.md"), help="Path for preview markdown")
    parser.add_argument("--pyautogui-screenshot", dest="use_pyautogui", type=_str_to_bool, default=_env_bool("USE_PYAUTOGUI_SCREENSHOT", False), help="Use PyAutoGUI for full-window screenshots (requires GUI)")
    parser.add_argument("--interact-with-telegram", dest="interact_with_telegram", type=_str_to_bool, default=_env_bool("INTERACT_WITH_TELEGRAM", False), help="Follow Telegram prompts and capture app windows")
    parser.add_argument("--user-data-dir", default=os.getenv("USER_DATA_DIR"), help="Chromium user data dir to reuse")
    parser.add_argument("--extension-path", default=os.getenv("EXTENSION_PATH"), help="Path to unpacked Chromium extension")
    parser.add_argument("--extension-flag", dest="extension_flags", action="append", default=_env_list("EXTENSION_FLAGS"), help="Extra Chromium flags; can be passed multiple times")
    parser.add_argument("--headless", type=_str_to_bool, default=_env_bool("HEADLESS", True), help="Run browser headless (ignored if PyAutoGUI is enabled)")
    parser.add_argument("--llm-base-url", default=os.getenv("LLM_BASE_URL"), help="Base URL for local LLM endpoint (e.g., http://localhost:11434/v1)")
    parser.add_argument("--llm-api-key", default=os.getenv("LLM_API_KEY"), help="API key for the LLM endpoint (optional for local)")
    parser.add_argument("--llm-timeout", type=float, default=float(os.getenv("LLM_TIMEOUT", "20")), help="LLM request timeout in seconds")

    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.is_file():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    if args.user_data_dir and not Path(args.user_data_dir).exists():
        logger.warning(f"user_data_dir does not exist: {args.user_data_dir}; disabling it.")
        args.user_data_dir = None

    if args.extension_path and not Path(args.extension_path).exists():
        logger.warning(f"extension_path does not exist: {args.extension_path}; disabling it.")
        args.extension_path = None

    args.extension_flags = args.extension_flags or []

    if args.use_pyautogui and args.headless:
        logger.warning("PyAutoGUI requires a visible browser; forcing headless=False.")
        args.headless = False

    if args.use_local_llm and not args.llm_base_url:
        args.llm_base_url = "http://localhost:11434/v1"
        logger.info(f"use_local_llm enabled but no LLM base URL provided; defaulting to {args.llm_base_url}")

    return args

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
    args = parse_args()
    logger.info("🚀 Starting News Monitoring Task...")
    
    # 1. Parse Inputs
    try:
        parser = TaskParser(args.input_file)
        tasks = parser.parse()
    except Exception as e:
        logger.error(f"Error parsing input file: {e}")
        sys.exit(1)

    if not tasks:
        logger.warning("No tasks found.")
        sys.exit(0)

    # Apply testing limit if configured
    if args.max_tasks is not None:
        logger.warning(f"⚠️  TEST MODE: Processing only the first {args.max_tasks} tasks.")
        tasks = tasks[:args.max_tasks]

    if args.preview_mode:
        write_task_preview(tasks, args.preview_output)
        logger.info(f"🧾 Task preview saved to {args.preview_output}. Skipping scraping.")
        sys.exit(0)

    # 2. Scrape Data (Screenshots + Text)
    processed_tasks = []
    async with WebScraper(
        headless=args.headless,
        use_llm=args.use_local_llm,
        capture_with_pyautogui=args.use_pyautogui,
        interact_with_telegram=args.interact_with_telegram,
        user_data_dir=args.user_data_dir,
        extension_path=args.extension_path,
        extension_launch_flags=args.extension_flags,
        mask_automation=True,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        llm_timeout=args.llm_timeout,
    ) as scraper:
        # Process sequentially to avoid rate limiting or memory explosion, 
        # but scraping can be parallelized in chunks if needed.
        for i, task in enumerate(tasks):
            logger.info(f"[{i+1}/{len(tasks)}] Processing {task['source']}...")
            result = await scraper.process_url(task)
            processed_tasks.append(result)

    # 3. Generate Report
    writer = ReportGenerator(args.output_file)
    for task in processed_tasks:
        writer.add_entry(task)
    
    writer.save()
    logger.info("✨ Task Complete!")

if __name__ == "__main__":
    asyncio.run(main())
