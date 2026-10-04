"""One-off helper: decompress /data/book_rec.db.gz -> /data/book_rec.db on the
Fly volume, then clean up. Run on the server with:
    fly ssh console -C "python /data/_unpack_db.py"
"""
import gzip
import os
import shutil

SRC = "/data/book_rec.db.gz"
DST = "/data/book_rec.db"

# Remove any stale/partial DB and its WAL sidecars first.
for p in (DST, DST + "-wal", DST + "-shm"):
    try:
        os.remove(p)
    except FileNotFoundError:
        pass

with gzip.open(SRC, "rb") as f, open(DST, "wb") as g:
    shutil.copyfileobj(f, g, 1024 * 1024)

print("wrote", os.path.getsize(DST), "bytes to", DST)
os.remove(SRC)
print("removed", SRC)
