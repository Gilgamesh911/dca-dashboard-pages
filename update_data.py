"""Build a public, credential-free market snapshot for GitHub Pages."""
import json
import csv
import io
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
FUNDS = ('017641', '019305', '019172', '019173')

def get(url):
    return json.loads(get_text(url))

def get_text(url):
    return subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--retry', '2', '--max-time', '20', '-H', 'Referer: https://fundf10.eastmoney.com/', url], timeout=70).decode('utf-8')

def merge(old_rows, new_rows):
    rows = {item['date']: item for item in old_rows}
    rows.update({item['date']: item for item in new_rows})
    return sorted(rows.values(), key=lambda item: item['date'])

def tencent_history(symbol):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,100,qfq'
    rows = (get(url).get('data') or {}).get(symbol, {}).get('day', [])
    return [{'date': p[0], 'close': float(p[2])} for p in rows if p[0] >= '2026-10-20']

def fred_history(series):
    raw = get_text(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2026-10-20')
    return [{'date': row['observation_date'], 'close': float(row[series])} for row in csv.DictReader(io.StringIO(raw)) if row.get(series) not in ('', '.') and row['observation_date'] >= '2026-10-20']

def ecb_fx():
    raw = get_text('https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml')
    root = ElementTree.fromstring(raw)
    result = []
    for cube in root.iter():
        date = cube.attrib.get('time')
        if not date or date < '2026-10-20':
            continue
        rates = {child.attrib.get('currency'): float(child.attrib['rate']) for child in cube if child.attrib.get('currency') in ('CNY', 'USD', 'HKD', 'JPY')}
        if len(rates) == 4:
            result.append({'date': date, 'CNY': 1, 'USD': rates['CNY']/rates['USD'], 'HKD': rates['CNY']/rates['HKD'], 'JPY': rates['CNY']/rates['JPY']})
    return sorted(result, key=lambda item: item['date'])

def main():
    target = ROOT / 'data' / 'market.json'
    old = json.loads(target.read_text()) if target.exists() else {}
    funds = {}
    for code in FUNDS:
        url = f'https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=20'
        data = get(url)
        if data.get('ErrCode') != 0 or not (data.get('Data') or {}).get('LSJZList'):
            raise RuntimeError(f'NAV unavailable: {code}')
        entries = []
        for row in data['Data']['LSJZList']:
            date, value = row.get('FSRQ'), row.get('DWJZ')
            if date and value and date >= '2026-10-27':
                entry = {'date': date, 'nav': float(value), 'changePct': float(row['JZZZL']) if row.get('JZZZL') else None}
                try:
                    dividend = float(row.get('FHFCZ') or 0)
                    if 0 < dividend < float(value):
                        entry['dividend'] = dividend
                except ValueError:
                    pass
                entries.append(entry)
        funds[code] = merge(old.get('funds', {}).get(code, []), entries)
    try:
        hk = merge(old.get('hk3195', []), [row for row in tencent_history('hk03195') if row['date'] >= '2026-11-01'])
    except Exception as exc:
        print(f'HK history unavailable: {exc}')
        hk = old.get('hk3195', [])
    benchmarks = old.get('benchmarks', {})
    for name, provider in [('spx', lambda: fred_history('SP500')), ('ndx', lambda: fred_history('NASDAQ100')), ('hsi', lambda: tencent_history('hkHSI')), ('csi300', lambda: tencent_history('sh000300')), ('nikkei', lambda: fred_history('NIKKEI225'))]:
        try:
            rows = provider()
            if rows:
                benchmarks[name] = merge(benchmarks.get(name, []), rows)
        except Exception as exc:
            print(f'Benchmark {name} unavailable: {exc}')
    try:
        fx = merge(old.get('fx', []), ecb_fx())
    except Exception as exc:
        print(f'FX unavailable: {exc}')
        fx = old.get('fx', [])
    quotes = old.get('quotes', {})
    for url in [
        'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&fid=f3&fs=i:100.SPX&fields=f2,f3,f12,f14,f124&fltt=2',
        'https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=116.03195&fields=f2,f3,f12,f14,f124',
    ]:
        try:
            data = get(url).get('data') or {}
            diff = data.get('diff') or []
            rows = diff.values() if isinstance(diff, dict) else diff
            for row in rows:
                key = {'SPX':'spx','NDX':'ndx','03195':'hk3195'}.get(row.get('f12'))
                if key and isinstance(row.get('f2'), (int,float)) and isinstance(row.get('f3'), (int,float)):
                    quotes[key] = {'price':float(row['f2']),'changePct':float(row['f3']),'timestamp':row.get('f124'),'source':'东方财富快照'}
        except Exception as exc:
            print(f'Quote unavailable: {exc}')
    try:
        ndx = get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=usNDX,day,,,2,qfq')['data']['usNDX']
        q = ndx['qt']['usNDX']
        quotes['ndx'] = {'price': float(q[3]), 'changePct': float(q[32]), 'date': ndx['day'][-1][0], 'source': '腾讯财经'}
    except Exception as exc:
        print(f'Nasdaq 100 quote unavailable: {exc}')
    payload = {'updatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'Eastmoney, Tencent Finance, FRED, ECB public data', 'funds': funds, 'hk3195': hk, 'quotes': quotes, 'benchmarks': benchmarks, 'fx': fx}
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Wrote {target}: {len(funds)} funds, {len(hk)} HK prices')

if __name__ == '__main__':
    main()
