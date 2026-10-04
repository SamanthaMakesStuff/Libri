import time
import app

t = time.time()
r = app.get_recommendations('all')
dt = time.time() - t
print(f"recommendation request: {dt:.1f}s  ({len(r['recommendations'])} recs returned)")
