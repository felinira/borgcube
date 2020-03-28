from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from email.message import EmailMessage
from subprocess import Popen, PIPE
from typing import Optional, List

from borgcube.backend.config import cfg as _cfg
from borgcube.backend.model import Repository, RepoLog, User
from borgcube.enum import LogOperation
from borgcube.exception import NotificationSendmailError


class BaseNotification(ABC):
    @abstractmethod
    def send_too_old_backups_notification(self, repos: List[Repository], logs: List[Optional[RepoLog]]):
        pass


class EmailNotification(object):
    def __init__(self, user):
        self.user = user
        self.from_mail = _cfg['notification_mail']

    def _send_mail(self, to_email, subject, body):
        msg = EmailMessage()
        msg.set_content(body)
        msg["From"] = self.from_mail
        msg["To"] = to_email
        msg['Subject'] = subject
        p = Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate(msg.as_bytes())
        if p.returncode != 0:
            raise NotificationSendmailError(stderr)

    def dispatch_too_old_backups_notification(self, repos: [Repository], logs: [Optional[RepoLog]], num_days: int):
        if len(repos) == 1:
            subject = f"[{_cfg['server_name']}] 1 Backup is out of date"
        else:
            subject = f"[{_cfg['server_name']}] {len(repos)} Backups are out of date"
        body = f"Your backups on {_cfg['server_name']} are out of date. The following repositories didn't have at" \
               f"least one successful 'borg serve' invocation in the last {num_days}:\n\n"

        for idx in range(len(repos)):
            repo: Repository = repos[idx]
            log: Optional[RepoLog] = logs[idx]

            body += f"* {repo.name}: "
            if log:
                body += f"Last successful backup on {log.date}"
            else:
                body += f"No successful backup on record"
            body += "\n"
        body += f"\nIf you have any questions please don't hesitate to contact your server administrator: " \
                f"{_cfg['admin_contact']}\n\nWe wish you a good day. Please fix your backups."
        to_email = self.user.email
        self._send_mail(to_email, subject, body)


class NotificationDispatcher(object):
    def __init__(self, notification_classes: List[BaseNotification] = None):
        if notification_classes is None:
            notification_classes = [EmailNotification]
        self.notification_classes = notification_classes

    def dispatch_too_old_backups_notifications(self, users: Optional[List[User]] = None, num_days: int = 2):
        if users is None:
            users = User.get_all()
        now = datetime.now()
        check_date = now - timedelta(days=num_days)
        for user in users:
            too_old_repos = []
            too_old_repo_logs = []
            for repo in Repository.get_all_by_user(user):
                too_old = False
                log = None
                if repo.creation_date < check_date:
                    log = RepoLog.get_last_entry_for_repo_with_operation(repo, LogOperation.SERVE_MODIFY_SUCCESS)
                    if not log:
                        too_old = True
                    else:
                        if log.date < check_date:
                            too_old = True
                if too_old:
                    too_old_repos.append(repo)
                    too_old_repo_logs.append(log)
            if len(too_old_repos) > 0:
                for cls in self.notification_classes:
                    notification = cls(user)
                    notification.dispatch_too_old_backups_notification(too_old_repos, too_old_repo_logs, num_days)

    def cron(self):
        self.dispatch_too_old_backups_notifications()
