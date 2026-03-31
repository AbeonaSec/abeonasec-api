from fastapi import APIRouter
import psutil
import subprocess

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
    net = psutil.net_io_counters()
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
            'bytes_sent': net.bytes_sent,
            'bytes_recv': net.bytes_recv,
            'mb_sent': round(net.bytes_sent / 1e6, 1),
            'mb_recv': round(net.bytes_recv / 1e6, 1),
        },
        'gpu': gpu,
    }
