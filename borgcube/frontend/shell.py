import argparse
# for input history functions
import readline
import datetime
import colored

from borgcube.backend.config import cfg
from borgcube.backend.model import DoesNotExist, DatabaseError, Repository, User, RepoLog, AdminLog, UserLog
from borgcube.backend.authorized_keys import AuthorizedKeysFile, AuthorizedKeyType

COLOR_SUCCESS = 'pale_green_3a'
COLOR_FAIL = 'indian_red_1b'
COLOR_PROMPT = 'light_sea_green'


def _echo(*args, fg=None, bg=None, attr=None):
    text = ''.join(str(*args))
    style = ""
    if fg:
        style += colored.fg(fg)
    if bg:
        style += colored.bg(bg)
    if attr:
        style += colored.attr(attr)
    if style != "":
        text = colored.stylize_interactive(text, style)
    print(text, end='')


def _yesno_prompt(line):
    yes = {'yes', 'y', 'ye'}
    no = {'no', 'n'}

    choice = input(line).lower()
    if choice in yes:
        return True
    elif choice in no:
        return False
    else:
        _echo("Please respond with 'Y' or 'N'\n")


class ShellError(Exception):
    pass


class ShellCommandError(Exception):
    pass


class ShellEnvironmentError(ShellError):
    pass


class ShellExit(Exception):
    pass


class Shell(object):
    def __init__(self, command):
        self.cmd = command
        self.user = self.cmd.user

    def parse_connection(self):
        if self.cmd.key_type == AuthorizedKeyType.USER and self.user.backup_ssh_key:
            self.user_key_delete_backup()
            _echo(f"SUCCESSFULLY ACCEPTED NEW SSH KEY. YOU BACKUP KEY SLOT HAS BEEN ERASED.\n\n")
        elif self.cmd.key_type == AuthorizedKeyType.USER_BACKUP:
            _echo(f"CONNECTED VIA BACKUP KEY. PLEASE CONNECT WITH YOUR NEW SSH KEY "
                  f"OR SET IT AGAIN VIA 'user key set'\n\n",
                  fg=COLOR_FAIL)

    def welcome_msg(self):
        _echo(f"Welcome to borgcube, {self.user.name}.\n")
        _echo("Enter 'help' for a command description.\n\n")
        _echo(f"You are connected from {self.cmd.remote_ip}.\n")
        _echo(f"This service is provided to you by:\n{cfg['admin_contact']}\n\n")
        self.user_quota_info()
        _echo("\n")
        if self.user.last_date:
            _echo(f"Last login: {self.user.last_date.ctime()}\n")
        else:
            _echo("This is your first login. We hope you are happy with our services :)\n")
        self.user.last_date = datetime.datetime.now()
        self.user.save()

    @staticmethod
    def usage(parser, args):
        parser.print_usage()

    @staticmethod
    def help(parser, args):
        parser.print_help()

    @staticmethod
    def exit(parser, args):
        raise ShellExit()

    def user_quota_info(self):
        _echo(f"Quota used: {self.user.quota_used}GB / {self.user.quota_gb}GB\n")
        _echo(f"Quota alloc: {self.user.quota_allocated}GB / {self.user.quota_gb}GB\n")

    def user_info(self, parser, args):
        _echo(f"You are logged in as {self.user.name}\n")
        _echo(f"Email: {self.user.email}\n")
        if self.user.ssh_key:
            _echo(f"SSH User Key: {self.user.ssh_key.comment}")
        if self.user.backup_ssh_key:
            _echo(f" (unverified)\n")
            _echo(f"Backup user key: {self.user.backup_ssh_key}")
        _echo(f"\nRepos: {len(self.user.repos)} / {self.user.max_repo_count}\n")
        self.user_quota_info()

    def user_key_delete_backup(self):
        self.user.backup_ssh_key = None
        self.user.save()

    def user_key_show(self, parser, args):
        _echo(f"SSH key: \n")
        if self.user.ssh_key:
            _echo(self.user.ssh_key.to_pubkey_line())
        else:
            _echo("<missing>")
        if self.user.backup_ssh_key:
            _echo("\n\nOld SSH Key: \n", fg=COLOR_FAIL)
            _echo(self.user.backup_ssh_key.to_pubkey_line())
            _echo("You have set a new key but didn't log in with it yet. Please log in once with your new key to "
                  "purge your old key.", fg=COLOR_FAIL)
        _echo("\n")

    def user_key_set(self, parser, args):
        if len(args.key) == 0:
            raise ShellCommandError("Can't set empty user key")
        else:
            key = ' '.join(args.key)
        try:
            self.user.backup_ssh_key = self.user.ssh_key
            self.user.ssh_key = key
            self.user.save()
            if key:
                _echo(f"Successfully set ssh user key\n", fg=COLOR_SUCCESS)
                _echo(f"Your old key is still valid. Please log in once with your new key to verify it.\n")
            else:
                _echo(f"Successfully cleared ssh user key\n", fg=COLOR_SUCCESS)
        except DatabaseError as e:
            raise ShellCommandError(f"Can't set key: {e}\n")
        authorized_keys_file = AuthorizedKeysFile(User.get_all())
        authorized_keys_file.save_atomic()


    def repo_show(self, parser, args):
        repo = args.repo
        _echo("Repo information:\n")
        _echo(f"Name: {repo.name}\n")
        _echo(f"Creation date: {repo.creation_date.ctime()}\n")
        if repo.last_date:
            _echo(f"Last Accessed: {repo.last_date.ctime()}\n")
        _echo(f"Locked: {repo.locked}\n")
        self.repo_quota(parser, args)

    def repo_list(self, parser, args):
        _echo(f"Repos: {len(self.user.repos)} / {self.user.max_repo_count}\n")
        if len(self.user.repos) > 0:
            _echo(f"{'REPO':<21}{'USAGE':<10}{'QUOTA'}\n")
            for repo in self.user.repos:
                _echo(f"{repo.name:<21}{(str(repo.size_gb) + ' GB'):<10}{repo.quota_gb} GB\n")

    def repo_quota(self, parser, args):
        if args.new_quota is not None:
            return self.repo_quota_set(parser, args)
        _echo(f"Storage used: {(str(args.repo.size_gb) + ' GB')} / {args.repo.quota_gb} GB\n")
        _echo(f"You can change quota with 'repo quota {args.repo.name} <size in GB>'\n")

    def repo_quota_set(self, parser, args):
        if args.new_quota < 1:
            raise ShellCommandError(f"Quota must be 1GB or more")
        try:
            args.repo.quota_gb = args.new_quota
            _echo(f"Changed repo quota to {args.repo.quota_gb} GB\n", fg=COLOR_SUCCESS)
        except DatabaseError as e:
            raise ShellCommandError(f'{e}')

    def repo_create(self, parser, args):
        try:
            repo = Repository.new(self.user, args.name, args.quota)
            _echo(f"Created repository with name {repo.name}\n", fg=COLOR_SUCCESS)
        except DatabaseError as e:
            raise ShellCommandError(f"Can't create repository '{args.name}': {e}")

    def repo_del(self, parser, args):
        if not args.repo:
            raise ShellCommandError(f"Can't delete repository because it does not exist")
        try:
            if _yesno_prompt(f"Do you want to delete your repo '{args.repo.name}' and all backup contents? [Y/N] "):
                args.repo.delete_instance()
                _echo(f"Deleted repo '{args.repo.name}'\n", fg=COLOR_SUCCESS)
        except DatabaseError as e:
            raise ShellCommandError(f"Can't delete repository '{args.repo.name}': {e}")

    def repo_keys_show(self, parser, args):
        _echo(f"Append SSH key:\n")
        if args.repo.append_ssh_key:
            _echo(args.repo.append_ssh_key.to_pubkey_line())
        else:
            _echo("<missing>")
        _echo("\n\nRead/write SSH Key:\n")
        if args.repo.rw_ssh_key:
            _echo(args.repo.rw_ssh_key.to_pubkey_line())
        else:
            _echo("<missing>")
        _echo("\n")

    def repo_key_set(self, parser, args):
        if len(args.key) == 0:
            key = None
        else:
            key = ' '.join(args.key)
        try:
            if args.key_type == 'append':
                old_key = args.repo.append_ssh_key
                args.repo.append_ssh_key = key
                if args.repo.rw_ssh_key and args.repo.rw_ssh_key.fingerprint == args.repo.append_ssh_key.fingerprint:
                    args.repo.append_ssh_key = old_key
                    raise ShellCommandError(f"Can't set repo '{args.repo.name}' append key to same value as read/write "
                                            f"key. If you only want to use one key you only need to set the read/write "
                                            f"key. You can clear/change the read/write key with this command:\n"
                                            f"repo keys {args.repo.name} set_rw_key")
            else:
                old_key = args.repo.rw_ssh_key
                args.repo.rw_ssh_key = key
                if args.repo.append_ssh_key and args.repo.append_ssh_key.fingerprint == args.repo.rw_ssh_key.fingerprint:
                    args.repo.rw_ssh_key = old_key
                    raise ShellCommandError(f"Can't set repo '{args.repo.name}' read/Write key to same value as append "
                                            f"key. If you only want to use one key you only need to set the read/write "
                                            f"key. You can clear/change the append key with this command:\n"
                                            f"repo keys {args.repo.name} set_append_key")
            args.repo.save()
            if key:
                _echo(f"Successfully set {args.key_type} key of '{args.repo.name}'\n", fg=COLOR_SUCCESS)
            else:
                _echo(f"Successfully cleared {args.key_type} key of '{args.repo.name}'\n", fg=COLOR_SUCCESS)
        except DatabaseError as e:
            raise ShellCommandError(f"Can't set key: {e}\n")
        authorized_keys_file = AuthorizedKeysFile(User.get_all())
        authorized_keys_file.save_atomic()

    def repo_logs(self, parser, args):
        if args.repo:
            lines = RepoLog.format_logs_for_repo(args.repo)
        else:
            lines = RepoLog.format_logs_for_user(self.user)
        for line in lines:
            _echo(line)

    def argparse_repo(self, repo_name):
        try:
            return Repository.get_by_name(repo_name, self.user)
        except DoesNotExist:
            raise argparse.ArgumentTypeError(f"Repo {repo_name} does not exist.")

    def get_parser(self):
        parser = argparse.ArgumentParser(description='Borgcube Backup Server Shell', add_help=False, prog='borgcube')
        subparsers = parser.add_subparsers(title='commands')

        parser.set_defaults(func=Shell.usage)
        parse_help = subparsers.add_parser('help', aliases=['h', '?'], help='Display this help')
        parse_help.set_defaults(func=Shell.help)

        parse_exit = subparsers.add_parser('exit', aliases=['quit', 'q'], help='Exit shell')
        parse_exit.set_defaults(func=Shell.exit)

        parse_user = subparsers.add_parser('user', help='user commands')
        parse_user.set_defaults(func=self.user_info)

        user_subparsers = parse_user.add_subparsers(required=False)

        parse_user_info = user_subparsers.add_parser('info', help='user information')
        parse_user_info.set_defaults(func=self.user_info)

        parse_user_key = user_subparsers.add_parser('key', help='get/set user shell ssh key')
        parse_user_key.set_defaults(func=self.user_key_show)

        user_key_subparsers = parse_user_key.add_subparsers(required=False)
        parse_user_key_set = user_key_subparsers.add_parser('set', help='set user ssh key')
        parse_user_key_set.add_argument('key', nargs="*", help='SSH key')
        parse_user_key_set.set_defaults(func=self.user_key_set, key_type='rw')

        parse_repo = subparsers.add_parser('repo', help='repo commands')
        parse_repo.set_defaults(func=self.repo_list)

        repo_subparsers = parse_repo.add_subparsers(required=False)
        parse_repo_show = repo_subparsers.add_parser('show', help='show repo information')
        parse_repo_show.add_argument('repo', type=self.argparse_repo, help='name of the repository')
        parse_repo_show.set_defaults(func=self.repo_show)

        parse_repo_logs = repo_subparsers.add_parser('logs', help='get logs')
        parse_repo_logs.set_defaults(func=self.repo_logs)
        parse_repo_logs.add_argument('repo', nargs="?", type=self.argparse_repo, help='name of the repository')

        parse_repo_quota = repo_subparsers.add_parser('quota', help='get or set quota')
        parse_repo_quota.set_defaults(func=self.repo_quota)
        parse_repo_quota.add_argument('repo', type=self.argparse_repo, help='name of the repository')
        parse_repo_quota.add_argument('new_quota', nargs='?', type=int, help='value to set the repo quota to')

        parse_repo_create = repo_subparsers.add_parser('create', help='create repo')
        parse_repo_create.add_argument('name', help='name of the new repository')
        parse_repo_create.add_argument('quota', type=int, help='repository quota')
        parse_repo_create.set_defaults(func=self.repo_create)

        parse_repo_delete = repo_subparsers.add_parser('delete', help='delete repo')
        parse_repo_delete.add_argument('repo', type=self.argparse_repo, help='repository name')
        parse_repo_delete.set_defaults(func=self.repo_del)

        parse_repo_keys = repo_subparsers.add_parser('keys', help='get or set ssh key')
        parse_repo_keys.add_argument('repo', type=self.argparse_repo, help='repository name')
        parse_repo_keys.set_defaults(func=self.repo_keys_show)

        repo_keys_subparsers = parse_repo_keys.add_subparsers(required=False)
        parse_repo_key_append_set = repo_keys_subparsers.add_parser('set_append_key', help='set append mode key')
        parse_repo_key_append_set.add_argument('key', nargs="*", help='SSH key')
        parse_repo_key_append_set.set_defaults(func=self.repo_key_set, key_type='append')

        parse_repo_key_rw_set = repo_keys_subparsers.add_parser('set_rw_key', help='set read write mode key')
        parse_repo_key_rw_set.add_argument('key', nargs="*", help='SSH key')
        parse_repo_key_rw_set.set_defaults(func=self.repo_key_set, key_type='rw')

        return parser

    def loop(self):
        parser = self.get_parser()
        try:
            while True:
                prompt = f"{cfg['server_name']}# "
                if self.user:
                    prompt = colored.stylize_interactive(f"{self.user.name}@{cfg['server_name']}",
                                                         colored.fg(COLOR_PROMPT)) + "$ "
                line = input(prompt).strip()
                if line == "":
                    continue
                try:
                    args = parser.parse_args(line.split())
                except SystemExit:
                    continue
                try:
                    args.func(parser, args)
                except ShellCommandError as e:
                    _echo(f"Error: {e}\n", fg=COLOR_FAIL)
        except (ShellExit, EOFError, KeyboardInterrupt):
            _echo("\nBye\n")

    def run(self):
        try:
            self.parse_connection()
            self.welcome_msg()
            self.loop()
        except ShellEnvironmentError as e:
            _echo(f"Error in shell environment variables: {e}\n")

