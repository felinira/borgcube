# borgcube

This is borgcube, a repository server for borgbackup.

# Features
* Administration
  * Add / Delete users
  * Configure Quotas for users
* User self service
  * Change ssh keys
  * Add and delete repositories
  * Set custom ssh keys for each repo
  * Set custom quota for each repo
  * modify old backup age notification days for each repo
* Notifications
  * Send email notifications if a backup client hasn't modified the repository after some amount of days

# Installation

1. Install borgcube (preferably in an isolated virtual machine):
```shell script
git clone https://github.com/felinira/borgcube.git`
sudo python3 setup.py install
```

2. Add borg system user (Debian example)
```shell script
sudo adduser --system borg --shell /bin/sh
sudo -u borg touch /home/borg/.hushlogin
```

3. Configure config.yaml.example, especially the storage directory and authorized_keys directory:
```shell script
sudo mkdir -p /etc/borgcube
sudo install -Dm644 config.yaml.example /etc/borgcube/config.yaml
sudo vi /etc/borgcube/config.yaml
```

4. Configure sshd_config:
```text
PermitUserEnvironment yes

Match User borg
        X11Forwarding no  
        AllowTcpForwarding no
        AuthorizedKeysFile /mnt/borg/authorized_keys
```
*Please make sure to set the same path to authorized_keys as in config.yaml. Also check all file/folder permissions 
against your SSH security policy.*

5. Try it out:
```shell script
sudo -u borg borgcube admin users add test
sudo -s borg borgcube admin shell test
user key set id-rsa AAAA[.......]
exit
```

6. Execute on the remote machine:
```shell script
ssh -T borg@borgcube_host
```
and you should end up in a borgcube shell.

7. Now you can create repos: `repo create testrepo 100`
8. And connect with borg: `borg init --encryption <enc> borg@borgcube_host:/mnt/borg/backups/test/testrepo`

Consult the borg documentation for further details: [Borg Documentation](https://borgbackup.readthedocs.io/en/stable/)

9. You can view the server logs with `borgcube log`. Users can view the logs with the shell and the `log` command.

10. Configure cron

You need to have a working `sendmail` setup on your server to use the notification feature. You can probably just
install postfix with a smarthost configuration. For more information consult your distribution documentation. Borgcube
expects to find sendmail in `/usr/sbin/sendmail` and will send mail as the user configured by the config file.

Setup your cron on the server to run `borgcube cron` once a day. This sends old age backup notifications and cleans up
your logs. You can run it as root. It will simply drop privileges to your configured user. If you don't want that just
run `borgcube cron` as your borg user.
```shell script
sudo cat > /etc/cron.daily/borgcube << EOF
#!/bin/sh
/usr/local/bin/borgcube cron
EOF
sudo chmod +x /etc/cron.daily/borgcube
```

# Troubleshooting

## I can't run backup because SSH is always using my user key!

This is because SSH tries all identity files by default, including the key specified by -i.

To prevent this add the following option to your ~/.ssh/config.
```
Match borgcube_host_backup
    IdentityFile repokey
    IdentitiesOnly yes
```

You also need to check if you have a `Match *` directive in your SSH config. If you include `IdentityFile` directives in it you need to exclude the borgcube host from the directive like this:
```
Match * !borgcube_host
    IdentityFile id_ed25519
    ...
```
