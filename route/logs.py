from fastapi import APIRouter, Query
from elasticsearch import AsyncElasticsearch

router = APIRouter()

ES_INDEX = 'tmp'

PROTOCOL_MAP = {6: 'TCP', 17: 'UDP', 1: 'ICMP', 2: 'IGMP', 58: 'ICMPv6'}


def es_client():
    return AsyncElasticsearch(
        'https://localhost:9200',
        basic_auth=('elastic', 'placeholder123'),
        verify_certs=False,
        ssl_show_warn=False,
    )


def fmt_record(src: dict) -> dict:
    protocol_num = src.get('protocol')
    return {
        'timestamp': src.get('timestamp'),
        'host_ip': src.get('host_ip'),
        'src_ip': src.get('src_ip'),
        'src_port': src.get('src_port'),
        'src_mac': src.get('src_mac'),
        'dest_ip': src.get('dest_ip'),
        'dest_port': src.get('dest_port'),
        'dest_mac': src.get('dest_mac'),
        'protocol': PROTOCOL_MAP.get(protocol_num, str(protocol_num)),
        'protocol_num': protocol_num,
        'flags': src.get('flags'),
        'data_len': src.get('data_len'),
    }


@router.get('/logs')
async def getLogs(
    search: str = Query(default=''),
    protocol: str = Query(default='All'),
    size: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    query: dict = {'bool': {'must': [], 'filter': []}}

    if search:
        query['bool']['must'].append({
            'multi_match': {
                'query': search,
                'fields': ['src_ip', 'dest_ip', 'host_ip', 'src_mac', 'dest_mac'],
                'type': 'phrase_prefix',
            }
        })

    protocol_nums = {v: k for k, v in PROTOCOL_MAP.items()}
    if protocol != 'All' and protocol in protocol_nums:
        query['bool']['filter'].append({'term': {'protocol': protocol_nums[protocol]}})

    async with es_client() as es:
        resp = await es.search(
            index=ES_INDEX,
            query=query,
            sort=[{'timestamp': {'order': 'desc'}}],
            size=size,
            from_=offset,
        )

    hits = resp['hits']
    return {
        'total': hits['total']['value'],
        'logs': [fmt_record(h['_source']) for h in hits['hits']],
    }
