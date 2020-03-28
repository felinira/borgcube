#!/usr/bin/env python3
import sys
import pwd
import os

from borgcube.backend.config import cfg as _cfg
from borgcube.exception import BorgcubeError


def drop_privileges():
    uid_name = _cfg['username']
    entry = pwd.getpwnam(uid_name)
    uid = entry.pw_uid
    gid = entry.pw_gid

    if os.getuid() != 0:
        # We're not root
        if os.getuid() != uid:
            raise BorgcubeError(f"Running as the wrong user: Expected user {uid_name}. Exiting.")
        return

    # We are root. Most likely because we are running from cron
    # Remove group privileges
    os.setgroups([])

    # Try setting the new uid/gid
    os.setgid(gid)
    os.setuid(uid)

    # Ensure a umask
    os.umask(0o022)


def main():
    try:
        drop_privileges()

        from borgcube.frontend.commandline import Commandline
        cmd = Commandline(os.environ.copy(), sys.argv)
        cmd.run()
    except BorgcubeError as e:
        if sys.gettrace():
            # Raise when debugging
            raise
        else:
            # Print the message in production
            print(e)


if __name__ == '__main__':
    main()
