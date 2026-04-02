import base64
import struct

from fastapi import APIRouter, Query
from elasticsearch import AsyncElasticsearch

router = APIRouter()

ES_INDEX = 'plugin-abp'

PROTOCOL_MAP = {6: 'TCP', 17: 'UDP', 1: 'ICMP', 2: 'IGMP', 58: 'ICMPv6'}


def es_client():
    return AsyncElasticsearch(
        'https://host.containers.internal:9200',
        basic_auth=('elastic', 'placeholder123'),
        verify_certs=False,
        ssl_show_warn=False,
    )


def fmt_record(src: dict, doc_id: str = None) -> dict:
    protocol_num = src.get('protocol')
    record = {
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
    if doc_id is not None:
        record['_id'] = doc_id
    return record


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
                # 'fields': ['src_ip', 'dest_ip', 'host_ip', 'src_mac', 'dest_mac'],
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
            sort=[{'timestamp.keyword': {'order': 'desc', 'unmapped_type': 'keyword'}}],
            size=size,
            from_=offset,
        )

    hits = resp['hits']
    return {
        'total': hits['total']['value'],
        'logs': [fmt_record(h['_source'], h['_id']) for h in hits['hits']],
    }


DNS_QTYPES = {1: 'A', 2: 'NS', 5: 'CNAME', 6: 'SOA', 12: 'PTR', 15: 'MX', 16: 'TXT', 28: 'AAAA', 33: 'SRV', 255: 'ANY'}


def _dns_read_name(data: bytes, offset: int) -> tuple[list, int]:
    labels = []
    while offset < len(data):
        length = data[offset]
        offset += 1
        if length == 0:
            break
        if (length & 0xC0) == 0xC0:
            ptr = ((length & 0x3F) << 8) | data[offset]
            offset += 1
            pointed, _ = _dns_read_name(data, ptr)
            labels.extend(pointed)
            break
        labels.append(data[offset:offset + length].decode('ascii', errors='replace'))
        offset += length
    return labels, offset


def parse_dns(raw) -> dict | None:
    try:
        if isinstance(raw, str):
            try:
                data = base64.b64decode(raw)
            except Exception:
                data = raw.encode('latin-1')
        elif isinstance(raw, bytes):
            data = raw
        else:
            return None

        if len(data) < 12:
            return None

        txid, flags, qdcount, ancount, nscount, arcount = struct.unpack_from('!HHHHHH', data, 0)
        qr = (flags >> 15) & 1
        opcode = (flags >> 11) & 0xF
        rcode = flags & 0x0F

        offset = 12
        questions = []
        for _ in range(qdcount):
            labels, offset = _dns_read_name(data, offset)
            if offset + 4 > len(data):
                break
            qtype, qclass = struct.unpack_from('!HH', data, offset)
            offset += 4
            questions.append({
                'name': '.'.join(labels),
                'type': DNS_QTYPES.get(qtype, str(qtype)),
                'class': 'IN' if qclass == 1 else str(qclass),
            })

        return {
            'transaction_id': f'0x{txid:04x}',
            'type': 'response' if qr else 'query',
            'opcode': opcode,
            'rcode': rcode,
            'questions': questions,
            'answer_count': ancount,
        }
    except Exception:
        return None


@router.get('/logs/{log_id}')
async def getLog(log_id: str):
    async with es_client() as es:
        resp = await es.get(index=ES_INDEX, id=log_id)
    src = resp['_source']
    record = {
        **fmt_record(src, log_id),
        'data': src.get('data'),
    }
    if src.get('src_port') == 53 or src.get('dest_port') == 53:
        parsed = parse_dns(src.get('data'))
        if parsed:
            record['parsed_dns'] = parsed
    return record
