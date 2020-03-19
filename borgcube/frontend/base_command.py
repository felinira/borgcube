from abc import ABC, abstractmethod


class BaseCommand(ABC):
    def __init__(self, env, commandline):
        self.env = env
        self._commandline = commandline
        self._parse_env()
        self._parse_args()

    @property
    @abstractmethod
    def _parser(self):
        pass

    @abstractmethod
    def _parse_env(self):
        pass

    def _parse_args(self):
        self.args = self._parser.parse_args(self._commandline[1:])
