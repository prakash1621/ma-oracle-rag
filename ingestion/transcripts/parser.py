"""
Earnings Transcript Parser.

Parses raw transcript text into speaker-attributed chunks
suitable for RAG retrieval and contradiction detection.
"""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class TranscriptParser:
    """Parse earnings call transcripts into structured chunks."""

    # Common section headers in earnings calls
    SECTION_MARKERS = [
        "prepared remarks",
        "operator",
        "question-and-answer",
        "questions and answers",
        "q&a session",
    ]

    def parse(self, transcript: Dict) -> List[Dict]:
        """
        Parse a transcript dict into speaker-attributed chunks.

        Args:
            transcript: Dict with keys: title, date, company, text, url

        Returns:
            List of chunk dicts with text and metadata
        """
        text = transcript.get("text", "")
        company = transcript.get("company", "Unknown")
        date = transcript.get("date", "")
        title = transcript.get("title", "")
        url = transcript.get("url", "")

        if not text or len(text) < 200:
            return []

        base_metadata = {
            "source": "earnings_transcript",
            "category": "earnings_transcript",
            "company_name": company,
            "transcript_date": date,
            "transcript_title": title,
            "transcript_url": url,
        }

        # Try to split by speakers
        speaker_chunks = self._split_by_speakers(text)

        if speaker_chunks:
            chunks = []
            for sc in speaker_chunks:
                # Further chunk if too long
                sub_chunks = self._chunk_text(sc["text"], max_size=800, overlap=100)
                for i, sub in enumerate(sub_chunks):
                    chunks.append({
                        "text": sub,
                        "metadata": {
                            **base_metadata,
                            "speaker": sc["speaker"],
                            "speaker_role": sc.get("role", ""),
                            "section": sc.get("section", ""),
                            "chunk_index": i,
                        }
                    })
            return chunks

        # Fallback: simple chunking without speaker attribution
        plain_chunks = self._chunk_text(text, max_size=800, overlap=100)
        return [
            {
                "text": chunk,
                "metadata": {
                    **base_metadata,
                    "speaker": "",
                    "section": "full_transcript",
                    "chunk_index": i,
                }
            }
            for i, chunk in enumerate(plain_chunks)
        ]

    def _split_by_speakers(self, text: str) -> List[Dict]:
        """
        Split transcript text by speaker turns.

        Looks for patterns like:
        - "John Smith -- CEO"
        - "John Smith - Chief Executive Officer"
        - "[Operator]"
        """
        # Pattern: Name followed by title/role indicator
        speaker_pattern = re.compile(
            r'\n\s*([A-Z][a-zA-Z\s\.]+?)\s*[-–—]+\s*(.+?)(?:\n|$)',
            re.MULTILINE
        )

        matches = list(speaker_pattern.finditer(text))
        if len(matches) < 3:
            return []  # Not enough speaker turns to be a real transcript

        chunks = []
        section = "prepared_remarks"

        for i, match in enumerate(matches):
            speaker = match.group(1).strip()
            role = match.group(2).strip()

            # Determine section
            text_before = text[match.start():match.start() + 200].lower()
            if any(m in text_before for m in ["question", "q&a", "analyst"]):
                section = "qa_session"

            # Get text until next speaker
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            speaker_text = text[start:end].strip()

            if speaker_text and len(speaker_text) > 50:
                chunks.append({
                    "speaker": speaker,
                    "role": role,
                    "section": section,
                    "text": f"[{speaker} — {role}]\n{speaker_text}",
                })

        return chunks

    def _chunk_text(self, text: str, max_size: int = 800, overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks."""
        if len(text) <= max_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_size
            if end < len(text):
                last_period = text[start:end].rfind(". ")
                if last_period > max_size // 2:
                    end = start + last_period + 2
            chunks.append(text[start:end].strip())
            start = end - overlap

        return [c for c in chunks if c]
