from borgcube.frontend.admin_command import AdminCommand
from borgcube.frontend.remote_command import RemoteCommand

from borgcube.exception import CommandError, CommandEnvironmentError, DatabaseError

SHELL_REMOTE_VARIABLES = ["SSH_CONNECTION"]


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
        remote = False
        for e in env:
            if e in SHELL_REMOTE_VARIABLES:
                remote = True
                break
        if 'SHELL' not in env:
            raise CommandEnvironmentError(error_str)
        if remote and env['SHELL'] != commandline[0]:
            raise CommandEnvironmentError(error_str)
        return remote

    def run(self):
        if self.cmd:
            try:
                self.cmd.run()
            except (CommandError, DatabaseError) as e:
                print(e)
        else:
            raise CommandError("No action specified. Run --help for info.")
