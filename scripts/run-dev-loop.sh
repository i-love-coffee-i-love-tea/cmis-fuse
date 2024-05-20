#!/bin/bash
#
# Helper script for development. It listens for changes
# to the cmis-fuse.py file and executes the following actions,
# when the file was written to:
#
# - kills all python instances 
# 
#
# requirements:
#     apt install inotify-tools
#
set -e

wait_for_file_modify_event() {
    TARGET_FILE="$1"
	WATCH_DIR="$(dirname $TARGET_FILE)"
	WATCH_FILENAME="$(basename $TARGET_FILE)"
	inotifywait -m -e modify "$WATCH_DIR"  | \
    	while read path event filename; do
    	    if [ "$filename" = "$WATCH_FILENAME" ]; then
        	    echo "$filename was written to in $path";
        	    break
       		fi
   		done
}

run_after_mount() {
    # run test commands to a first basic visual confirmation that it works
    # or to test the feature you're working on
	ls -la "$MOUNT_PATH" --color
	ls -la "$MOUNT_PATH"/Knowledge\ Provider --color
}

on_file_modified() {
	# restart fuse fs
    echo "executing file modify hook"
    ps aux | grep "$FUSE_IMPL_SCRIPT.*\?$MOUNT_PATH" | grep -v -e grep -v -e bash  | awk '{print $2}' | xargs kill
    echo "running $FUSE_IMPL_SCRIPT"
	python3 "$FUSE_IMPL_SCRIPT" "$CMIS_BROWSER_URL" "$CMIS_REPO_ID" "$MOUNT_PATH" 
    run_after_mount
}


if [ "$#" -lt 4 ]; then
    echo "usage: $0 <fuse-implementation-script> <cmis-browser-url> <cmis-repo-id> <mount-path>"
    exit
fi


FUSE_IMPL_SCRIPT="$1"
CMIS_BROWSER_URL="$2"
CMIS_REPO_ID="$3"
MOUNT_PATH="$4"
mkdir -p "$MOUNT_PATH" 2>/dev/null

while true; do 
    on_file_modified
	wait_for_file_modify_event "$FUSE_IMPL_SCRIPT"
done
