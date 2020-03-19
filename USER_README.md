# Welcome to borgcube

You have a new account on a borgcube host and want to know how to use it? This guide is for you!

## First Login

### Prerequisites

Your server administrator should have sent you credentials to log in to your new borgcube account.
You have already sent your SSH public key to your borgcube admin and they set it up.

### First login

To login simply run
```shell script
$ ssh borg@<borgcube_host>
```

You will be greeted by the borgcube host. You now need to create a repository:
```shell script
repo create <name> <quota in GB>
```

for <name> substitute your repository name (choose a name to identify your machine).
for <quota in GB> set a value in GB how big you want your repository to be. You can't set it higher than your user quota.

Your free user quota can be viewed by issuing the `user` command and looking for the "Quota alloc" value.

Your new repo also needs an SSH key. You need to generate a new one on your client machine:
```shell script
$ ssh-keygen -t ed25519 -f ~/.ssh/borgcube
```

Add it by:
```shell script
repo keys set_rw_key <ssh pubkey>
```

Substitute <ssh pubkey> with the contents of your `~/.ssh/borgcube.pub` file.

Now you can create a repository:
```shell script
borg init -e repokey-blake2 borg@<borgcube_host>:<repo_name>
```

Substitute <borgcube_host> for your borgcube hostname and <repo_name> for your repository name. `borg init` should
finish successfully. If not please consult your server administrator.

Now use borg as usual. Consolt the [Borg documentation](https://borgbackup.readthedocs.io/en/stable/usage/create.html).
You can create a new backup by issuing:
```shell script
borg [common options] create [options] borg@<borgcube_host>:<repo_name> [PATH...]
```

Have fun using borgcube!