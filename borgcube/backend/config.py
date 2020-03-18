import yaml
import os


class ConfigFileDoesNotExistError(Exception):
    pass


CONFIG_PATH = ['config.yaml', '/etc/borgcube/config.yaml']

configfilename = None
for path in CONFIG_PATH:
    if os.path.isfile(path):
        configfilename = path
        break

if configfilename:
    with open(configfilename, 'r') as yamlfile:
        cfg = yaml.safe_load(yamlfile)
else:
    raise ConfigFileDoesNotExistError()
