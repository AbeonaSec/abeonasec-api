from datetime import date

from fastapi import APIRouter, Query
from elasticsearch import AsyncElasticsearch

router = APIRouter()

ES_INDEX = 'plugin-abp'

PROTOCOL_MAP = {6: 'TCP', 17: 'UDP', 1: 'ICMP', 2: 'IGMP', 58: 'ICMPv6'}


def es_client():
    return AsyncElasticsearch(
        'https://localhost:9200',
        basic_auth=('elastic', 'placeholder123'),
        verify_certs=False,
        ssl_show_warn=False,
    )


def fmt_threat(src: dict, doc_id: str) -> dict:
    protocol_num = src.get('protocol')
    try:
        protocol_num = int(protocol_num)
    except (TypeError, ValueError):
        pass
    return {
        '_id': doc_id,
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
        'probs': src.get('probs'),
    }


@router.get('/threats')
async def getThreats(
    search: str = Query(default=''),
    protocol: str = Query(default='All'),
    severity: str = Query(default='critical'),  # 'critical' = probs:true only, 'all' = no filter
    size: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    must = []
    filters = []

    if severity == 'critical':
        must.append({'term': {'probs': True}})
    elif severity == 'warning':
        # placeholder no plugin emits warn yet
        return {'total': 0, 'threats': []}

    if search:
        must.append({
            'multi_match': {
                'query': search,
                'fields': ['src_ip', 'dest_ip', 'host_ip', 'src_mac', 'dest_mac'],
                'type': 'phrase_prefix',
            }
        })

    protocol_nums = {v: k for k, v in PROTOCOL_MAP.items()}
    if protocol != 'All' and protocol in protocol_nums:
        filters.append({'term': {'protocol': protocol_nums[protocol]}})

    query = {'bool': {'must': must, 'filter': filters}} if (must or filters) else {'match_all': {}}

    sort = [{'timestamp.keyword': {'order': 'desc', 'unmapped_type': 'keyword'}}]
    if severity == 'all':
        sort.insert(0, {'probs': {'order': 'desc'}})

    async with es_client() as es:
        resp = await es.search(
            index=ES_INDEX,
            query=query,
            sort=sort,
            size=size,
            from_=offset,
            track_total_hits=True,
        )

    hits = resp['hits']
    return {
        'total': hits['total']['value'],
        'threats': [fmt_threat(h['_source'], h['_id']) for h in hits['hits']],
    }


@router.get('/threats/stats')
async def getThreatStats():
    today = date.today().isoformat()

    aggs = {
        'by_protocol': {
            'terms': {'field': 'protocol.keyword', 'size': 10},
        },
        'top_src_ips': {
            'terms': {'field': 'src_ip.keyword', 'size': 10},
        },
        'today': {
            'filter': {
                'range': {
                    'timestamp': {
                        'gte': f'{today}T00:00:00',
                        'lte': f'{today}T23:59:59',
                    }
                }
            }
        },
    }

    async with es_client() as es:
        resp = await es.search(
            index=ES_INDEX,
            query={'term': {'probs': True}},
            aggs=aggs,
            size=0,
            track_total_hits=True,
        )

    agg = resp.get('aggregations', {})

    by_protocol = [
        {
            'protocol': PROTOCOL_MAP.get(int(b['key']), str(b['key'])) if str(b['key']).isdigit() else str(b['key']),
            'count': b['doc_count'],
        }
        for b in agg.get('by_protocol', {}).get('buckets', [])
    ]

    top_src_ips = [
        {'ip': b['key'], 'count': b['doc_count']}
        for b in agg.get('top_src_ips', {}).get('buckets', [])
    ]

    return {
        'total': resp['hits']['total']['value'],
        'today': agg.get('today', {}).get('doc_count', 0),
        'by_protocol': by_protocol,
        'top_src_ips': top_src_ips,
    }
