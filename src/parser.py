import docx
import re
import logging
from typing import List, Dict, Tuple

from docx.oxml.ns import qn
from docx.oxml.shared import qn as shared_qn

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

    def _iter_lines(self, document: docx.document.Document) -> Tuple[str, List[str]]:
        """
        Iterate paragraphs while honoring inline page breaks so we can split long runs.
        Returns tuples of (text, hyperlink_targets) so we don't miss URLs embedded as hyperlinks.
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
            hyperlink_targets = self._extract_hyperlinks(paragraph)
            for run in paragraph.runs:
                for child in run._element:
                    if child.tag == qn_t:
                        parts.append(child.text or "")
                    elif child.tag == qn_br and child.get(qn_type) == "page":
                        text = flush_parts()
                        if text:
                            yield text, []
                        yield self.PAGE_BREAK_MARKER, []
            text = flush_parts()
            if text:
                yield text, hyperlink_targets

    def _extract_hyperlinks(self, paragraph) -> List[str]:
        """
        Collect external hyperlinks from a paragraph so we capture URLs even if
        the visible text is not the raw link.
        """
        urls: List[str] = []
        try:
            hyperlink_elements = paragraph._p.xpath(".//w:hyperlink[@r:id]")
            rel_ids = {el.get(shared_qn("r:id")) for el in hyperlink_elements if el.get(shared_qn("r:id"))}
            for rel_id in rel_ids:
                rel = paragraph.part.rels.get(rel_id)
                if rel and rel.target_ref:
                    urls.append(rel.target_ref)
        except Exception as exc:
            logger.debug(f"Failed to extract hyperlinks from paragraph: {exc}")
        return urls

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    parser = TaskParser("ЦТ_скрины_соцсети.docx")
    items = parser.parse()
    for item in items[:3]:
        print(item)
