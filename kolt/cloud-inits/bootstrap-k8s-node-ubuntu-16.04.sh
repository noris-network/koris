text/x-shellscript
#!/bin/sh
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# Specify the Kubernetes version to use.
