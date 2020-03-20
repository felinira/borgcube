

class BorgCommand(object):
    def __init__(self):

    pass


from borg.repository import Repository
from borg.helpers import msgpack

import os
repo = Repository('./')
repo.__enter__()
transaction_id = repo.get_transaction_id()
hints_path = os.path.join(repo.path, 'hints.%d' % transaction_id)
with open(hints_path, 'rb') as fd:
    hints = msgpack.unpack(fd)