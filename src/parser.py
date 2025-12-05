import docx
import re
import logging
from typing import List, Dict

from docx.oxml.ns import qn

logger = logging.getLogger(__name__)

class TaskParser:
    PAGE_BREAK_MARKER = "#new page#"

    def __init__(self, filepath: str):
        self.filepath = filepath

    def parse(self) -> List[Dict]:
        """
        Parses the input DOCX file.
        Strategy: Iterate through paragraphs. When a URL is found, 
        assume the preceding lines belong to this entry (Source, Date, Title).
        """
        logger.info(f"Parsing input file: {self.filepath}")
        doc = docx.Document(self.filepath)
        tasks = []
        
        # Buffer to hold lines since the last found URL
        buffer = []
        
        # Regex to identify URLs
        url_pattern = re.compile(r'https?://[^\s]+')

        for text in self._iter_lines(doc):
            if not text:
                continue

            if text == self.PAGE_BREAK_MARKER:
                buffer = []
                continue

            # Check if this line contains a URL
            url_match = url_pattern.search(text)
            
            if url_match:
                url = url_match.group(0)
                # Clean URL: remove trailing punctuation that might have been captured
                url = url.rstrip('.,;:)("\'')
                
                source = "Unknown Source"
                date = "Unknown Date"
                snippet_lines = [line for line in buffer if line != self.PAGE_BREAK_MARKER]

                if snippet_lines:
                    source = snippet_lines[0]
                if len(snippet_lines) >= 2:
                    date = snippet_lines[1]
                body_lines = snippet_lines[2:]
                snippet = "\n".join(body_lines) if body_lines else ""
                buffer_snippet = snippet

                logger.debug(f"Found task: {source} - {url}")

                tasks.append({
                    "source": source,
                    "date": date,
                    "title": None,
                    "url": url,
                    "snippet": buffer_snippet,
                    "original_snippet": buffer_snippet
                })
                
                # Clear buffer for the next entry
                buffer = []
            else:
                buffer.append(text)

        logger.info(f"✅ Parsed {len(tasks)} tasks from {self.filepath}")
        return tasks

    def _iter_lines(self, document: docx.document.Document):
        """
        Iterate paragraphs while honoring inline page breaks so we can split long runs.
        """
        qn_t = qn('w:t')
        qn_br = qn('w:br')
        qn_type = qn('w:type')

        parts: List[str] = []

        def flush_parts():
            text = ''.join(parts)
            parts.clear()
            return text

        for paragraph in document.paragraphs:
            for run in paragraph.runs:
                for child in run._element:
                    if child.tag == qn_t:
                        parts.append(child.text or "")
                    elif child.tag == qn_br and child.get(qn_type) == "page":
                        text = flush_parts()
                        if text:
                            yield text
                        yield self.PAGE_BREAK_MARKER
            text = flush_parts()
            if text:
                yield text

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    parser = TaskParser("ЦТ_скрины_соцсети.docx")
    items = parser.parse()
    for item in items[:3]:
        print(item)
