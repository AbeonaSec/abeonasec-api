from fastapi import APIRouter
import psutil
import subprocess
# custom netutils file with modified psutil functions
from .netutils import net_io_counters

router = APIRouter()

def get_gpu():
    try:
        result = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=name,utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            gpus = []
            for line in result.stdout.strip().splitlines():
                if line:
                    parts = [p.strip() for p in line.split(',')]
                    gpus.append({
                        'name': parts[0],
                        'utilization_percent': float(parts[1]),
                        'memory_used_mb': float(parts[2]),
                        'memory_total_mb': float(parts[3]),
                        'memory_percent': round(float(parts[2]) / float(parts[3]) * 100, 1),
                    })
            return gpus
    except Exception:
        pass
    return None

@router.get('/health')
async def getHealth():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = net_io_counters()
    # net now has bytes sent and recv data for all interfaces
    # i.e. {'lo': (45814314, 45814314, 220424, 220424, 0, 0, 0, 0), 'enp1s0': (17252702, 106527039, 68781, 91602, 0, 0, 72, 0)...}
    # so if you want to get the info for the main interface regardless of name then the best way is to
    # convert the values to a list and use index 1 (0 is loopback/localhost) like this: list(net.values())[1]
    # bytes sent is the nested 0 index, and bytes recieved is the nested 1 index
    bytes_sent = list(net.values())[1][0]
    bytes_recv = list(net.values())[1][1]
    # you could also use a loop to sum all interfaces, I will save it since I already wrote it:
    '''
    total_bytes_sent = 0
    total_bytes_recv = 0
    for interface, stats in net.items():
        if interface=='lo': continue # skip localhost traffic
        total_bytes_sent += stats[0]
        total_bytes_recv += stats[1]
    '''

    gpu = get_gpu()

    return {
        'cpu': {
            'percent': cpu,
        },
        'memory': {
            'total_gb': round(mem.total / 1e9, 1),
            'used_gb': round(mem.used / 1e9, 1),
            'percent': mem.percent,
        },
        'disk': {
            'total_gb': round(disk.total / 1e9, 1),
            'used_gb': round(disk.used / 1e9, 1),
            'percent': disk.percent,
        },
        'network': {
            'bytes_sent': bytes_sent,
            'bytes_recv': bytes_recv,
            'mb_sent': round(bytes_sent / 1e6, 1),
            'mb_recv': round(bytes_recv / 1e6, 1),
        },
        'gpu': gpu,
    }