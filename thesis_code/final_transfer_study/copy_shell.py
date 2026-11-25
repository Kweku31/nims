#!/usr/bin/env python3
"""Per-copy SSH relay for the paired study. Management SSH never uses the relay."""
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import time


def main():
    name = Path(sys.argv[0]).name
    args = sys.argv[1:]
    relay = os.environ['STUDY_RELAY']
    if name == 'scp':
        binary = os.environ['STUDY_SCP']
        os.execv(binary, [binary, '-S', relay, *args])
    if name == 'rsync':
        binary = os.environ['STUDY_RSYNC']
        shell = args.index('-e') + 1
        args[shell] = shlex.join([relay, *shlex.split(args[shell])[1:]])
        trace = Path(os.environ['STUDY_TRACE'])
        first = not trace.exists()
        status = subprocess.run([binary, *args]).returncode
        if status and first and trace.exists():
            if any(json.loads(line)['event']=='controlled_drop' for line in trace.read_text().splitlines()):
                print('Connection reset by peer (study interrupted this copy)', file=sys.stderr)
        return status if status >= 0 else 128-status

    trace = Path(os.environ['STUDY_TRACE'])
    def record(kind, count):
        with trace.open('a') as f:
            f.write(json.dumps(dict(event=kind, bytes_forwarded=count, unix_time=time.time()))+'\n')

    first_copy = not trace.exists()
    cutoff = int(os.environ['STUDY_CUTOFF']) if first_copy else 0
    forwarded = 0
    record('copy_started', 0)
    # SSH stdout goes directly to the file-transfer client. Only its outgoing
    # protocol stream is counted, upstream of SSH framing and encryption.
    with subprocess.Popen([os.environ['STUDY_SSH'], *args], stdin=subprocess.PIPE,
                          bufsize=0, start_new_session=True) as child:
        os.close(1)  # The copy client must receive EOF as soon as its SSH child exits.
        try:
            while child.poll() is None:
                if not select.select([0], [], [], 0.1)[0]:
                    continue
                limit = min(65536, cutoff-forwarded) if cutoff else 65536
                block = os.read(0, limit)
                if not block:
                    break
                view = memoryview(block)
                while view:
                    written = os.write(child.stdin.fileno(), view)
                    forwarded += written
                    view = view[written:]
                if cutoff and forwarded == cutoff:
                    record('controlled_drop', forwarded)
                    child.terminate()
                    child.wait()
                    print('Connection reset by peer (study interrupted this copy)', file=sys.stderr)
                    return 255
        except BrokenPipeError:
            pass
        finally:
            child.stdin.close()
        result = child.wait()
        record('copy_exit', forwarded)
        return result


if __name__ == '__main__':
    sys.exit(main())
