"""Đo so sánh SQLite FTS5 và PostgreSQL FTS (tsvector + GIN) trên kho mục tổng hợp.

    python tests/bench_fts.py --sections 50000 --pg postgresql+psycopg://ai:ai@127.0.0.1:55432/ai_bench
Cả hai dùng cùng cách chuẩn hóa tiếng Việt của ứng dụng (bỏ dấu, chữ thường, tách token).
"""
import argparse
import random
import sqlite3
import statistics
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from aicommon.text import tokens, unaccent

SEED = Path(__file__).resolve().parents[2] / "kb-seed"


def corpus(n: int, seed: int = 7):
    rnd = random.Random(seed)
    base = sorted({t for f in SEED.rglob("*.md") for t in tokens(unaccent(f.read_text(encoding="utf-8")).lower())})
    on = "b c d g h k l m n p q r s t v x ch gh kh ng nh ph th tr".split()
    van = "a e i o u y ai ao au ay oi ui uy an ang anh en eng inh on ong un ung at ac ich ot uc".split()
    vocab = base + [rnd.choice(on) + rnd.choice(van) for _ in range(6000)]
    weights = [1 / (i + 1) ** 1.05 for i in range(len(vocab))]  # phân bố Zipf
    rows = []
    for i in range(n):
        head = " ".join(rnd.choices(vocab[:400], weights[:400], k=8))
        body = " ".join(rnd.choices(vocab, weights, k=rnd.randint(40, 200)))
        rows.append((f"S{i}", f"D{i // 20}", head, body))
    queries = [" ".join(rnd.choices(vocab[20:3000], weights[20:3000], k=rnd.randint(2, 4))) for _ in range(200)]
    return rows, queries


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] * 1000


def bench_sqlite(rows, queries):
    db = sqlite3.connect(":memory:")
    t = time.perf_counter()
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(sid UNINDEXED, did UNINDEXED, head, body, tokenize='unicode61 remove_diacritics 0')")
    db.executemany("INSERT INTO fts VALUES (?,?,?,?)", rows)
    db.commit()
    build = time.perf_counter() - t
    lat, hits = [], 0
    for q in queries:
        ex = " AND ".join(f'"{w}"' for w in q.split())
        t = time.perf_counter()
        r = db.execute("SELECT sid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 4.0, 1.0) LIMIT 10", (ex,)).fetchall()
        lat.append(time.perf_counter() - t)
        hits += bool(r)
    return build, lat, hits


def bench_pg(rows, queries, url):
    from tests.pgutil import recreate_db
    recreate_db(url)
    eng = create_engine(url)
    t = time.perf_counter()
    with eng.begin() as c:
        c.execute(text("CREATE TABLE s (sid text primary key, did text, head text, body text, tsv tsvector GENERATED ALWAYS AS "
                       "(setweight(to_tsvector('simple', head), 'A') || setweight(to_tsvector('simple', body), 'B')) STORED)"))
        c.execute(text("INSERT INTO s (sid, did, head, body) VALUES (:a, :b, :c, :d)"),
                  [{"a": a, "b": b, "c": c_, "d": d} for a, b, c_, d in rows])
        c.execute(text("CREATE INDEX ON s USING gin (tsv)"))
        c.execute(text("ANALYZE s"))
    build = time.perf_counter() - t
    with eng.connect() as c:
        size = c.execute(text("SELECT pg_size_pretty(pg_total_relation_size('s'))")).scalar()
    lat, hits = [], 0
    with eng.connect() as c:
        for q in queries:
            t = time.perf_counter()
            r = c.execute(text("SELECT sid FROM s, to_tsquery('simple', :q) q WHERE tsv @@ q "
                               "ORDER BY ts_rank_cd(tsv, q, 1) DESC LIMIT 10"), {"q": " & ".join(q.split())}).fetchall()
            lat.append(time.perf_counter() - t)
            hits += bool(r)
    return build, lat, hits, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", type=int, default=50000)
    ap.add_argument("--pg", default="postgresql+psycopg://ai:ai@127.0.0.1:55432/ai_bench")
    a = ap.parse_args()
    rows, queries = corpus(a.sections)
    sb, sl, sh = bench_sqlite(rows, queries)
    pb, pl, ph, size = bench_pg(rows, queries, a.pg)
    print(f"Số mục: {a.sections}, số truy vấn: {len(queries)} (AND 2–4 từ, xếp hạng top-10)")
    print(f"SQLite FTS5 : dựng chỉ mục {sb:6.1f} s | p50 {pct(sl, .5):7.2f} ms | p95 {pct(sl, .95):7.2f} ms | "
          f"tb {statistics.mean(sl) * 1000:6.2f} ms | có kết quả {sh}")
    print(f"PostgreSQL  : dựng chỉ mục {pb:6.1f} s | p50 {pct(pl, .5):7.2f} ms | p95 {pct(pl, .95):7.2f} ms | "
          f"tb {statistics.mean(pl) * 1000:6.2f} ms | có kết quả {ph} | dung lượng bảng+chỉ mục {size}")


if __name__ == "__main__":
    main()
