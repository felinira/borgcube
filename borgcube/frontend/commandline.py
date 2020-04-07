from borgcube.frontend.admin_command import AdminCommand
from borgcube.frontend.remote_command import RemoteCommand
from borgcube.backend.config import cfg as _cfg

from borgcube.exception import CommandError, CommandEnvironmentError, DatabaseError

SHELL_REMOTE_VARIABLES = ['SSH_CONNECTION', 'BORGCUBE_KEY_TYPE']


class Commandline(object):

    def __init__(self, env, commandline):
        self.is_remote = self._is_remote(env, commandline)
        if not self.is_remote:
            self.cmd = AdminCommand(env, commandline)
        else:
            self.cmd = RemoteCommand(env, commandline)

    @staticmethod
    def _is_remote(env, commandline):
        error_str = "Inconsistent or incomplete environment. Can't determine if running in a remote shell or not."
        is_remote = False
        is_local = False
        for e in SHELL_REMOTE_VARIABLES:
            if e in env:
                is_remote = True
            if e not in env:
                is_local = True
        if is_remote == is_local:
            raise CommandEnvironmentError(error_str)
        if 'SHELL' not in env:
            raise CommandEnvironmentError(error_str)
        if commandline[0] != _cfg['borgcube_executable']:
            raise CommandEnvironmentError(error_str)
        return is_remote

    def run(self) -> int:
        if self.cmd:
            try:
                return self.cmd.run()
            except (CommandError, DatabaseError) as e:
                print(e)
        else:
            raise CommandError("No action specified. Run --help for info.")
