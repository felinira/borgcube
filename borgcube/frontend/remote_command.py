from subprocess import Popen
import argparse
import sys
import shlex

from borgcube.backend.config import cfg as _cfg
from borgcube.backend.model import User, Repository, RepoLog, LogOperation
from borgcube.backend.authorized_keys import AuthorizedKeyType
from borgcube.frontend.base_command import BaseCommand
from borgcube.enum import RemoteCommandType

from borgcube.frontend.shell import Shell

from borgcube.exception import CommandEnvironmentError, \
    CommandMissingBorgcubeEnvironmentVariableError, \
    RemoteCommandError, \
    DatabaseObjectLockedError


class RemoteCommand(BaseCommand):

    @property
    def _parser(self):
        parser = argparse.ArgumentParser(description='Borgcube Backup Server')
        parser.set_defaults(admin=False, func=Shell.usage)

        subparsers = parser.add_subparsers()
        parse_remote = subparsers.add_parser('remote')
        parse_remote.add_argument(dest='command', metavar='BORG SERVE COMMAND', nargs='?',
                                  help='execute borg serve', type=self._parse_remote_command)
        return parser

    def repo_log(self, msg):
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

    def _parse_env(self):
        try:
            self.key_type = self._parse_key_type()
            self.user = self._parse_user()
            self.repo = self._parse_repo()
            self.remote_ip = self._parse_remote_ip()
        except ValueError:
            CommandEnvironmentError("Environment variables in the wrong format.")
        if self.repo and self.repo.user != self.user:
            raise CommandEnvironmentError('Inconsistent repo and user from environment')

    def _parse_remote_command(self, command):
        if command is None:
            return None
        if command == RemoteCommandType.BORGCUBE_COMMAND_SHELL.value:
            if 'SSH_ORIGINAL_COMMAND' in self.env:
                raise RemoteCommandError(f"Connecting via user ssh key to run borg serve is not supported. "
                                         f"Please create an appropriate repository key. "
                                         f"This is for your own safety. "
                                         f"Please also consider using different append mode and read/write keys.")
            else:
                return self._run_shell
        elif command == RemoteCommandType.BORGCUBE_COMMAND_BORG_SERVE.value:
            if 'SSH_ORIGINAL_COMMAND' not in self.env:
                raise RemoteCommandError(f"You are trying to connect to borgcube shell with your repo key. This is not "
                                         f"supported.")
            elif shlex.split(self.env['SSH_ORIGINAL_COMMAND'])[1] != 'serve':
                raise RemoteCommandError(f"You are only allowed to run borg serve!")
            return self._run_borg_command
        raise RemoteCommandError(f'Not permitted to run command: {command}. '
                                 f'Are you running this via borgcube authorized_keys file?')

    def _run_borg_command(self):
        command = [
            _cfg['borg_executable'],
            'serve',
            '--restrict-to-path', f'{self.repo.path}',
            f'--storage-quota', f'{self.repo.quota_gb}G'
        ]
        if self.key_type == AuthorizedKeyType.REPO_APPEND:
            command += [
                '--append-only'
            ]

        try:
            transaction_id_before = self.repo.transaction_id
            RepoLog.log(self.repo, LogOperation.SERVE_REPO_BEGIN, " ".join(command))

            proc = Popen(
                command,
                stderr=sys.stderr,
                stdout=sys.stdout,
                stdin=sys.stdin,
                cwd=self.user.path,
                env=self._stripped_env
            )

            proc.wait()
            new_transaction_id = self.repo.transaction_id

            if proc.returncode == 0:
                RepoLog.log(self.repo, LogOperation.SERVE_REPO_SUCCESS, self.key_type.name)
                if transaction_id_before and new_transaction_id and new_transaction_id > transaction_id_before:
                    RepoLog.log(self.repo, LogOperation.SERVE_MODIFY_SUCCESS, f"Transaction {new_transaction_id}")
            else:
                RepoLog.log(self.repo, LogOperation.SERVE_REPO_ABORT, self.key_type.name)
                if transaction_id_before and new_transaction_id and new_transaction_id > transaction_id_before:
                    RepoLog.log(self.repo, LogOperation.SERVE_MODIFY_ABORT, f"Transaction {new_transaction_id}")
        except DatabaseObjectLockedError:
            raise RemoteCommandError("Can't start borg serve: Repository is already in use.")
        return proc.returncode

    def _run_shell(self):
        if self.key_type not in [AuthorizedKeyType.USER, AuthorizedKeyType.USER_BACKUP]:
            raise RemoteCommandError(f"You are not permitted to connect to borgcube shell with your repository keys. "
                                     f"Please use your associated user key.")
        shell = Shell(self)
        shell.run()

    def run(self):
        if not self.args.command:
            raise CommandMissingBorgcubeEnvironmentVariableError('SSH command')
        self.args.command()
