# cmis-fuse

CMIS FUSE implementation for development. Mounts a CMIS repository into your filesystem.

NOT RECOMMENDED FOR USE IN PRODUCTION ENVIROMENTS 


## Requirements

python packages
- fuse-python
- urllib3
- cmislib

## Development status

This is a mere prototype implementation.

My goal was to see how well it would work and to try to overcome my dependency
on the apache chemistry CMIS workbench for testing during development of CMIS services.

What works and what doesn't

works:

- listing and changing directories
- cp to and from the repository (=reading/writing files)
- mkdir/rmdir
- touch/rm
- listfattr and getfattr to read cmis object properties

Of course all other filesystem tools and programs accessing
filesystems like rsync, for example, can also be used.


doesn't work:
- any kind of linking


Problems for usage in production:
- uses very naiive caching algorithms:
  - during upload and download of documents temp files are written to /tmp
    This means to upload a 10GB document, there needs to be an additional 10GB of free disk space in /tmp 
  - the root folder children are cached
  - cmis objects are cached with a timeout, but never removed from the cache
- may also have threading issues
- amount of CMIS API request seems excessive





## Mounting a repository 

### preparation

install chemistry-cmislib python3 module from source  
    $ mkdir ~/src
    $ cd ~/src
    $ git clone https://github.com/i-love-coffee-i-love-tea/chemistry-cmislib
    $ pip install ~/src/chemistry-cmislib

### without virtual environment

install python modules 
    $ apt install python3-fuse python3-urllib3
mount a CMIS repository
    $ python3 cmis-fuse.py <cmis-browser-url> <repository-id> <mountpoint>


### in a python virtual environment

mount a repository
	$ cd scripts
    $ ./run-dev-loop.sh ../cmis-fuse.py cmis-browser-url> <repository-id> <mountpoint>


### dev loop helper

mount the filesystem once and remount it if the implementation script is modified

	$ cd scripts
    $ ./run-dev-loop.sh ../cmis-fuse.py <cmis-browser-url> <repository-id> <mountpoint>

example

	$ ./run-dev-loop.sh ../cmis-fuse.py http://192.168.0.214:8090/browser ZPRZXS43UMVWXYML4IRBFA4TPORXXYLY /tmp/repo


