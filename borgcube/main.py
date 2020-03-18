#!/usr/bin/env python3
import argparse
import os

from borgcube.backend.model import *

from borgcube.frontend.shell import Shell
from borgcube.frontend.command import Command


def main():
    os.umask(0o022)
    cmd = Command(os.environ.copy())
    cmd.run()


if __name__ == '__main__':
    main()
