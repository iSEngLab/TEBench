"""
Logging utility module
"""

import logging
import sys
import os
from config import Config

def setup_logger(name='dataset_builder', level='INFO'):
    """
    Set up the logger

    Args:
        name: Logger name
        level: Log level (can be a string or logging constant)

    Returns:
        logger: Logger instance
    """
    # Support string-based level
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level if Config.VERBOSE else logging.WARNING)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    # Console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File output
    try:
        # Ensure output directory exists
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

        file_handler = logging.FileHandler(
            Config.get_output_path(Config.LOG_FILE),
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Failed to create log file: {e}")

    return logger

def get_logger(name='dataset_builder'):
    """Get an existing logger"""
    return logging.getLogger(name)
