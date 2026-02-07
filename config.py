import yaml
import logging

CONFIG_FILE = 'config.yaml'

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration file {CONFIG_FILE} not found.")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file: {e}")
        return None
