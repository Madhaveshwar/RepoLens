import logging
import sys
import re

class SecretsMaskingFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)
        # Match standard PATs, API keys, and authorization headers
        self.patterns = [
            (re.compile(r'github_pat_[a-zA-Z0-9_]{30,200}'), 'github_pat_***[MASKED]***'),
            (re.compile(r'gsk_[a-zA-Z0-9_]{30,200}'), 'gsk_***[MASKED]***'),
            (re.compile(r'Authorization:\s*Bearer\s+[a-zA-Z0-9_\-\.\~]+', re.IGNORECASE), 'Authorization: Bearer ***[MASKED]***'),
            (re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.\~]+', re.IGNORECASE), 'Bearer ***[MASKED]***'),
        ]

    def format(self, record: logging.LogRecord) -> str:
        original_msg = super().format(record)
        masked_msg = original_msg
        for pattern, replacement in self.patterns:
            masked_msg = pattern.sub(replacement, masked_msg)
        return masked_msg

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = SecretsMaskingFormatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger
