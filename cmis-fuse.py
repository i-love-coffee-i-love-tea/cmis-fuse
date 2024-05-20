#!/usr/bin/env python
#
#    This program can be distributed under the terms of the GNU LGPL.
#    See the file COPYING.
#

import sys, os, io, stat, errno
import logging
import time
import tempfile
import threading 
from datetime import datetime
from cmislib import CmisClient
from cmislib.browser.binding import BrowserBinding

# Andrew Straw write: pull in some spaghetti to make this stuff work without fuse-py being installed
try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse
fuse.fuse_python_api = (0, 2)

logging.basicConfig(filename='/tmp/cmis-fuse.log',
                filemode='a',
                format='%(asctime)-8s,%(msecs)03d %(name)s %(levelname)-7s %(lineno)d:%(funcName)-25s %(message)s',
                datefmt='%H:%M:%S',
                level=logging.INFO)

CACHE_SECONDS=600


# used to buffer file during upload
# should be improved to directly write to http stream
class CmisFileBuffer:
    def __init__(self, max_buffer_size: int = 0):
        self.lock = threading.Lock()
        self.file = tempfile.NamedTemporaryFile(mode='ab')
        self.max_buffer_size = max_buffer_size
        self.buffer = io.BytesIO()
        self.limit_exceeded = False


    def read(self, size: int = -1):
        
        with self.lock:
            if self.buffer.getbuffer().nbytes > 0:
                return self.buffer.getvalue()

            return self.file.read(size)

    def write(self, data: bytes, offset: int = None):
        

        with self.lock:
            if offset is not None:
                self.file.seek(offset)

            self.buffer.write(data)

            if self.buffer.getbuffer().nbytes > self.max_buffer_size:
                self.dump_to_file()

            #if offset is not None:
            #    self.file.seek(0, os.SEEK_END)


    def is_limit_exceeded(self, data):
        return self.buffer.getbuffer().nbytes + len(data) <= self.max_buffer_size

    def dump_to_file(self):
        self.file.write(self.buffer.getvalue())
        self.file.flush()  # make sure all data is written to disk

        # Reset the in-memory buffer
        self.buffer = io.BytesIO()

    def close(self):
        if self.buffer.getbuffer().nbytes > 0:
            self.dump_to_file()
        self.file.close()


class Cmis:
    
    def __init__(self, url, repo):
        print("cmis url: %s" % url)
        client = CmisClient(url, None, None, binding=BrowserBinding())
        print("fetching repository info for repo %s" % repo)
        self.repo = client.getRepository(repo)
        
        self.rootFolder = self.repo.rootFolder
        self._cache = {}
        self._cached_root_children = None
        self._cache_times = {}
        self._cached_folders = {}
        print("mounting repository %s" % self.repo.getRepositoryName())

    def getRootFolderChildren(self):
        now = time.time()
        if self._cached_root_children is None or now < self._cache_times['root_children'] + CACHE_SECONDS:
            self._cached_root_children = self.rootFolder.getChildren()
            self._cache_times['root_children'] = now
	
        return self._cached_root_children
            

    def invalidateCache(self, path):
        self._cache.pop(path, None)
        # invalidate parent
        self._cache.pop(os.path.dirname(path), None)

    # files in the root directory begin with '//'
    # directories in the root directory begin with '/'
    def cmisPathIsRootDirFile(self, path):
        return path.startswith("//")



    # for resolving the path argument value of file io functions
    # to a cmis object
    def getObjectByPath(self, path):

        now = time.time()
        # if the object is in the cache and the time is less than the expiry time,
        # return the cached result
        if path in self._cache:
            if now < self._cache[path][0]:
                return self._cache[path][1]

        folder = self.getFolderByPath(path)

        if path in folder.getPaths():
            self._cache[path] = (now + CACHE_SECONDS, folder)
            return folder

        for child in folder.getChildren():
            fixedChildPaths = [p.replace("//","/") for p in child.getPaths()]
            if path in fixedChildPaths:
                self._cache[path] = (now + CACHE_SECONDS, child)
                return child
        return None

    def getBaseTypeId(self, cmisObject):
         return cmisObject.getProperties()['cmis:baseTypeId']

    def isFolder(self, cmisObject):
        return self.getBaseTypeId(cmisObject) == 'cmis:folder'

    def isDocument(self, cmisObject):
        return self.getBaseTypeId(cmisObject) == 'cmis:document'

    def getFolderByPath(self, path):

        if path not in self._cached_folders:
            self._cached_folders[path] = self.getFolderByPathV1(path)

        return self._cached_folders[path]

    # without optimization
    def getFolderByPathV1(self, path):

        path = path[1:len(path)]
        parts = path.split("/")
        children = self.getRootFolderChildren()
        partIdx = 0
        lastFolderInPath = None
        # lookup every part of the path to finally get a reference to the basename object
        while partIdx < len(parts):
            part = parts[partIdx]

            # find matching cmis object for the path part
            for child in children:
                # if it is a folder, get its children to resolve the next part
                if self.isFolder(child):
                    if parts[partIdx] == child.getName():
                        # set children for next part iteration
                        children = child.getChildren() 
                        lastFolderInPath = child
                        break # for
            partIdx += 1
        if lastFolderInPath is None:
           lastFolderInPath = self.rootFolder
        return lastFolderInPath


class CmisFS(Fuse):

    def __init__(self, *args, url=None, repo=None, **kw):
        self.cmis = Cmis(url, repo)
        self.files = {}
        self.downloadedFiles = {}
        self.lock = threading.Lock()
        print(*args)
        #del kw['url']
        #del kw['repo']
        usage="""
CMIS FUSE implementation

""" + Fuse.fusage
        Fuse.__init__(self, *args, **kw)
        #Fuse.__init__(self, [],
        #              version="%prog " + fuse.__version__,
        #              dash_s_do='setsingle',
        #              usage=usage)

    def mapAttrs(self, st, cmisObject):
        props = cmisObject.getProperties()

        if 'cmis:creationDate' in props:
           st.st_ctime = int(props['cmis:creationDate'].strftime('%s'))
        if 'cmis:lastModificationDate' in props:
           st.st_mtime = int(props['cmis:lastModificationDate'].strftime('%s'))

        if self.cmis.isFolder(cmisObject):
            st.st_mode = stat.S_IFDIR | 0o755
            st.st_nlink = len(cmisObject.getChildren())
        elif self.cmis.isDocument(cmisObject):
            st.st_mode = stat.S_IFREG | 0o666
            st.st_nlink = len(cmisObject.getPaths())
            st.st_size = props['cmis:contentStreamLength']
        return st
    def getattr(self, path):
        st = fuse.Stat() 
        if path == '/':
            st.st_mode = stat.S_IFDIR | 0o755
            st.st_nlink = 2
        else:
            cmisObject = self.cmis.getObjectByPath(path)
            if cmisObject is None:
                return -errno.ENOENT
            self.mapAttrs(st, cmisObject)  
        return st

    def readdir(self, path, offset):
        dirents = ['.', '..']

        children = []
        if path == '/':
            children = self.cmis.getRootFolderChildren()
        else:
            children = self.cmis.getFolderByPath(path).getChildren()

        for child in children:
            dirents.append(child.name.replace('/',''))

        # + [name.encode('utf-8')
        #                      for name in self.sftp.listdir(path)]
        for r in  dirents:
            yield fuse.Direntry(r)

    def access(self, path, mode):
        return -errno.ENOSYS

    def open(self, path, flags):
        return


    def read(self, path, size, offset):
        
        # offset not supported
        #if offset > 0:
        #    return -errno.ENOENT
        with self.lock:
            if path not in self.downloadedFiles:
                cmisObject = self.cmis.getObjectByPath(path)
                if cmisObject is None:
                    return -errno.ENOENT

                try:
                    stream = cmisObject.getContentStream()
                except Error:
                    pass
        
                buf = stream.read()
                stream.close()
                self.downloadedFiles[path] = buf
            
        # read from downloaded file
        return self.downloadedFiles[path][offset:offset+size]

    def write(self, path, buf, offset):
        if offset == 0:
            if path not in self.files:
                self.files[path] = CmisFileBuffer()
                self.files[path].write(buf, offset)
        else:
            self.files[path].write(buf, offset)
        return len(buf)

    def release(self, path, flags):
        if path not in self.files and path not in self.downloadedFiles:
            return
        if path in self.downloadedFiles:
            del self.downloadedFiles[path]
            return

        name = os.path.basename(path)
        dirname = os.path.dirname(path)
        parentFolder = self.cmis.getFolderByPath(dirname)
        cmisObject = self.cmis.getObjectByPath(path)
        if path in self.files.keys():
            buf = self.files[path]
            try:
                x =  parentFolder
                with open(buf.file.name, 'rb') as f:
                    try:
                        cmisObject.setContentStream(f)
                    finally:
                        buf.close()
                        del self.files[path]
            finally:
                buf.close()
               

    def getxattr(self, path, name, size):
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT
        props = cmisObject.getProperties()
        if name not in props:
            return -errno.ENODATA

        val = str(props[name])
        if size == 0:
            # We are asked for size of the value.
            return len(val)
        return val

    def listxattr(self, path, size):
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT

        # We use the "user" namespace to please XFS utils
        aa = ["user." + p for p in cmisObject.getProperties()]

        if size == 0:
            # We are asked for size of the attr list, i.e. joint size of attrs
            # plus null separators.
            return len("".join(aa)) + len(aa)
        return aa

    def rmdir(self, path):
        self.cmis.invalidateCache(path)
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT
        cmisObject.delete()
        self.cmis.invalidateCache(path)

    def mkdir(self, path, mode):
        self.cmis.invalidateCache(path)
        dirname = os.path.dirname(path)
        containingFolder = self.cmis.getFolderByPath(dirname)
        # remove leading slash
        path = path[1:len(path)]
        parts = path.split("/")
        folderName = parts[len(parts)-1]
        folder = self.cmis.repo.createFolder(containingFolder, folderName)

    def mknod(self, path, mode, dev):
        self.cmis.invalidateCache(path)
        parentFolder = self.cmis.getFolderByPath(path)
        if parentFolder is None:
            return -errno.ENOENT
        name = os.path.basename(path)
        cmisDocument = parentFolder.createDocument(name)
        if cmisDocument is None:
            return -errno.ENOENT

        #return 0

    def readlink(self, path):
        return -errno.ENOSYS

    def unlink(self, path):
        self.cmis.invalidateCache(path)
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT
        cmisObject.delete()
        self.cmis.invalidateCache(path)

    def symlink(self, path, target_path):
        self.cmis.invalidateCache(path)
        if not path.startswith(self.fuse_args.mountpoint):
            return -errno.ENOSYS
        else:
            # todo: create relation
            return -errno.ENOSYS


    def renameDocument(self, path, target_path):
        True


    # must cover all combinations of source and target, which could
    # be 
    #    - directories or files
    #    - the target doesn't have to exist 
    #       - in this case the dirname of the target must exist
    # also move and rename are separate cmis operations
    # 
    def rename(self, path, target_path):
        basename1 = os.path.basename(path)
        dirname1 = os.path.dirname(path)
        basename2 = os.path.basename(target_path)
        dirname2 = os.path.dirname(target_path)
        cmisObject1 = self.cmis.getObjectByPath(path)
        parentFolder = self.cmis.getFolderByPath(path)
        # validate existence of src object
        if cmisObject1 is None:
            return -errno.ENOENT
        # fetch target object
        cmisObject2 = self.cmis.getObjectByPath(target_path)
        targetFolder = None
        # check if target object exists and is a dir
        if cmisObject2 is not None and self.cmis.isFolder(cmisObject2):
            targetFolder = cmisObject2
        else:

            # check if basedir object of target path exists
            cmisObject2 = self.cmis.getFolderByPath(dirname2)
            if cmisObject2 is not None and self.cmis.isFolder(cmisObject2):
                targetFolder = cmisObject2

        # move/rename
        if targetFolder is not None:
            # move
            cmisObject1.move(parentFolder, targetFolder)
            # rename
            if basename1 != basename2:
                cmisObject1.updateProperties({'cmis:name': basename2})
            self.cmis.invalidateCache(path)
            self.cmis.invalidateCache(target_path)
            #self.cmis.invalidateCache(dirname2)
        else:
            return -errno.ENOENT

    def link(self, path, path1):
        return -errno.ENOSYS
        #self.cmis.invalidateCache(path)

    def chmod(self, path, mode):
        #self.cmis.invalidateCache(path)
        #return -errno.ENOSYS
        return

    def chown(self, path, user, group):
        #self.cmis.invalidateCache(path)
        #return -errno.ENOSYS
        return

    def truncate(self, path, len):
        self.cmis.invalidateCache(path)
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT
        cmisObject.deleteContentStream()

    def utime(self, path, times):
        cmisObject = self.cmis.getObjectByPath(path)
        if cmisObject is None:
            return -errno.ENOENT
        date_fmt='%Y-%m-%d %H:%M:%S.%f'
        date = datetime.now().strftime(date_fmt)
        props = {'cmis:lastModificationDate': date}
        try:
            # not always supported
            cmisObject.updateProperties(props)
        except:
            pass

    def utimens(self, path):
        return -errno.ENOSYS

    def statfs(self, path):
        return -errno.ENOSYS

    def setxattr(self, path):
        return -errno.ENOSYS
        
    def removexattr(self, path):
        return -errno.ENOSYS

    def lock(self, path):
        return -errno.ENOSYS

    def fgetattr(self, path):
        return -errno.ENOSYS
      
    def bmap(self, path):
        return -errno.ENOSYS

    def fsinit(self, path):
        return -errno.ENOSYS

    def fsdestroy(self, path):
        return -errno.ENOSYS
  
    def ioctl(self, path):
        return -errno.ENOSYS

    def poll(self, path):
        return -errno.ENOSYS

    def fsync(self, path):
        return -errno.ENOSYS

    def fsyncdir(self, path):
        return -errno.ENOSYS
        


def main():
    try:
        fs = CmisFS(url=sys.argv[1], repo=sys.argv[2])
        fs.parse(errex=1)
        fs.main()
    except OSError:
        exit(2)

if __name__ == '__main__':
    main()
