import datetime
import os
import re
import subprocess
import sys
import threading
from pathlib import PurePath
from random import randint
from tempfile import gettempdir
from typing import Dict, Any, Optional
import json

from pytranscoder.media import MediaInfo

status_re = re.compile(r'^.*avg (?P<fps>.+?) fps.*ETA\s(?P<eta>.+?)\)')

_CHARSET: str = sys.getdefaultencoding()


class Handbrake:

    def __init__(self, hbcli_path):
        self.hbcli = hbcli_path
        self.last_command = ''
        self.monitor_interval = 30
        self.log_path: PurePath = None

    @property
    def is_available(self) -> bool:
        return self.hbcli is not None

    def fetch_details(self, _path: str) -> MediaInfo:
        """Use HandBrakeCLI to get media information

        :param _path:   Absolute path to media file
        :return:        Instance of MediaInfo
        """
        with subprocess.Popen([self.hbcli, '--scan', '-i', _path], stderr=subprocess.PIPE) as proc:
            output = proc.stderr.read().decode(encoding='utf8')
            mi = MediaInfo.parse_handbrake_details(_path, output)
            if mi.valid:
                return mi
        return MediaInfo(None)

    def monitor_hbcli(self, proc: subprocess.Popen):
        diff = datetime.timedelta(seconds=self.monitor_interval)
        event = datetime.datetime.now() + diff

        #
        # Create a transaction log for this run, to be left behind if an error is encountered.
        #
        suffix = randint(100, 999)
        self.log_path: PurePath = PurePath(gettempdir(), 'pytranscoder-' + threading.current_thread().getName() + '-' +
                                           str(suffix) + '.log')

        with open(str(self.log_path), 'w') as logfile:
            while proc.poll() is None:
                line = proc.stdout.readline()
                logfile.write(line)
                logfile.flush()

                match = status_re.match(line)
                if match is not None and len(match.groups()) >= 2:
                    if datetime.datetime.now() > event:
                        event = datetime.datetime.now() + diff
                        info: Dict[str, Any] = match.groupdict()
                        yield info

        if proc.returncode == 0:
            # if we got here then everything went fine, so remove the transaction log
            os.remove(str(self.log_path))
            self.log_path = None

    def run(self, params, event_callback) -> Optional[int]:

        self.last_command = ' '.join([self.hbcli, *params])
        with subprocess.Popen([self.hbcli,
                               *params],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True,
                              shell=False) as p:

            for stats in self.monitor_hbcli(p):
                if event_callback is not None:
                    veto = event_callback(stats)
                    if veto:
                        p.kill()
                        return None
            return p.returncode

    def run_remote(self, sshcli: str, user: str, ip: str, params: list, event_callback) -> Optional[int]:
        cli = [sshcli, user + '@' + ip, self.hbcli, *params]
        self.last_command = ' '.join(cli)
        with subprocess.Popen(cli,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True,
                              shell=False) as p:
            for stats in self.monitor_hbcli(p):
                if event_callback is not None:
                    veto = event_callback(stats)
                    if veto:
                        p.kill()
                        return None
            return p.returncode
