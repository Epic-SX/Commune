import psutil
import os
import signal
import sys

def check_pid(pid):        
    """ Check For the existence of a unix pid. """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def kill_process(pid):
    if isinstance(pid, str):
        pid = int(pid)
    
    os.kill(pid, signal.SIGKILL)


class NetworkMonitor:

    def __enter__(self):
        io_1 = psutil.net_io_counters()
        self.start_bytes_sent, self.start_bytes_recv = io_1.bytes_sent, io_1.bytes_recv
        self.start_time = datetime.datetime.utcnow()
        return self

    def __exit__(self, *args):
        io_2 = psutil.net_io_counters()
        self.total_upload_bytes, self.total_download_bytes = self.upload_bytes, self.download_bytes
    
    @property
    def download_bytes(self):
        io_2 = psutil.net_io_counters()
        return io_2.bytes_sent - self.start_bytes_sent

    @property
    def upload_bytes(self):
        io_2 = psutil.net_io_counters()
        return io_2.bytes_recv - self.start_bytes_recv

kill_pid = kill_process



import subprocess
import shlex
def run_command(command:str):

    process = subprocess.run(shlex.split(command), 
                        stdout=subprocess.PIPE, 
                        universal_newlines=True)
    
    return process




def path_exists(path:str):
    return os.path.exists(path)

def ensure_path( path):
    """
    ensures a dir_path exists, otherwise, it will create it 
    """

    dir_path = os.path.dirname(path)
    if not os.path.isdir(dir_path):
        os.makedirs(dir_path)

    return path
