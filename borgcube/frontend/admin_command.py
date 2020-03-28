import argparse
from datetime import datetime, timedelta

from borgcube.backend.model import User, DatabaseError, UserLog, Repository, RepoLog, AdminLog
from borgcube.backend.authorized_keys import AuthorizedKeyType, AuthorizedKeysFile
from borgcube.backend.notification import NotificationDispatcher
from borgcube.enum import LogOperation
from borgcube.exception import AdminCommandError
from borgcube.frontend.base_command import BaseCommand
from borgcube.frontend.shell import Shell


class AdminCommand(BaseCommand):

    @property
    def _parser(self):
        parser = argparse.ArgumentParser(description='Borgcube Backup Server')
        parser.set_defaults(func=None)
        subparsers = parser.add_subparsers()

        parse_cron = subparsers.add_parser('cron')
        parse_cron.set_defaults(func=self._command_cron)

        parse_log = subparsers.add_parser('log')
        parse_log.set_defaults(func=self._command_log_read, logfile=None)
        parse_log_subparsers = parse_log.add_subparsers()

        parse_log_user = parse_log_subparsers.add_parser('user')
        parse_log_user.set_defaults(logfile='user')
        parse_log_user.add_argument('user', nargs='?')

        parse_log_repo = parse_log_subparsers.add_parser('repo')
        parse_log_repo.set_defaults(logfile='repo')
        parse_log_repo.add_argument('user', nargs='?')
        parse_log_repo.add_argument('repo', nargs='?')

        parse_log_admin = parse_log_subparsers.add_parser('admin')
        parse_log_admin.set_defaults(logfile='admin')

        parse_regen = subparsers.add_parser('regen')
        parse_regen.set_defaults(func=self._command_regen)

        parse_shell = subparsers.add_parser('shell')
        parse_shell.set_defaults(func=self._command_shell)
        parse_shell.add_argument('user')

        parse_users = subparsers.add_parser('users')
        parse_users.set_defaults(func=self._command_user_list)

        parse_user_add = subparsers.add_parser('add')
        parse_user_add.set_defaults(func=self._command_user_add)
        parse_user_add.add_argument('name')
        parse_user_add.add_argument('email')
        parse_user_add.add_argument('quota', nargs="?")

        parse_user_add = subparsers.add_parser('quota')
        parse_user_add.set_defaults(func=self._command_user_quota)
        parse_user_add.add_argument('name')
        parse_user_add.add_argument('quota')

        parse_user_delete = subparsers.add_parser('delete')
        parse_user_delete.set_defaults(func=self._command_user_delete)
        parse_user_delete.add_argument('name')
        parse_user_delete.add_argument('confirm', nargs="?")

        return parser

    @staticmethod
    def _print_user_headline():
        print(f"{'USER':<21}{'REPOS':<10}{'USAGE':<10}{'ALLOC':<10}{'QUOTA'}")

    @staticmethod
    def _print_user_line(user):
        print(f"{user.name:<21}"
              f"{len(user.repos):<10}"
              f"{(str(user.quota_used_gb) + ' GB'):<10}"
              f"{str(user.quota_allocated_gb) + ' GB':<10}"
              f"{user.quota_gb} GB")

    def _parse_env(self):
        pass

    def _command_log_read(self):
        user = None
        repo = None
        if 'user' in self.args and self.args.user:
            user = User.get_by_name(self.args.user)
            if 'repo' in self.args and self.args.repo:
                repo = Repository.get_by_name(self.args.repo, user)
        if self.args.logfile == 'user':
            if user:
                lines = UserLog.format_logs_for_user(user)
            else:
                lines = UserLog.format_all_logs()
        elif self.args.logfile == 'repo':
            if user:
                if repo:
                    lines = RepoLog.format_logs_for_repo(repo)
                else:
                    lines = RepoLog.format_logs_for_user(user)
            else:
                lines = RepoLog.format_all_logs()
        elif self.args.logfile == 'admin':
            lines = AdminLog.format_all_logs()
        else:
            raise AdminCommandError("You need to specify a log to read: user, repo or admin")
        for line in lines:
            print(line)

    @staticmethod
    def _command_regen():
        authorized_keys = AuthorizedKeysFile(User.get_all())
        authorized_keys.save_atomic()
        print("Regenerated authorized_keys file")

    def _command_user_add(self):
        name = self.args.name
        email = self.args.email
        if '@' not in email:
            raise AdminCommandError(f'Not a valid email address: {email}')
        quota = self.args.quota
        if self.args.quota:
            quota = int(self.args.quota) * 1000 * 1000 * 1000
        try:
            user = User.new(name=name, email=email, quota=quota)
        except DatabaseError as e:
            raise AdminCommandError(e)
        user.save()

    def _command_user_quota(self):
        quota = int(self.args.quota)
        try:
            user = User.get_by_name(self.args.name)
            user.quota_gb = quota
            user.save()
            print(f"Successfully changed quota of user {user.name} to {user.quota_gb} GB")
        except DatabaseError as e:
            raise AdminCommandError(e)
        user.save()

    def _command_user_delete(self):
        user = User.get_by_name(self.args.name)
        if user is None:
            raise AdminCommandError(f"The user {self.args.name} was not found.")
        if self.args.confirm != "CONFIRM":
            self._print_user_headline()
            self._print_user_line(user)
            raise AdminCommandError("\nDo you want to delete this user? Then append CONFIRM to the command line.")
        if user.delete_instance():
            print(f"Successfully deleted user {self.args.name}")
        else:
            raise AdminCommandError(f"There was an error deleting the user {self.args.name}.")

    def _command_user_list(self):
        users = User.get_all()
        self._print_user_headline()
        for user in users:
            self._print_user_line(user)

    def _command_line_user_show(self):
        user = User.get_by_name(self.args.name)
        self._print_user_headline()
        self._print_user_line(user)

    def _command_shell(self):
        # Now we need to fake an environment for the shell
        self.key_type = AuthorizedKeyType.ADMIN_IMPERSONATE
        self.user = user = User.get_by_name(self.args.user)
        self.remote_ip = None
        print(f"Launching shell for user: '{user.name}'")
        shell = Shell(self)
        shell.run()

    @staticmethod
    def _command_cron():
        # Check for last successful backup date
        notification_dispatcher = NotificationDispatcher()
        notification_dispatcher.cron()
        RepoLog.cleanup_logs()

    def run(self):
        if self.args.func:
            self.args.func()
        else:
            raise AdminCommandError("No action specified. Run --help for info.")
