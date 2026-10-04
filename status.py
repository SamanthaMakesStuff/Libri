import json, os, time, sqlite3
from datetime import datetime

lines = open('hardcover_driver.log', encoding='utf-8').read().splitlines()
print('=== driver log (last 12) ===')
print('\n'.join(lines[-12:]))
print()
prog = json.load(open('hardcover_progress.json'))
mt = os.path.getmtime('hardcover_progress.json')
print(f'enrich processed: {len(prog):,} | last checkpoint {datetime.fromtimestamp(mt):%H:%M:%S} ({time.time()-mt:.0f}s ago)')
print('discovery started:', os.path.exists('hardcover_discover_progress.json'))
c = sqlite3.connect('book_rec.db')
t = c.execute('SELECT COUNT(*) FROM books').fetchone()[0]
e = c.execute("SELECT COUNT(*) FROM books WHERE tropes!='[]' OR tags!='[]'").fetchone()[0]
cw = c.execute("SELECT COUNT(*) FROM books WHERE content_warnings!='[]'").fetchone()[0]
print(f'DB: {t:,} books | recommendable: {e:,} ({e/t*100:.1f}%) | content warnings: {cw:,}')
