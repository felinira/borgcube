from contextlib import contextmanager
from pathlib import Path
import shutil

import os
from borg.repository import Repository
from borg.helpers import Error
from borg.locking import LockError
from borg.logger import setup_logging
from borg.helpers import msgpack
from borgcube.exception import StorageError, StorageInconsistencyError


setup_logging()


class BorgRepo(object):
    def __init__(self, path, lock_wait=None):
        self.path = path
        self.__repo = None
        if Repository.is_repository(path):
            self.__repo = Repository(path, lock_wait=lock_wait, create=False)

    @property
    def quota_used(self):
        if self.is_repo:
            return self._get_borg_repo_hints()[b'storage_quota_use']
        return 0

    @property
    def is_repo(self):
        return self.__repo is not None

    @property
    def __quota(self):
        return self.__repo.config.getint('repository', 'storage_quota', fallback=0)

    @__quota.setter
    def __quota(self, new_quota):
        self.__repo.config.set('repository', 'storage_quota', str(new_quota))
        self.__repo.save_config(self.__repo.path, self.__repo.config)

    def _get_borg_repo_hints(self):
        if self.is_repo:
            transaction_id = self.__repo.get_index_transaction_id()
            hints_path = os.path.join(self.path, 'hints.%d' % transaction_id)
            with open(hints_path, 'rb') as fd:
                hints = msgpack.unpack(fd)
            return hints
        return None

    @contextmanager
    def open_locked(self):
        try:
            self.__repo.open(self.__repo.path, exclusive=True)
            yield
        except LockError as e:
            raise StorageError(e)
        except Error as e:
            raise StorageError(e)
        finally:
            self.__repo.close()

    @contextmanager
    def open_no_lock(self):
        try:
            self.__repo.open(self.__repo.path, exclusive=False, lock=False)
            yield
        except Error as e:
            raise StorageError(e)
        finally:
            self.__repo.close()

    def set_new_quota_safe(self, new_quota):
        if not self.__repo:
            raise StorageError("Repository has not been initialized yet")
        with self.open_locked():
            if self.quota_used < new_quota:
                self.__quota = new_quota
            else:
                raise StorageError(f"Can't set new quota: New quota too small. "
                                   f"Smallest quota would be {self.quota_used}")

    def get_quota_used(self):
        if not self.__repo:
            raise StorageError("Repository has not been initialized yet")


class Storage(object):
    def __init__(self, path):
        self.path = Path(path)
        self.backups_path = self.path.joinpath('backups')
        self.home_path = self.path.joinpath('home')
        self.ssh_path = self.home_path.joinpath('.ssh')
        self.create_if_needed()

    def create_if_needed(self):
        self.path.mkdir(exist_ok=True)
        self.backups_path.mkdir(exist_ok=True)
        self.home_path.mkdir(exist_ok=True)
        self.ssh_path.mkdir(exist_ok=True, mode=0o700)

    def create_user(self, user_name):
        self.user_path(user_name).mkdir()

    def delete_user(self, user_name):
        shutil.rmtree(self.user_path(user_name))

    def user_path(self, user_name):
        return self.backups_path.joinpath(user_name)

    def repo_path(self, user_name, repo_name):
        return self.backups_path.joinpath(user_name).joinpath(repo_name)

    def create_repo(self, user_name, repo_name):
        self.repo_path(user_name, repo_name).mkdir()

    def delete_repo(self, user_name, repo_name):
        shutil.rmtree(self.repo_path(user_name, repo_name))

    def get_borg_repo(self, repo):
        borg_repo = BorgRepo(self.repo_path(repo.user.name, repo.name))
        if borg_repo.is_repo:
            return borg_repo
        return None

    def get_quota_used(self, repo):
        borg_repo = self.get_borg_repo(repo)
        with borg_repo.open_no_lock():
            return borg_repo.quota_used

    def set_new_quota(self, repo, new_quota):
        borg_repo = self.get_borg_repo(repo)
        if borg_repo is None:
            return
        with borg_repo.open_locked():
            if borg_repo.quota_used <= new_quota:
                borg_repo.set_new_quota_safe(new_quota)

    def assert_consistency_for_user(self, user):
        user_path = self.user_path(user.name)
        if not user_path.is_dir():
            raise StorageInconsistencyError(f"Storage for user '{user.name}' is missing")

        repos = user.repos
        if len(repos) > user.max_repo_count:
            raise StorageInconsistencyError(f"User '{user}' is allowed to have maximum of {user.max_repo_count} "
                                            f"repos but {len(repos)} were found")

        for repo in repos:
            repo_path = user_path.joinpath(repo.name)
            if not repo_path.is_dir():
                raise StorageInconsistencyError(f"Repository '{repo.name}' for user '{user.name}' is missing")

        for file in user_path.iterdir():
            if not file.is_dir():
                raise StorageInconsistencyError(f"Stale file '{file.name}' found in user directory of '{user.name}'")
            if file.name not in [repo.name for repo in repos]:
                raise StorageInconsistencyError(f"Stale repository '{file.name}' found "
                                                f"in user directory of '{user.name}'")

    def assert_consistency(self, users):
        for user in users:
            self.assert_consistency_for_user(user)
