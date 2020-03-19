class BorgcubeError(Exception):
    pass


class CommandError(BorgcubeError):
    pass


class CommandEnvironmentError(CommandError):
    pass


class AdminCommandError(CommandError):
    pass


class RemoteCommandError(CommandError):
    pass


class CommandMissingBorgcubeEnvironmentVariableError(CommandEnvironmentError):
    def __init__(self, env_var):
        msg = f"Not connected via borgcube generated authorized_keys file. " \
              f"This is not supported. Please read the borgcube documentation. " \
              f"Missing Environment variable: {env_var}"
        super().__init__(msg)


class StorageError(BorgcubeError):
    pass


class StorageInconsistencyError(StorageError):
    pass


class ConfigFileDoesNotExistError(BorgcubeError):
    pass


class DatabaseError(BorgcubeError):
    pass

class DatabaseObjectLockedError(DatabaseError):
    pass