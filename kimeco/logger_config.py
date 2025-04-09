import logging


# Configure the logger
def setup_logger():
    logging.basicConfig(
        filename='kimeco.log',  # Log file name
        level=logging.INFO,  # Set the logging level
        format='%(asctime)s - %(levelname)s - %(message)s'
    )