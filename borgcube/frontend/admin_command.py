import argparse
from borgcube.backend.model import User, DatabaseError
from borgcube.backend.authorized_keys import AuthorizedKeyType, AuthorizedKeysFile
from borgcube.exception import AdminCommandError
from borgcube.frontend.base_command import BaseCommand
from borgcube.frontend.shell import Shell


class AdminCommand(BaseCommand):

    @property
    def _parser(self):
        parser = argparse.ArgumentParser(description='Borgcube Backup Server')
        subparsers = parser.add_subparsers()

        parse_admin = subparsers.add_parser('admin', help='admin commands')
        parse_admin.set_defaults(func=parse_admin.print_usage)
        parse_admin_subparsers = parse_admin.add_subparsers()

        parse_admin_regen = parse_admin_subparsers.add_parser('regen')
        parse_admin_regen.set_defaults(func=self._command_admin_regen)

        parse_admin_users = parse_admin_subparsers.add_parser('shell')
        parse_admin_users.set_defaults(func=self._command_admin_shell)
        parse_admin_users.add_argument('user')

        parse_admin_users = parse_admin_subparsers.add_parser('users')
        parse_admin_users.set_defaults(func=self._command_admin_user_list)

        parse_admin_user_add = parse_admin_subparsers.add_parser('add')
        parse_admin_user_add.set_defaults(func=self._command_admin_user_add)
        parse_admin_user_add.add_argument('name')
        parse_admin_user_add.add_argument('email')
        parse_admin_user_add.add_argument('quota', nargs="?")

        parse_admin_user_add = parse_admin_subparsers.add_parser('delete')
        parse_admin_user_add.set_defaults(func=self._command_admin_user_delete)
        parse_admin_user_add.add_argument('name')
        parse_admin_user_add.add_argument('confirm', nargs="?")

        return parser

    @staticmethod
    def _print_user_headline():
        print(f"{'USER':<21}{'REPOS':<10}{'USAGE':<10}{'ALLOC':<10}{'QUOTA'}")

    @staticmethod
    def _print_user_line(user):
        print(f"{user.name:<21}"
              f"{len(user.repos):<10}"
              f"{(str(user.quota_used) + ' GB'):<10}"
              f"{str(user.quota_allocated) + ' GB':<10}"
              f"{user.quota_gb} GB")

    def _parse_env(self):
        pass

    @staticmethod
    def _command_admin_regen():
        authorized_keys = AuthorizedKeysFile(User.get_all())
        authorized_keys.save_atomic()
        print("Regenerated authorized_keys file")

    def _command_admin_user_add(self):
        name = self.args.name
        email = self.args.email
        quota = None
        if self.args.quota:
            quota = int(self.args.quota)
        try:
            user = User.new(name=name, email=email, quota_gb=quota)
        except DatabaseError as e:
            raise AdminCommandError(e)
        user.save()

    def _command_admin_user_delete(self):
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
            raise AdminCommandError("There was an error deleting the user {self.args.name}.")

    def _command_admin_user_list(self):
        users = User.get_all()
        self._print_user_headline()
        for user in users:
            self._print_user_line(user)

    def _command_line_user_show(self):
        user = User.get_by_name(self.args.name)
        self._print_user_headline()
        self._print_user_line(user)

    def _command_admin_shell(self):
        # Now we need to fake an environment for the shell
        self.key_type = AuthorizedKeyType.ADMIN_IMPERSONATE
        self.user = user = User.get_by_name(self.args.user)
        self.remote_ip = None
        print(f"Launching shell for user: '{user.name}'")
        shell = Shell(self)
        shell.run()

    def run(self):
        if self.args.func:
            self.args.func()
        else:
            raise AdminCommandError("No action specified. Run --help for info.")
