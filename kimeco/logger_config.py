import logging
from logging import Logger


# Configure the logger
def setup_logger(name) -> Logger:
    logging.basicConfig(
        filename=name,  # Log file name
        level=logging.INFO,  # Set the logging level
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    klog: Logger = logging.getLogger()
    return klog
