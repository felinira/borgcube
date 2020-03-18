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

# Installation

1. Install borgcube (preferably in an isolated virtual machine):
```
git clone https://github.com/felinira/borgcube.git`
sudo python3 setup.py install
```

2. Add borg system user (Debian example)
```
sudo adduser --system borg --shell /usr/local/bin/borgcube
sudo -u borg touch /home/borg/.hushlogin
```
*Important: You have to set the shell of the user to borgcube, otherwise the user has full shell access.*

3. Configure config.yaml.example, especially the storage directory and authorized_keys directory:
```
sudo mkdir -p /etc/borgcube
sudo install -Dm644 config.yaml.example /etc/borgcube/config.yaml
sudo vi /etc/borgcube/config.yaml
```

4. Configure sshd_config:
```
PermitUserEnvironment yes

Match User borg
        X11Forwarding no  
        AllowTcpForwarding no
        PermitTTY no
        AuthorizedKeysFile /mnt/borg/authorized_keys
```
*Please make sure to set the same path to authorized_keys as in config.yaml. Also check all file/folder permissions against your SSH security policy.*

5. Try it out:
```
sudo -u borg borgcube admin users add test
sudo -s borg borgcube admin shell test
user key set id-rsa AAAA[.......]
exit
```

6. Execute on the remote machine:
```
ssh -T borg@borgcube_host
```
and you should end up in a borgcube shell.

7. Now you can create repos: `repo create testrepo 100`
8. And connect with borg: `borg init --encryption <enc> borg@borgcube_host:/mnt/borg/backups/test/testrepo`

Consult the borg documentation for further details: (https://borgbackup.readthedocs.io/en/stable/)[Borg Documentation]
