from _thread import LockType
import logging
from logging import Logger
import threading
import os
from datetime import datetime

# Module-level lock for thread-safe file renaming
_file_rename_lock: LockType = threading.Lock()


class KMOLogger:
    """Lazy logger that only creates the log file when a message is
    actually written.

    Behaves like a standard Logger but defers file creation until a message
    at or above the configured level is logged.

    If a log file with the same name already exists when the first message
    is logged, the existing file is automatically renamed with a timestamp
    from its creation date (format: basename_YYYY_MM_DD.log). If that name
    is taken, a counter is appended (e.g., basename_YYYY_MM_DD_1.log).
    This behavior is thread-safe.
    """

    def __init__(self, filename: str, level: int = logging.INFO):
        """Initialize the KMOLogger.

        Args:
            filename: Path to the log file (created only on first write)
            level: Minimum logging level (default: logging.INFO)
        """
        self.filename = filename
        self.level = level
        self._logger: Logger | None = None
        self._initialized = False
        self.format = '%(asctime)s - %(levelname)s - %(message)s'

    def _ensure_initialized(self):
        """Initialize the underlying logger and create the file."""
        if not self._initialized:
            # Thread-safe file rename logic
            with _file_rename_lock:
                if os.path.exists(self.filename):
                    # Get creation time and format as YYYY_MM_DD
                    try:
                        ctime = os.path.getctime(self.filename)
                        timestamp = datetime.fromtimestamp(ctime).strftime(
                            '%Y_%m_%d')

                        # Split filename into base and extension
                        base, ext = os.path.splitext(self.filename)

                        # Construct new filename with timestamp
                        new_name = f"{base}_{timestamp}{ext}"

                        # Handle naming collisions by appending counter
                        counter = 1
                        while os.path.exists(new_name):
                            new_name = f"{base}_{timestamp}_{counter}{ext}"
                            counter += 1

                        # Rename the old file
                        os.rename(self.filename, new_name)
                    except OSError:
                        # Silently continue if rename fails
                        pass

            # Create a unique logger instance for this file
            logger_name = f"KMOLogger_{id(self)}"
            self._logger = logging.getLogger(logger_name)
            self._logger.setLevel(self.level)

            # Remove any existing handlers
            self._logger.handlers.clear()

            # Create file handler (this creates the file)
            handler = logging.FileHandler(self.filename, mode='a')
            handler.setLevel(self.level)
            formatter = logging.Formatter(self.format)
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

            # Prevent propagation to root logger
            self._logger.propagate = False

            self._initialized = True

    def _log(self, level: int, msg: str, *args, **kwargs):
        """Internal logging method that ensures initialization before
        writing."""
        if level >= self.level:
            self._ensure_initialized()
            self._logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """Log a debug message."""
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """Log an info message."""
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Log a warning message."""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Log an error message."""
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Log a critical message."""
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def setLevel(self,
                 level: int):
        """Set the logging level.

        Args:
            level: New logging level (e.g., logging.DEBUG, logging.INFO)
        """
        self.level = level
        if self._logger:
            self._logger.setLevel(level)
            for handler in self._logger.handlers:
                handler.setLevel(level)

    def getEffectiveLevel(self) -> int:
        """Get the effective logging level."""
        return self.level

    def isEnabledFor(self,
                     level: int) -> bool:
        """Check if a message at the given level would be logged."""
        return level >= self.level

    def close(self):
        """Close all handlers and clean up."""
        if self._logger:
            for handler in self._logger.handlers:
                handler.close()
            self._logger.handlers.clear()


def setup_logger(name: str,
                 level: int = logging.INFO) -> KMOLogger:
    """Create a KMOLogger instance.

    Args:
        name: Log file path
        level: Logging level (default: logging.INFO)

    Returns:
        KMOLogger instance
    """
    return KMOLogger(filename=name, level=level)


def create_logger(name: str,
                  level: int = logging.INFO) -> KMOLogger:
    """Factory function to create a KMOLogger.

    Args:
        name: Log file path
        level: Logging level (default: logging.INFO)

    Returns:
        KMOLogger instance
    """
    return KMOLogger(filename=name, level=level)
