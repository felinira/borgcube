from enum import Enum


class RemoteCommandType(Enum):
    BORGCUBE_COMMAND_SHELL = 'BORGCUBE_COMMAND_SHELL'
    BORGCUBE_COMMAND_BORG_SERVE = 'BORGCUBE_COMMAND_BORG_SERVE'


class AuthorizedKeyType(Enum):
    USER = 1
    USER_BACKUP = 2
    REPO_APPEND = 3
    REPO_RW = 4
    ADMIN_IMPERSONATE = 5
