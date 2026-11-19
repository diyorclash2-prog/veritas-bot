"""Official Gutenberg fallback when the primary Gutendex catalogue is unavailable."""
import csv
import gzip
import io
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT='https://www.gutenberg.org'
cache = {}
lock = threading.Lock()


def read_url(path, max_bytes):
    req=urllib.request.Request(ROOT+path,headers={'User-Agent':'VeritasBot/1.0 Gutenberg catalogue'})
    with urllib.request.urlopen(req,timeout=10) as response:
        data=response.read(max_bytes+1)
    if len(data)>max_bytes:
        raise ValueError('catalogue size')
    return data


def book_ids(lang):
    with lock:
        if cache.get('until',0)<=time.monotonic():
            body=read_url('/cache/epub/feeds/pg_catalog.csv.gz',10_000_000)
            by_language={}
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as data:
                raw=data.read(55_000_001)
            if len(raw)>55_000_000:raise ValueError('catalogue size')
            for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
                sid=row.get('Text#','').strip()
                if row.get('Type')!='Text' or not sid.isdecimal():continue
                for language in row.get('Language','').lower().split(';'):
                    by_language.setdefault(language.strip(),[]).append(sid)
            cache.update(until=time.monotonic()+86400,by_language=by_language)
        return cache['by_language'].get(lang,[])


def candidate(lang, offset, known):
    ids=book_ids(lang)
    metadata_checked=0
    for index in range(min(len(ids),500)):
        pos=(offset+index)%len(ids)
        sid=ids[pos]
        if known(sid):continue
        node=ET.fromstring(read_url(f'/cache/epub/{sid}/pg{sid}.rdf',300_000))
        ns={'d':'http://purl.org/dc/terms/','p':'http://www.gutenberg.org/2009/pgterms/',
            'r':'http://www.w3.org/1999/02/22-rdf-syntax-ns#'}
        ebook=node.find('p:ebook',ns)
        if ebook is not None and 'public domain in the usa' in ebook.findtext('d:rights','',ns).lower():
            langs=[v.text for v in ebook.findall('d:language//r:value',ns)]
            title=ebook.findtext('d:title','',ns)
            if lang in langs and title:
                authors=[{'name':n.text} for n in ebook.findall('d:creator//p:name',ns) if n.text]
                item={'id':int(sid),'title':title,'languages':langs,'authors':authors,'copyright':False}
                return (item,lang,'epub','application/epub+zip',f'{ROOT}/cache/epub/{sid}/pg{sid}.epub'),pos+1
        metadata_checked+=1
        if metadata_checked==4:return None,pos+1
    return None,offset+min(len(ids),500)
