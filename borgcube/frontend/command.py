from subprocess import Popen
from asyncio import AbstractEventLoop, coroutine
import sys
import argparse

from borgcube.backend.model import User, Repository, RepoLog, LogOperation, DatabaseError
from borgcube.backend.authorized_keys import AuthorizedKeyType
from borgcube.backend.config import cfg as _cfg

from borgcube.frontend.shell import Shell


class CommandError(Exception):
    pass


class CommandEnvironmentError(CommandError):
    pass


class CommandMissingBorgcubeEnvironmentVariableError(CommandEnvironmentError):
    def __init__(self, env_var):
        msg = f"Not connected via borgcube generated authorized_keys file. " \
              f"This is not supported. Please read the borgcube documentation. " \
              f"Missing Environment variable: {env_var}"
        super().__init__(msg)


class Command(object):
    def __init__(self, env):
        self.env = env
        self.args = self._parse_args()
        self.command = self._parse_command(self.args.command)
        if not self.args.admin:
            try:
                self.key_type = self._parse_key_type()
                self.user = self._parse_user()
                self.repo = self._parse_repo()
                self.remote_ip = self._parse_remote_ip()
            except ValueError:
                CommandEnvironmentError("Environment variables in the wrong format.")
            if self.repo and self.repo.user != self.user:
                raise CommandEnvironmentError('Inconsistent repo and user from environment')

    def _repo_log(self, msg):
        RepoLog.log(self.repo, LogOperation.SERVE_REPO_LOG, str(msg))

    @property
    def _stripped_env(self):
        env = {}
        if 'SSH_ORIGINAL_COMMAND' in self.env:
            env['SSH_ORIGINAL_COMMAND'] = self.env['SSH_ORIGINAL_COMMAND']
        return env

    def _parse_user(self):
        if 'LOGNAME' not in self.env:
            raise CommandEnvironmentError(f"Your SSH server does not set LOGNAME. This is required.")
        if self.env['LOGNAME'] != _cfg['username']:
            raise CommandEnvironmentError(f"Connected with wrong SSH user: expected {_cfg['username']}")
        if 'BORGCUBE_USER' in self.env:
            user_id = int(self.env['BORGCUBE_USER'])
            user = User.get_by_id(user_id)
            if not user:
                raise CommandEnvironmentError(f'User id:{user_id} not found')
            return user
        else:
            raise CommandMissingBorgcubeEnvironmentVariableError(f"BORGCUBE_USER")

    def _parse_repo(self):
        if 'BORGCUBE_REPO' in self.env:
            repo_id = int(self.env['BORGCUBE_REPO'])
            repo = Repository.get_by_id(repo_id)
            if not repo:
                raise CommandEnvironmentError(f'Repository id:{repo_id} not found')
            return repo
        return None

    def _parse_key_type(self):
        if 'BORGCUBE_KEY_TYPE' in self.env:
            return AuthorizedKeyType(int(self.env['BORGCUBE_KEY_TYPE']))
        raise CommandMissingBorgcubeEnvironmentVariableError("BORGCUBE_KEY_TYPE")

    def _parse_remote_ip(self):
        if 'SSH_CONNECTION' in self.env:
            return self.env['SSH_CONNECTION'].split()[0]
        return None

    def _command_line_admin_user_add(self):
        name = self.args.name
        email = self.args.email
        quota = None
        if self.args.quota:
            quota = int(self.args.quota)
        try:
            user = User.new(name=name, email=email, quota_gb=quota)
        except DatabaseError as e:
            raise CommandError(e)
        user.save()

    def _command_line_admin_user_delete(self):
        user = User.get_by_name(self.args.name)
        if self.args.confirm != "CONFIRM":
            self._print_user_headline()
            self._print_user_line(user)
            raise CommandError("\nDo you want to delete this user? Then append CONFIRM to the command line")
        user.delete_instance()

    def _print_user_headline(self):
        print(f"{'USER':<21}{'REPOS':<10}{'USAGE':<10}{'ALLOC':<10}{'QUOTA'}")

    def _print_user_line(self, user):
        print(f"{user.name:<21}"
              f"{len(user.repos):<10}"
              f"{(str(user.quota_used) + ' GB'):<10}"
              f"{str(user.quota_allocated) + ' GB':<10}"
              f"{user.quota_gb} GB")

    def _command_line_admin_user_list(self):
        users = User.get_all()
        self._print_user_headline()
        for user in users:
            self._print_user_line(user)

    def _command_line_admin_user_show(self):
        user = User.get_by_name(self.args.name)
        self._print_user_headline()
        self._print_user_line(user)

    def _command_line_admin(self):
        pass

    def _command_line_admin_shell(self):
        user = User.get_by_name(self.args.user)
        # Now we need to fake an environment for the shell
        print(f"Launching shell for user: '{user.name}'")
        self.env = {
            f'BORGCUBE_KEY_TYPE': AuthorizedKeyType.USER_BACKUP.value,
            f'BORGCUBE_USER': user.id,
            f'LOGNAME': _cfg['username'],
            f'SSH_CONNECTION': '127.0.0.1'
        }
        self.key_type = self._parse_key_type()
        self.user = self._parse_user()
        self.remote_ip = self._parse_remote_ip()
        self._run_shell()

    def _parse_args(self):
        parser = argparse.ArgumentParser(description='Borgcube Backup Server')
        parser.add_argument('-c', dest='command', metavar='BORG SERVE COMMAND', nargs='?',
                            help='execute borg serve')
        parser.set_defaults(admin=False)
        subparsers = parser.add_subparsers()

        parse_admin = subparsers.add_parser('admin', help='admin commands')
        parse_admin.set_defaults(admin=True, func=self._command_line_admin)
        parse_admin_subparsers = parse_admin.add_subparsers()

        parse_admin_users = parse_admin_subparsers.add_parser('shell')
        parse_admin_users.set_defaults(func=self._command_line_admin_shell)
        parse_admin_users.add_argument('user')

        parse_admin_users = parse_admin_subparsers.add_parser('users')
        parse_admin_users.set_defaults(func=self._command_line_admin_user_list)

        parse_admin_user_add = parse_admin_subparsers.add_parser('add')
        parse_admin_user_add.set_defaults(func=self._command_line_admin_user_add)
        parse_admin_user_add.add_argument('name')
        parse_admin_user_add.add_argument('email')
        parse_admin_user_add.add_argument('quota', nargs="?")

        parse_admin_user_add = parse_admin_subparsers.add_parser('delete')
        parse_admin_user_add.set_defaults(func=self._command_line_admin_user_delete)
        parse_admin_user_add.add_argument('name')
        parse_admin_user_add.add_argument('confirm', nargs="?")

        args = parser.parse_args()
        return args

    def _parse_command(self, command):
        if command is None:
            return None
        if command != 'BORGCUBE_COMMAND_BORG_SERVE':
            raise CommandError(f'Not permitted to run command: {command}. '
                               f'Are you running this via borgcube authorized_keys file? You should!')
        command = [
            _cfg['borg_executable'],
            'serve',
            f'--restrict-to-path {self.repo.path}',
            f'--storage-quota {self.repo.quota_gb}G'
        ]
        if self.key_type == AuthorizedKeyType.REPO_APPEND:
            command += [
                '--append-only'
            ]
        return command

    def _run_borg_serve(self):
        if self.key_type not in [AuthorizedKeyType.REPO_APPEND, AuthorizedKeyType.REPO_RW]:
            raise CommandError(f"Connecting via user ssh key to run borg serve is not supported. "
                               f"Please create an appropriate repository key. "
                               f"This is for your own safety. "
                               f"Please also consider using different append mode and read/write keys (not enforced)")
        RepoLog.log(self.repo, LogOperation.SERVE_REPO_BEGIN, self.key_type.name)

        proc = Popen(
            self.args.command,
            stderr=sys.stderr,
            stdout=sys.stdout,
            stdin=sys.stdin,
            cwd=self.repo.path,
            env=self._stripped_env
        )

        proc.wait()
        if proc.returncode == 0:
            RepoLog.log(self.repo, LogOperation.SERVE_REPO_SUCCESS, self.key_type.name)
        else:
            RepoLog.log(self.repo, LogOperation.SERVE_REPO_ABORT, self.key_type.name)
        return proc.returncode

    def _run_shell(self):
        if self.key_type not in [AuthorizedKeyType.USER, AuthorizedKeyType.USER_BACKUP]:
            raise CommandError(f"You are not permitted to connect to borgcube shell with your repository keys. "
                               f"Please use your associated user keys.")
        shell = Shell(self)
        shell.run()

    def run(self):
        if self.args.command:
            # BORG SERVE MODE
            self._run_borg_serve()
        elif 'SSH_CONNECTION' in self.env:
            # SHELL MODE
            self._run_shell()
        elif self.args.admin:
            try:
                self.args.func()
            except (CommandError, DatabaseError) as e:
                print(e)
        else:
            # FAIL MODE
            raise CommandError("No action specified. Run --help for info.")
