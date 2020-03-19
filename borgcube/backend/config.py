import yaml
import os

from borgcube.exception import ConfigFileDoesNotExistError

CONFIG_PATH = ['config.yaml', '/etc/borgcube/config.yaml']

config_filename = None
for path in CONFIG_PATH:
    if os.path.isfile(path):
        config_filename = path
        break

if config_filename:
    with open(config_filename, 'r') as yamlfile:
        cfg = yaml.safe_load(yamlfile)
else:
    raise ConfigFileDoesNotExistError()
