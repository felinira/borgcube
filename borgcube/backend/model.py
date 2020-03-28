import datetime
import math
import os
from time import time, sleep
from typing import Optional, List

import psutil
from peewee import *
from peewee import IntegerField
from sshpubkeys import SSHKey, InvalidKeyError
from contextlib import contextmanager
import re

from .storage import Storage
from .config import cfg as _cfg

from borgcube.exception import DatabaseError, DatabaseObjectLockedError, StorageError
from borgcube.enum import LogOperation


_db = SqliteDatabase(None)
_storage = Storage(_cfg['storage_path'])
_name_regex = reg = re.compile('^[a-zA-Z0-9_]+$')


class LogOperationField(SmallIntegerField):
    def db_value(self, enum_value: LogOperation):
        int_value = enum_value.value
        return super().db_value(int_value)

    def python_value(self, value):
        int_value = super().python_value(value)
        return LogOperation(int_value)


class SSHKeyField(CharField):
    @staticmethod
    def parse_ssh_key(key_string: str):
        try:
            key = SSHKey(key_string)
            key.parse()
            if not key.comment:
                raise ValueError("No name set. Please add a name to your key.")
            return key
        except InvalidKeyError as err:
            raise DatabaseError(f"Invalid SSH key: {err}")

    def db_value(self, ssh_key: SSHKey):
        if ssh_key is None:
            return None
        str_value = ssh_key.keydata
        return super().db_value(str_value)

    def python_value(self, value):
        str_value = super().python_value(value)
        if str_value is None:
            return None
        return SSHKeyField.parse_ssh_key(str_value)


class BaseModel(Model):
    @classmethod
    def get_all(cls):
        return cls.select()

    class Meta:
        database = _db
        legacy_table_names = False


class BaseObject(BaseModel):
    creation_date = DateTimeField(default=datetime.datetime.now)
    last_date = DateTimeField(default=None, null=True)


class LockableObject(BaseObject):
    locked = IntegerField(default=0)

    @contextmanager
    def lock(self, timeout_sec=1800):
        begin = time()
        recursive = False
        while self.locked != 0 and psutil.pid_exists(self.locked):
            if os.getpid() == self.locked:
                # Recursive lock
                recursive = True
                break
            now = time()
            if now - begin < timeout_sec:
                sleep(5)
            else:
                raise DatabaseObjectLockedError(f"Can't lock {self.name}: Object is already locked by pid {self.locked}"
                                                f" for {timeout_sec}s")
        with _db.atomic():
            # check again because race conditions might happen
            if self.locked == 0 or os.getpid() == self.locked:
                self.locked = os.getpid()
                self.save()
        try:
            yield
        finally:
            if not recursive:
                self.locked = 0
                self.save()
            # else the outer lock manager will release the lock


class User(LockableObject):
    name = CharField(unique=True)
    email = CharField(unique=True)
    max_repo_count = SmallIntegerField(default=10)
    quota = IntegerField(default=_cfg['default_repo_quota'])
    _ssh_key = SSHKeyField(null=True, column_name='ssh_key')
    _backup_ssh_key = SSHKeyField(null=True, column_name='backup_ssh_key')
    repos = None  # for type hinting

    @property
    def path(self):
        return _storage.user_path(self.name)

    @property
    def ssh_key(self):
        return self._ssh_key

    @ssh_key.setter
    def ssh_key(self, key):
        if isinstance(key, str):
            key = SSHKeyField.parse_ssh_key(key)
        self._ssh_key = key

    @property
    def backup_ssh_key(self):
        return self._backup_ssh_key

    @backup_ssh_key.setter
    def backup_ssh_key(self, key):
        if isinstance(key, str):
            key = SSHKeyField.parse_ssh_key(key)
        self._backup_ssh_key = key

    @classmethod
    def new(cls, name: str, email: str, quota: int = None) -> 'User':
        if quota is None:
            quota = _cfg['default_user_quota']
        with _db.atomic():
            user = User._create(name=name, email=email, quota=quota)
        return user

    def delete_instance(self, **kwargs):
        with _db.atomic():
            _storage.delete_user(self.name)
            UserLog.log(self, LogOperation.DELETE_USER, str(self.name))
            return super().delete_instance(**kwargs)

    @classmethod
    def _create(cls, **query):
        name = query['name']
        if len(name) > 20:
            raise DatabaseError("User name has to be 20 characters or less")
        if not _name_regex.match(name):
            raise DatabaseError("Name may only contain these characters: [a-zA-Z0-9_]")
        try:
            cls.get(cls.name == name)
            raise DatabaseError(f"User already exists: '{name}'")
        except DoesNotExist:
            pass
        try:
            _storage.create_user(name)
            with _db.atomic():
                user = super().create(**query)
                UserLog.log(user, LogOperation.CREATE_USER, name)
        except IntegrityError:
            _storage.delete_user(name)
            raise
        return user

    @classmethod
    def get_by_name(cls, name: str) -> 'User':
        try:
            return cls.get(cls.name == name)
        except DoesNotExist:
            raise DatabaseError(f"User '{name}' does not exist")

    @classmethod
    def get_by_id(cls, uid: int) -> 'User':
        try:
            return cls.get(cls.id == uid)
        except DoesNotExist:
            raise DatabaseError(f"User with id '{uid}' does not exist")

    def get_repo_by_name(self, repo_name) -> 'Repository':
        try:
            return Repository.get((Repository.user == self) & (Repository.name == repo_name))
        except DoesNotExist:
            raise DatabaseError(f"Repo with name '{repo_name}' for user '{self.name}' does not exist")

    @property
    def repo_logs(self):
        return RepoLog.get_logs_for_user(self)

    @property
    def quota_used(self) -> int:
        size = 0
        for repo in self.repos:
            size += repo.quota_used
        return size

    @property
    def quota_used_gb(self) -> int:
        return math.floor(self.quota_used / 1000 / 1000 / 1000)

    @property
    def quota_allocated(self) -> int:
        size = 0
        for repo in self.repos:
            size += repo.quota
        return size

    @property
    def quota_allocated_gb(self) -> int:
        return math.floor(self.quota_allocated / 1000 / 1000 / 1000)

    @property
    def quota_gb(self) -> int:
        return math.floor(self.quota / 1000 / 1000 / 1000)

    @quota_gb.setter
    def quota_gb(self, new_quota):
        self.quota = new_quota * 1000 * 1000 * 1000


class Repository(LockableObject):
    name = CharField(unique=True)
    user = ForeignKeyField(User, backref='repos')
    _quota = IntegerField(column_name='quota', default=500)
    last_session_success = BooleanField(default=True)
    _append_ssh_key = SSHKeyField(null=True, column_name='append_ssh_key')
    _rw_ssh_key = SSHKeyField(null=True, column_name='rw_ssh_key')

    @property
    def path(self):
        return _storage.repo_path(self.user.name, self.name)

    @property
    def append_ssh_key(self):
        return self._append_ssh_key

    @append_ssh_key.setter
    def append_ssh_key(self, key):
        if isinstance(key, str):
            key = SSHKeyField.parse_ssh_key(key)
        self._append_ssh_key = key

    @property
    def rw_ssh_key(self):
        return self._rw_ssh_key

    @rw_ssh_key.setter
    def rw_ssh_key(self, key):
        if isinstance(key, str):
            key = SSHKeyField.parse_ssh_key(key)
        self._rw_ssh_key = key

    @classmethod
    def new(cls, user: User, repo_name: str, quota_gb: int = None) -> 'Repository':
        if quota_gb is None:
            quota_gb = math.floor(_cfg['default_repo_quota'] / 1000 / 1000 / 1000)
        repo = None
        if len(repo_name) > 20:
            raise DatabaseError("Repository name has to be 20 characters or less")
        with _db.atomic():
            count = cls.select().where(cls.user == user).count()
            if count >= user.max_repo_count:
                raise DatabaseError("Too many repositories")
            repo = cls._create(user=user, name=repo_name, _quota_gb=quota_gb)
        return repo

    @classmethod
    def _create(cls, **query):
        user = query['user']
        name = query['name']
        if not _name_regex.match(name):
            raise DatabaseError("Name may only contain these characters: [a-zA-Z0-9_]")
        quota_gb = query['_quota_gb']
        with _db.atomic() as transaction:
            _storage.create_repo(user.name, name)
            repo = super().create(**query)
            try:
                repo.quota_gb = quota_gb
            except DatabaseError:
                transaction.rollback()
                _storage.delete_repo(user.name, name)
                raise
            RepoLog.log(repo, LogOperation.CREATE_REPO, name)
        return repo

    def delete_instance(self, **kwargs):
        with _db.atomic():
            _storage.delete_repo(self.user.name, self.name)
            RepoLog.log(self, LogOperation.DELETE_REPO, str(self.name))
            return super().delete_instance(**kwargs)

    @classmethod
    def get_all_by_user(cls, user: User) -> List['Repository']:
        return cls.select().where(cls.user == user)

    @classmethod
    def get_by_name(cls, name: str, user: User) -> 'Repository':
        try:
            return cls.get((cls.name == name) & (cls.user == user))
        except DoesNotExist:
            raise DatabaseError(f"Repository with name '{name}' does not exist for user '{user.name}'")

    @classmethod
    def get_by_id(cls, id: int) -> 'Repository':
        try:
            return cls.get((cls.id == id))
        except DoesNotExist:
            raise DatabaseError(f"Repository with id '{id}' does not exist")

    @property
    def quota(self) -> int:
        return self._quota

    @quota.setter
    def quota(self, new_quota: int):
        try:
            if new_quota < 1:
                raise DatabaseError("Quota must be bigger than 0")
            repos = Repository.select().where(Repository.user == self.user)
            combined_size = 0
            for iter_repo in repos:
                combined_size += iter_repo.quota
            new_size = combined_size - self.quota + new_quota
            if new_size > self.user.quota:
                max_size = self.user.quota - (combined_size - self.quota)
                raise DatabaseError("Proposed repo size would be too large to fit user quota. "
                                    f"Maximum size would be {math.floor(max_size/1000/1000/1000)}")
            if new_size < self.quota_used:
                raise DatabaseError("Proposed repo size would be too small to fix the current repo size. "
                                    f"Minimum size would be {self.size_gb}")
            _storage.set_new_quota(self, new_quota)
            self._quota = new_quota
            self.save()
        except StorageError as e:
            raise DatabaseError(e)

    @property
    def quota_used(self) -> int:
        borg_repo = _storage.get_borg_repo(self)
        if borg_repo is None:
            return 0
        with borg_repo.open_no_lock():
            return borg_repo.quota_used

    @property
    def quota_used_gb(self) -> int:
        return math.floor(self.quota_used / 1000 / 1000 / 1000)

    @property
    def quota_gb(self):
        return math.floor(self.quota / 1000 / 1000 / 1000)

    @quota_gb.setter
    def quota_gb(self, new_quota):
        self.quota = new_quota * 1000 * 1000 * 1000

    @property
    def transaction_id(self):
        return _storage.get_repo_transaction_id(self)


class LogBase(BaseModel):
    date = DateTimeField(default=datetime.datetime.now)
    operation = LogOperationField()
    data = CharField()
    acknowledged = BooleanField(default=False)

    def format_line(self):
        date = self.date
        return f"[{date.isoformat()}] {self.operation.name} {self.data}"

    @classmethod
    def format_all_logs(cls):
        return [line.format_line() for line in cls.select()]


class UserLog(LogBase):
    user = ForeignKeyField(User, backref='logs')

    def format_line(self):
        date = self.date
        return f"[{date.isoformat()}] {self.user.name} {self.operation.name} {self.data}"

    @classmethod
    def log(cls, user: User, operation: LogOperation, data: str):
        cls.create(user=user, operation=operation, data=data)

    @classmethod
    def get_logs_for_user(cls, user):
        try:
            return cls.select().where(cls.user == user)
        except DoesNotExist:
            return []

    @classmethod
    def format_logs_for_user(cls, user):
        return [line.format_line() for line in cls.get_logs_for_user(user)]


class RepoLog(LogBase):
    repo = ForeignKeyField(Repository, backref='logs')

    def format_line(self):
        date = self.date
        return f"[{date.isoformat()}] {self.repo.user.name} {self.repo.name} {self.operation.name} {self.data}"

    @classmethod
    def log(cls, repo: Repository, operation: LogOperation, data: str):
        cls.create(repo=repo, operation=operation, data=data)

    @classmethod
    def get_logs_for_repo(cls, repo):
        try:
            return cls.select().where(cls.repo == repo)
        except DoesNotExist:
            return []

    @classmethod
    def get_logs_for_repo_with_operation(cls, repo, operation):
        try:
            return cls.select().where((cls.repo == repo) & (cls.operation == operation))
        except DoesNotExist:
            return []

    @classmethod
    def get_last_entry_for_repo_with_operation(cls, repo, operation) -> Optional['RepoLog']:
        logs = cls.get_logs_for_repo_with_operation(repo, operation)
        if len(logs) > 0:
            return logs[-1]
        return None

    @classmethod
    def get_logs_for_user(cls, user):
        try:
            return cls.select().join(Repository).where(cls.repo.user == user)
        except DoesNotExist:
            return []

    @classmethod
    def format_logs_for_repo(cls, repo):
        return [line.format_line() for line in cls.get_logs_for_repo(repo)]

    @classmethod
    def format_logs_for_user(cls, user):
        return [line.format_line() for line in cls.get_logs_for_user(user)]


class AdminLog(LogBase):
    @classmethod
    def log(cls, repo, operation: LogOperation, data: str):
        cls.create(user=repo, operation=operation, data=data)

    @classmethod
    def get_logs(cls):
        return cls.select()


def _init():
    _db.init(os.path.join(_storage.path, 'borgcube.db'))
    _db.connect()
    _db.create_tables([User, Repository, UserLog, RepoLog, AdminLog])

    _storage.assert_consistency(User.get_all())


_init()
