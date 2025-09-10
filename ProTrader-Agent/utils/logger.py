import logging
from pathlib import Path

LOG_FILE = Path('logs/agent.log')
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured for the project."""
    return logging.getLogger(name)
