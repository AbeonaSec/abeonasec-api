import asyncio
import socket
from datetime import date

from fastapi import APIRouter
import psutil
from elasticsearch import AsyncElasticsearch

from .netutils import net_io_counters

router = APIRouter()

RATE_INTERVAL = 0.5  # seconds for rate sampling
ES_INDEX = 'plugin-abp'


def es_client():
    return AsyncElasticsearch(
        'https://host.containers.internal:9200',
        basic_auth=('elastic', 'placeholder123'),
        verify_certs=False,
        ssl_show_warn=False,
    )


async def get_blocked_today() -> int:
    try:
        today = date.today().isoformat()
        async with es_client() as es:
            resp = await es.count(
                index=ES_INDEX,
                query={'range': {'timestamp': {'gte': f'{today}T00:00:00', 'lte': f'{today}T23:59:59'}}},
            )
        return resp['count']
    except Exception:
        return 0


def get_connections():
    try:
        conns = psutil.net_connections(kind='inet')
        result = []
        for c in conns:
            laddr = f'{c.laddr.ip}:{c.laddr.port}' if c.laddr else ''
            raddr = f'{c.raddr.ip}:{c.raddr.port}' if c.raddr else ''
            result.append({
                'family': 'IPv6' if c.family == socket.AF_INET6 else 'IPv4',
                'type': 'UDP' if c.type == socket.SOCK_DGRAM else 'TCP',
                'local_addr': laddr,
                'remote_addr': raddr,
                'status': c.status,
                'pid': c.pid,
            })
        return result
    except Exception:
        return []


def get_interfaces():
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    result = []
    for name, st in stats.items():
        iface_addrs = []
        for addr in addrs.get(name, []):
            family_map = {
                socket.AF_INET: 'IPv4',
                socket.AF_INET6: 'IPv6',
                psutil.AF_LINK: 'MAC',
            }
            iface_addrs.append({
                'family': family_map.get(addr.family, str(addr.family)),
                'address': addr.address,
                'netmask': addr.netmask,
            })
        result.append({
            'name': name,
            'isup': st.isup,
            'speed_mbps': st.speed,
            'mtu': st.mtu,
            'addresses': iface_addrs,
        })
    return result


@router.get('/network')
async def getNetwork():
    # Take two net samples separated by RATE_INTERVAL; run ES query concurrently
    net1 = net_io_counters()
    blocked_task = asyncio.create_task(get_blocked_today())
    await asyncio.sleep(RATE_INTERVAL)
    net2 = net_io_counters()

    # Sum bytes across non-loopback interfaces for aggregate rate
    sent1 = recv1 = sent2 = recv2 = 0
    for iface, s in net1.items():
        if iface == 'lo':
            continue
        sent1 += s[0]
        recv1 += s[1]
    for iface, s in net2.items():
        if iface == 'lo':
            continue
        sent2 += s[0]
        recv2 += s[1]

    outbound_bps = max((sent2 - sent1) / RATE_INTERVAL, 0)
    inbound_bps = max((recv2 - recv1) / RATE_INTERVAL, 0)

    # Per-interface traffic snapshot (latest)
    traffic = [
        {
            'interface': name,
            'bytes_sent': s[0],
            'bytes_recv': s[1],
            'packets_sent': s[2],
            'packets_recv': s[3],
            'errin': s[4],
            'errout': s[5],
            'dropin': s[6],
            'dropout': s[7],
        }
        for name, s in net2.items()
    ]

    connections = get_connections()
    blocked_today = await blocked_task

    return {
        'stats': {
            'connections_count': len(connections),
            'inbound_bps': round(inbound_bps, 1),
            'outbound_bps': round(outbound_bps, 1),
            'blocked_today': blocked_today,
        },
        'connections': connections,
        'traffic': traffic,
        'interfaces': get_interfaces(),
    }
