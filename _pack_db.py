"""One-off helper: compress /data/book_rec.db -> /data/book_rec.db.gz on a Fly
volume, so the ~199 MB database can be DOWNLOADED as a small (~62 MB) file
without the sftp tunnel dropping. Run on the server with:
    fly ssh console -a <app> -C "python /data/_pack_db.py"
then `fly ssh sftp get /data/book_rec.db.gz <local-name>.gz`.
"""
import gzip
import os
import shutil

SRC = "/data/book_rec.db"
DST = "/data/book_rec.db.gz"

print("source:", os.path.getsize(SRC), "bytes")
with open(SRC, "rb") as f, gzip.open(DST, "wb", compresslevel=6) as g:
    shutil.copyfileobj(f, g, 1024 * 1024)
print("wrote:", os.path.getsize(DST), "bytes to", DST)
