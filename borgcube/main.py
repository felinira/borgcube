#!/usr/bin/env python3
import argparse
import os
import sys

from borgcube.backend.model import *
from borgcube.frontend.commandline import Commandline
from borgcube.exception import BorgcubeError


def main():
    os.umask(0o022)
    try:
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
