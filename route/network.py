import asyncio
import socket
from datetime import date

from fastapi import APIRouter
import psutil
from elasticsearch import AsyncElasticsearch

from .netutils import net_io_counters, get_host_iface_meta, get_host_iface_v4, get_host_iface_v6

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
        return [
            {
                'family': 'IPv6' if c.family == socket.AF_INET6 else 'IPv4',
                'type': 'UDP' if c.type == socket.SOCK_DGRAM else 'TCP',
                'local_addr': f'{c.laddr.ip}:{c.laddr.port}' if c.laddr else '',
                'remote_addr': f'{c.raddr.ip}:{c.raddr.port}' if c.raddr else '',
                'status': c.status,
                'pid': c.pid,
            }
            for c in psutil.net_connections(kind='inet')
        ]
    except Exception:
        return []


def get_interfaces(host_iface_names: list[str]):
    # IPv4 from /proc/1/net/fib_trie + route (host namespace)
    # IPv6 from /proc/1/net/if_inet6 (host namespace)
    meta = get_host_iface_meta(host_iface_names)
    v4_addrs = get_host_iface_v4()
    v6_addrs = get_host_iface_v6()
    result = []
    for name in host_iface_names:
        m = meta.get(name, {})
        iface_addrs = []
        if m.get('mac'):
            iface_addrs.append({'family': 'MAC', 'address': m['mac'], 'netmask': None})
        iface_addrs.extend(v4_addrs.get(name, []))
        iface_addrs.extend(v6_addrs.get(name, []))
        result.append({
            'name': name,
            'isup': m.get('isup'),
            'speed_mbps': m.get('speed_mbps'),
            'mtu': m.get('mtu'),
            'addresses': iface_addrs,
        })
    return result


def _wan_bytes(net):
    sent = sum(s[0] for k, s in net.items() if k != 'lo')
    recv = sum(s[1] for k, s in net.items() if k != 'lo')
    return sent, recv


@router.get('/network')
async def getNetwork():
    # two net samples separated by RATE_INTERVAL; run ES query concurrently
    net1 = net_io_counters()
    blocked_task = asyncio.create_task(get_blocked_today())
    await asyncio.sleep(RATE_INTERVAL)
    net2 = net_io_counters()

    sent1, recv1 = _wan_bytes(net1)
    sent2, recv2 = _wan_bytes(net2)
    outbound_bps = max((sent2 - sent1) / RATE_INTERVAL, 0)
    inbound_bps = max((recv2 - recv1) / RATE_INTERVAL, 0)

    # interface traffic snapshot (latest)
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
        'interfaces': get_interfaces(list(net2.keys())),
    }
