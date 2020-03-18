import datetime
import os
from peewee import *
from peewee import IntegerField
from sshpubkeys import SSHKey, InvalidKeyError
from contextlib import contextmanager
from enum import Enum
import re

from .storage import Storage
from .config import cfg as _cfg


_db = SqliteDatabase(None)
_storage = Storage(_cfg['storage_path'])
_name_regex = reg = re.compile('^[a-zA-Z0-9_]+$')


class DatabaseError(Exception):
    pass


class LogOperation(Enum):
    CREATE_REPO = 1
    DELETE_REPO = 2
    SERVE_REPO_BEGIN = 3
    SERVE_REPO_LOG = 4
    SERVE_REPO_SUCCESS = 5
    SERVE_REPO_ABORT = 6
    CHANGE_REPO_QUOTA = 7
    CHANGE_REPO_SSH_KEY = 8
    CREATE_USER = 9
    DELETE_USER = 10
    CHANGE_USER_QUOTA = 11
    CHANGE_USER_SSH_KEY = 12


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
    locked = BooleanField(default=False)

    @contextmanager
    def lock(self):
        with _db.atomic():
            if not self.locked:
                self.locked = True
                self.save()
            else:
                raise DatabaseError(f"Can't lock {self}: Object is already locked")
        try:
            yield
        finally:
            self.locked = False
            self.save()


class User(LockableObject):
    name = CharField(unique=True)
    email = CharField(unique=True)
    max_repo_count = SmallIntegerField(default=10)
    quota_gb = IntegerField(default=_cfg['default_repo_quota_gb'])
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
    def new(cls, name: str, email: str, quota_gb: int = None) -> 'User':
        if quota_gb is None:
            quota_gb = _cfg['default_user_quota_gb']
        with _db.atomic():
            user = User._create(name=name, email=email, quota_gb=quota_gb)
        return user

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
            size += repo.size_gb
        return size

    @property
    def quota_allocated(self) -> int:
        size = 0
        for repo in self.repos:
            size += repo.quota_gb
        return size


class Repository(LockableObject):
    name = CharField(unique=True)
    user = ForeignKeyField(User, backref='repos')
    _quota_gb = IntegerField(column_name='quota', default=500)
    size_gb = IntegerField(default=0, null=True)
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
            quota_gb = _cfg['default_repo_quota_gb']
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
            super().delete_instance(**kwargs)

    @classmethod
    def get_by_name(cls, name: str, user: User) -> 'Repository':
        try:
            return cls.get((cls.name == name) & cls.user == user)
        except DoesNotExist:
            raise DatabaseError(f"Repository with name '{name}' does not exist for user '{user.name}'")

    @classmethod
    def get_by_id(cls, id: int) -> 'Repository':
        try:
            return cls.get((cls.id == id))
        except DoesNotExist:
            raise DatabaseError(f"Repository with id '{id}' does not exist")

    @property
    def quota_gb(self) -> int:
        return self._quota_gb

    @quota_gb.setter
    def quota_gb(self, new_quota: int):
        with self.lock():
            _storage.calculate_repo_size(self)
            with _db.atomic():
                repos = Repository.select().where(Repository.user == self.user)
                combined_size = 0
                for iter_repo in repos:
                    combined_size += iter_repo.quota_gb
                new_size = combined_size - self.quota_gb + new_quota
                if new_size > self.user.quota_gb:
                    max_size = self.user.quota_gb - (combined_size - self.quota_gb)
                    raise DatabaseError("Proposed repo size would be too large to fit user quota. "
                                        f"Maximum size would be {max_size}")
                if new_size < self.size_gb:
                    raise DatabaseError("Proposed repo size would be too small to fix the current repo size. "
                                        f"Minimum size would be {self.size_gb}")
                self._quota_gb = new_quota
                self.save()


class LogBase(BaseModel):
    date = DateTimeField(default=datetime.datetime.now)
    operation = LogOperationField()
    data = CharField()
    acknowledged = BooleanField(default=False)

    def format_line(self):
        date = self.date
        return f"[{date.isoformat()}] {self.operation.name} {self.data}\n"

    @classmethod
    def format_all_logs(cls):
        return [line.format_line() for line in cls.select()]


class UserLog(LogBase):
    user = ForeignKeyField(User, backref='logs')

    @classmethod
    def log(cls, user: User, operation: LogOperation, data: str):
        cls.create(user=user, operation=operation, data=data)

    @classmethod
    def get_logs_for_user(cls, user):
        return cls.select().where(cls.user == user)

    @classmethod
    def format_logs_for_user(cls, user):
        return [line.format_line() for line in cls.get_logs_for_user(user)]


class RepoLog(LogBase):
    repo = ForeignKeyField(Repository, backref='logs')

    @classmethod
    def log(cls, repo: Repository, operation: LogOperation, data: str):
        cls.create(repo=repo, operation=operation, data=data)

    @classmethod
    def get_logs_for_repo(cls, repo):
        return cls.select().where(cls.repo == repo)

    @classmethod
    def get_logs_for_user(cls, user):
        return cls.select().join(Repository).where(cls.repo.user == user)

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
