"""Build a public, credential-free market snapshot for GitHub Pages."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FUNDS = ('017641', '019305', '019172', '019173')

def get(url):
    raw = subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--retry', '2', '--max-time', '20', '-H', 'Referer: https://fundf10.eastmoney.com/', url], timeout=70)
    return json.loads(raw)

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
                entries.append({'date': date, 'nav': float(value), 'changePct': float(row['JZZZL']) if row.get('JZZZL') else None})
        merged = {item['date']: item for item in old.get('funds', {}).get(code, [])}
        merged.update({item['date']: item for item in entries})
        funds[code] = sorted(merged.values(), key=lambda item: item['date'])
    url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=116.03195&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=0&beg=20261001&end=20500101&lmt=1000'
    try:
        raw = get(url)
        klines = (raw.get('data') or {}).get('klines', [])
        hk = [{'date': p[0], 'close': float(p[2])} for line in klines if (p := line.split(',')) and len(p) >= 3 and p[0] >= '2026-11-01']
    except Exception as exc:
        print(f'HK history unavailable: {exc}')
        hk = old.get('hk3195', [])
    quotes = old.get('quotes', {})
    for url in [
        'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&fid=f3&fs=i:100.SPX,i:100.NDX&fields=f2,f3,f12,f14,f124&fltt=2',
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
    payload = {'updatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'Eastmoney public endpoints', 'funds': funds, 'hk3195': hk, 'quotes': quotes}
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Wrote {target}: {len(funds)} funds, {len(hk)} HK prices')

if __name__ == '__main__':
    main()
