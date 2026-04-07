import sys
from ipaddress import IPv6Address

FILE_READ_BUFFER_SIZE = 32 * 1024
ENCODING = sys.getfilesystemencoding()
ENCODING_ERRS = sys.getfilesystemencodeerrors()

PROC_1_PATH = '/proc/1'


def _sysfs_read(name, attr, default=None):
    try:
        with open(f'/sys/class/net/{name}/{attr}') as f:
            return f.read().strip()
    except OSError:
        return default


def get_host_iface_meta(iface_names):
    result = {}
    for name in iface_names:
        operstate = _sysfs_read(name, 'operstate', 'unknown')
        isup = operstate in ('up', 'unknown')
        try:
            speed = int(_sysfs_read(name, 'speed', '-1'))
            speed = None if speed < 0 else speed
        except (ValueError, TypeError):
            speed = None
        try:
            mtu = int(_sysfs_read(name, 'mtu', '0'))
        except (ValueError, TypeError):
            mtu = None
        mac = _sysfs_read(name, 'address')
        result[name] = {'isup': isup, 'speed_mbps': speed, 'mtu': mtu, 'mac': mac}
    return result


def get_host_iface_v6(proc_path=PROC_1_PATH):  # proc_path kept for testability
    addrs: dict[str, list] = {}
    try:
        with open_text(f'{proc_path}/net/if_inet6') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                hex_addr, _, hex_prefix, _, _, iface = parts[:6]
                addr = str(IPv6Address(int(hex_addr, 16)))
                prefix = int(hex_prefix, 16)
                addrs.setdefault(iface, []).append({
                    'family': 'IPv6',
                    'address': addr,
                    'netmask': str(prefix),
                })
    except Exception:
        pass
    return addrs

# IMPORTANT INFO
# these next few functions and variables are all literally copy and pasted
# from psutil source code just so I can add an argument to specify the filepath

# when we change the PROCFS path for psutil it breaks other psutil commands so we need to
# specify our own

# we will be mounting the pid environment of the host into the container in order to access
# /proc/1, the proc information for PID 1

# this is done via flag --pid=host on a podman run command for dev purposes
# we will need to add that flag to the podman compose for the full application as well
def net_io_counters(proc_path='/proc/1'):
    """Return network I/O statistics for every network interface
    installed on the system as a dict of raw tuples.
    """
    with open_text(f"{proc_path}/net/dev") as f:
        lines = f.readlines()
    retdict = {}
    for line in lines[2:]:
        colon = line.rfind(':')
        assert colon > 0, repr(line)
        name = line[:colon].strip()
        fields = line[colon + 1 :].strip().split()

        (
            # in
            bytes_recv,
            packets_recv,
            errin,
            dropin,
            _fifoin,  # unused
            _framein,  # unused
            _compressedin,  # unused
            _multicastin,  # unused
            # out
            bytes_sent,
            packets_sent,
            errout,
            dropout,
            _fifoout,  # unused
            _collisionsout,  # unused
            _carrierout,  # unused
            _compressedout,  # unused
        ) = map(int, fields)

        retdict[name] = (
            bytes_sent,
            bytes_recv,
            packets_sent,
            packets_recv,
            errin,
            errout,
            dropin,
            dropout,
        )
    return retdict

def open_text(fname):
    """Open a file in text mode by using the proper FS encoding and
    en/decoding error handlers.
    """
    # See:
    # https://github.com/giampaolo/psutil/issues/675
    # https://github.com/giampaolo/psutil/pull/733
    fobj = open(  # noqa: SIM115
        fname,
        buffering=FILE_READ_BUFFER_SIZE,
        encoding=ENCODING,
        errors=ENCODING_ERRS,
    )
    try:
        # Dictates per-line read(2) buffer size. Defaults is 8k. See:
        # https://github.com/giampaolo/psutil/issues/2050#issuecomment-1013387546
        fobj._CHUNK_SIZE = FILE_READ_BUFFER_SIZE
    except AttributeError:
        pass
    except Exception:
        fobj.close()
        raise

    return fobj