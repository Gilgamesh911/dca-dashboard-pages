"""Build a public, credential-free market snapshot for GitHub Pages."""
import json
import csv
import io
import subprocess
from datetime import datetime, timezone, timedelta
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

def tencent_history(symbol, start='2026-10-20', count=100):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq'
    rows = (get(url).get('data') or {}).get(symbol, {}).get('day', [])
    return [{'date': p[0], 'close': float(p[2])} for p in rows if p[0] >= start]

def fred_history(series):
    raw = get_text(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2026-10-20')
    return [{'date': row['observation_date'], 'close': float(row[series])} for row in csv.DictReader(io.StringIO(raw)) if row.get(series) not in ('', '.') and row['observation_date'] >= '2026-10-20']

def ecb_fx(start, full=False):
    file = 'eurofxref-hist.xml' if full else 'eurofxref-hist-90d.xml'
    raw = get_text(f'https://www.ecb.europa.eu/stats/eurofxref/{file}')
    root = ElementTree.fromstring(raw)
    result = []
    for cube in root.iter():
        date = cube.attrib.get('time')
        if not date or date < start:
            continue
        rates = {child.attrib.get('currency'): float(child.attrib['rate']) for child in cube if child.attrib.get('currency') in ('CNY', 'USD', 'HKD', 'JPY')}
        if len(rates) == 4:
            result.append({'date': date, 'CNY': 1, 'USD': rates['CNY']/rates['USD'], 'HKD': rates['CNY']/rates['HKD'], 'JPY': rates['CNY']/rates['JPY']})
    return sorted(result, key=lambda item: item['date'])

def main():
    target = ROOT / 'data' / 'market.json'
    old = json.loads(target.read_text()) if target.exists() else {}
    funds = {}
    backtest_funds = {}
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=370)).isoformat()
    for code in FUNDS:
        previous = old.get('backtestFunds', {}).get(code, [])
        previous_latest = previous[-1]['date'] if previous else None
        entries = []
        for page in range(1, 31):
            url = f'https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={page}&pageSize=20'
            try:
                data = get(url)
                rows = (data.get('Data') or {}).get('LSJZList') or []
                if data.get('ErrCode') != 0 or not rows:
                    raise RuntimeError(f'NAV unavailable: {code}, page {page}')
            except Exception:
                if previous:
                    break
                raise
            for row in rows:
                date, value = row.get('FSRQ'), row.get('DWJZ')
                if not date or not value or date < cutoff:
                    continue
                entry = {'date': date, 'nav': float(value), 'changePct': float(row['JZZZL']) if row.get('JZZZL') else None}
                try:
                    dividend = float(row.get('FHFCZ') or 0)
                    if 0 < dividend < float(value):
                        entry['dividend'] = dividend
                except ValueError:
                    pass
                entries.append(entry)
            if rows[-1]['FSRQ'] <= (previous_latest or cutoff):
                break
        backtest_funds[code] = [row for row in merge(previous, entries) if row['date'] >= cutoff]
        funds[code] = merge(old.get('funds', {}).get(code, []), [row for row in entries if row['date'] >= '2026-10-27'])
    try:
        hk = merge(old.get('hk3195', []), tencent_history('hk03195', start=cutoff, count=500))
    except Exception as exc:
        print(f'HK history unavailable: {exc}')
        hk = old.get('hk3195', [])
    benchmarks = old.get('benchmarks', {})
    for name, provider in [('spx', lambda: merge(fred_history('SP500'), tencent_history('us.INX'))), ('ndx', lambda: fred_history('NASDAQ100')), ('hsi', lambda: tencent_history('hkHSI')), ('csi300', lambda: tencent_history('sh000300')), ('nikkei', lambda: fred_history('NIKKEI225'))]:
        try:
            rows = provider()
            if rows:
                benchmarks[name] = merge(benchmarks.get(name, []), rows)
        except Exception as exc:
            print(f'Benchmark {name} unavailable: {exc}')
    try:
        old_fx = old.get('fx', [])
        fx = merge(old_fx, ecb_fx(cutoff, full=not old_fx or old_fx[0]['date'] > cutoff))
    except Exception as exc:
        print(f'FX unavailable: {exc}')
        fx = old.get('fx', [])
    quotes = old.get('quotes', {})
    for url in [
        'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&fid=f3&fs=i:100.SPX&fields=f2,f3,f12,f14,f124&fltt=2',
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
        for symbol,key in [('us.INX','spx'),('usNDX','ndx'),('hk03195','hk3195')]:
            row = get(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,2,qfq')['data'][symbol]
            q = row['qt'][symbol]
            quotes[key] = {'price': float(q[3]), 'changePct': float(q[32]), 'date': row['day'][-1][0], 'source': '腾讯财经'}
    except Exception as exc:
        print(f'Tencent quote unavailable: {exc}')
    if 'spx' not in quotes and len(benchmarks.get('spx', [])) >= 2:
        last, prev = benchmarks['spx'][-1], benchmarks['spx'][-2]
        quotes['spx'] = {'price': last['close'], 'changePct': 100*(last['close']/prev['close']-1), 'date': last['date'], 'source': 'FRED收盘'}
    payload = {'updatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'Eastmoney, Tencent Finance, FRED, ECB public data', 'funds': funds, 'backtestFunds': backtest_funds, 'hk3195': hk, 'quotes': quotes, 'benchmarks': benchmarks, 'fx': fx}
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Wrote {target}: {len(funds)} funds, {len(hk)} HK prices')

if __name__ == '__main__':
    main()
