#!/bin/sh
#
# helper script to run cmis-fuse.py in a virtual environment
# it prepares a venv under /tmp if it isnt already initialized

set -e

create_venv() {
	if [ ! -d "$VENV_DIR" ]; then
        echo "creating venv directory '$VENV_DIR'"
		mkdir -p "$VENV_DIR"
        echo "initializing venv"
		python3 -m venv "$VENV_DIR"
		$VENV_DIR/bin/pip install $CMISLIB_DIR
        $VENV_DIR/bin/pip install fuse-python
        $VENV_DIR/bin/pip install urllib3
	fi
}


CMISLIB_DIR=~/src/chemistry-cmislib
VENV_DIR=/tmp/cmis-fuse-venv

FUSE_IMPL_SCRIPT="$1"
CMIS_BROWSER_URL="$2"
CMIS_REPO_ID="$3"
MOUNT_PATH="$4"

create_venv "$VENV_DIR"

if [ ! -d "$MOUNT_PATH" ]; then
    echo "creating repository mount point '$MOUNT_PATH'"
	mkdir -p "$MOUNT_PATH"
fi

echo "using fuse implementation in '$FUSE_IMPL_SCRIPT'"

if $VENV_DIR/bin/python3 $FUSE_IMPL_SCRIPT $CMIS_BROWSER_URL $CMIS_REPO_ID $MOUNT_PATH; then
	echo "repository is mounted to $MOUNT_PATH"
	echo "to unmount, kill the process"
else
    echo "failed"
    echo "potentially active, blocking mounts"
    echo "q: $FUSE_IMPL_SCRIPT $MOUNT_PATH"
    ps aux |grep "$FUSE_IMPL_SCRIPT.*\?$MOUNT_PATH" | grep -v -e grep
fi
