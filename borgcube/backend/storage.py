from pathlib import Path
import shutil
import os
import math


def folder_size(path: str):
    total = 0
    for entry in os.scandir(path):
        if entry.is_file():
            total += entry.stat().st_size
        elif entry.is_dir():
            total += folder_size(entry.path)
    return total


class StorageError(Exception):
    pass


class StorageInconsistencyError(StorageError):
    pass


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

    def calculate_repo_size(self, repo):
        size_b = folder_size(str(self.repo_path(repo.user.name, repo.name)))
        size_gb = math.ceil(size_b / 1000000000)
        repo.size_gb = size_gb
        repo.save()

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
