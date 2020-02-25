import yaml

CONFIG_PATH = 'config.yaml'


with open(CONFIG_PATH, 'r') as yamlfile:
    cfg = yaml.load(yamlfile, Loader=yaml.CLoader)
