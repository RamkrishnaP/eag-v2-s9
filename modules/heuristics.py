import re
import math
from typing import List, Optional, Any

class HeuristicsEngine:
    """
    A simple heuristics engine to validate user queries and tool results.
    """

    def __init__(self):
        self.banned_words = {"badword1", "badword2", "evil", "malware"} # Placeholder list
        self.sql_injection_patterns = [
            r"(?i)DROP\s+TABLE",
            r"(?i)SELECT\s+\*\s+FROM",
            r"(?i)DELETE\s+FROM",
            r"(?i)UNION\s+SELECT",
        ]
        self.shell_injection_patterns = [
            r"(?i)rm\s+-rf",
            r"(?i)mkfs",
            r"(?i):(){:|:&};:",
        ]

    def check_query(self, query: str) -> List[str]:
        """Run heuristics on user query. Returns a list of warnings."""
        warnings = []
        if not query:
            return ["Query is empty"]

        # 1. Banned Words
        if any(word in query.lower() for word in self.banned_words):
            warnings.append("Query contains banned words")

        # 2. Length Check
        if len(query) > 1000:
            warnings.append("Query is too long (>1000 chars)")
        if len(query) < 2:
            warnings.append("Query is too short")

        # 3. Gibberish (Entropy check - simplified)
        if self._is_gibberish(query):
            warnings.append("Query appears to be gibberish")

        # 4. PII Detection (Email/Phone)
        if re.search(r"[\w\.-]+@[\w\.-]+\.\w+", query):
            warnings.append("Query contains potential Email PII")
        if re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", query):
            warnings.append("Query contains potential Phone PII")

        # 5. Code Injection
        for pattern in self.sql_injection_patterns + self.shell_injection_patterns:
            if re.search(pattern, query):
                warnings.append("Query contains potential code injection pattern")

        # 6. Language Check (ASCII ratio)
        if not self._is_mostly_ascii(query):
            warnings.append("Query contains significant non-ASCII characters")

        return warnings

    def check_result(self, result: Any) -> List[str]:
        """Run heuristics on tool result. Returns a list of warnings."""
        warnings = []
        result_str = str(result)

        # 9. Empty/Null
        if not result:
            return ["Result is empty or None"]

        # 2. Length Check (Result specific)
        if len(result_str) > 100000:
            warnings.append("Result is extremely large (>100k chars)")

        # 7. URL Safety (if result contains URLs)
        urls = re.findall(r"https?://\S+", result_str)
        for url in urls:
            if self._is_suspicious_url(url):
                warnings.append(f"Result contains suspicious URL: {url}")

        # 8. Repetition
        if self._has_excessive_repetition(result_str):
            warnings.append("Result contains excessive repetition")

        # 10. Sentiment (Negative words check - very basic)
        negative_words = {"error", "failed", "failure", "crash", "exception", "fatal"}
        if any(word in result_str.lower() for word in negative_words):
            warnings.append("Result contains negative sentiment/error keywords")

        return warnings

    def _is_gibberish(self, text: str) -> bool:
        """Check for low entropy or repeated characters."""
        if not text: return False
        # Check for repeated characters (e.g., "aaaaa")
        if re.search(r"(.)\1{9,}", text):
            return True
        return False

    def _is_mostly_ascii(self, text: str) -> bool:
        """Check if text is mostly ASCII."""
        try:
            text.encode("ascii")
            return True
        except UnicodeEncodeError:
            non_ascii = sum(1 for c in text if ord(c) > 127)
            return (non_ascii / len(text)) < 0.2 # Allow 20% non-ASCII

    def _is_suspicious_url(self, url: str) -> bool:
        """Check for suspicious URL patterns."""
        suspicious_extensions = {".exe", ".bat", ".sh", ".bin", ".dll"}
        if any(url.lower().endswith(ext) for ext in suspicious_extensions):
            return True
        if "@" in url: # Basic auth or obfuscation
            return True
        return False

    def _has_excessive_repetition(self, text: str) -> bool:
        """Check if a phrase is repeated many times."""
        # Simple check for a line repeated 10+ times
        lines = text.splitlines()
        if not lines: return False
        from collections import Counter
        counts = Counter(lines)
        if counts and counts.most_common(1)[0][1] > 10:
            return True
        return False
