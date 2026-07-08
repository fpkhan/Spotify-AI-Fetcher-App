import os
import urllib
import json
import time
import pandas as pd
from sqlalchemy import create_engine, text, event
from sqlalchemy.pool import QueuePool
import ollama
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from server.Credentials import DB_USER as user, DB_PASSWORD as password

# --- SERVER ENGINE SETUP ---
server = 'jio-internship-server.database.windows.net'
database = 'SpotifyDB'
connection_string = (
    f'Driver={{ODBC Driver 18 for SQL Server}};'
    f'Server=tcp:{server},1433;Database={database};'
    f'Uid={user};Pwd={password};'
    f'Encrypt=yes;TrustServerCertificate=no;Connection Timeout=50;'
)
params = urllib.parse.quote_plus(connection_string)

# pool_pre_ping -> detects and discards dead/stale connections before use
# pool_recycle  -> proactively recycle connections before Azure's idle timeout kicks in
#
# NOTE: fast_executemany is intentionally NOT enabled. pyodbc's fast_executemany
# has to pre-size a parameter buffer across the whole batch, and it does this badly
# for VARCHAR(MAX)/large variable-length text (our embedding JSON strings are ~10-15KB
# each and vary in length). In practice this causes it to hang or become extremely
# slow on exactly this kind of data. We avoid the problem entirely below by writing
# through a staging table + single set-based UPDATE instead of a parameterized
# executemany UPDATE.
engine = create_engine(
    f'mssql+pyodbc:///?odbc_connect={params}',
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_recycle=1500,   # recycle every 25 min, well under Azure's ~30 min idle cutoff
)

STAGING_TABLE = "embedding_staging"


def ensure_staging_table(id_sql_type: str = "VARCHAR(32)"):
    """
    Creates a small staging table once, if it doesn't already exist.
    id_sql_type should match track_data.id's type now that it's been narrowed
    from VARCHAR(MAX) to VARCHAR(32) (Spotify track IDs are 22 chars).
    """
    with engine.begin() as conn:
        conn.execute(text(f"""
            IF OBJECT_ID('dbo.{STAGING_TABLE}', 'U') IS NULL
            CREATE TABLE dbo.{STAGING_TABLE} (
                id {id_sql_type} PRIMARY KEY,
                vector VARCHAR(MAX)
            );
        """))

NUM_WORKERS = 8
MAX_RUN_TIME = 3600     # Limit execution to ~1 hour
BATCH_SIZE = 500
EMBEDDING_DIM = 768  # nomic-embed-text output size -- verify with len(ollama.embeddings(...)["embedding"])


def build_enriched_text(row):
    """Converts raw metrics and date text into a semantic sentence structure."""
    def categorize(val, label):
        if val is None or pd.isna(val):
            return ""
        return f"high {label}" if val > 0.7 else f"medium {label}" if val > 0.3 else f"low {label}"

    date_str = str(row.get('release_date', ''))
    year = date_str.split('-')[0] if '-' in date_str else date_str
    year_desc = f"released in {year}" if year.strip() and year.lower() != 'none' else ""

    features = [
        f"Track: {row.get('name', 'Unknown')}",
        f"Artist: {row.get('artists', 'Unknown')}",
        year_desc,
        categorize(row.get('energy'), 'energy'),
        categorize(row.get('danceability'), 'danceability'),
        categorize(row.get('acousticness'), 'acoustic properties'),
        categorize(row.get('valence'), 'happy positive mood')
    ]
    return ", ".join([f for f in features if f])


def process_single_row(row_tuple):
    """Worker function to execute parallel embedding generation via Ollama."""
    index, row = row_tuple
    text_to_embed = build_enriched_text(row)
    try:
        response = ollama.embeddings(model="nomic-embed-text", prompt=text_to_embed)
        return {"vector": json.dumps(response["embedding"]), "id": row['id']}
    except Exception as e:
        return {"error": str(e), "id": row['id']}


def fetch_next_batch(batch_size):
    """Opens a short-lived connection just to read the next batch of un-embedded rows."""
    query = f"""
    SELECT TOP ({batch_size}) id, name, artists, release_date, energy, danceability, acousticness, valence
    FROM track_data
    WHERE embedding IS NULL AND name IS NOT NULL;
    """
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def write_batch(update_payloads):
    """
    Writes an entire batch via a staging table + single set-based UPDATE...JOIN,
    instead of a per-row/executemany parameterized UPDATE (which hangs on VARCHAR(MAX)
    payloads of this size). Steps, all against a fresh short-lived connection:
      1. Empty the staging table.
      2. Multi-row INSERT the batch into staging (plain INSERT, not executemany --
         avoids pyodbc's large-parameter buffering issue entirely).
      3. One UPDATE ... FROM ... JOIN to push staged vectors into track_data.

    Joins on t.id = s.id, both VARCHAR(32) and indexed (per the ALTER TABLE /
    CREATE INDEX statements you already ran on track_data.id). Casts the staged
    JSON-array string explicitly to VECTOR(EMBEDDING_DIM) rather than relying on
    implicit string->vector conversion.
    """
    if not update_payloads:
        return

    df_stage = pd.DataFrame(update_payloads)  # columns: vector, id

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE dbo.{STAGING_TABLE};"))

        # method='multi' builds compact multi-row INSERT statements (INSERT ... VALUES (...),(...),...)
        # rather than parameter-array executemany, so it doesn't hit the fast_executemany/MAX-type issue.
        # chunksize keeps each individual INSERT statement a reasonable size given ~10-15KB per vector.
        df_stage.to_sql(
            STAGING_TABLE,
            con=conn,
            schema="dbo",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=50,
        )

        conn.execute(text(f"""
            UPDATE t
            SET t.embedding = CAST(s.vector AS VECTOR({EMBEDDING_DIM}))
            FROM track_data t
            INNER JOIN dbo.{STAGING_TABLE} s ON t.id = s.id;
        """))


def seed_embeddings_for_one_hour():
    start_time = time.time()
    ensure_staging_table()  # no-op if it already exists
    print(f"Initiating 1-Hour Connection-Isolated Processing (Workers: {NUM_WORKERS}, Batch: {BATCH_SIZE})...")

    while True:
        current_elapsed = time.time() - start_time
        if current_elapsed >= MAX_RUN_TIME:
            print(f"\nTarget execution window reached ({current_elapsed/60:.1f} mins elapsed). Stopping cleanly.")
            break

        t_fetch = time.time()
        df = fetch_next_batch(BATCH_SIZE)
        print(f"[fetch] {time.time() - t_fetch:.2f}s for {len(df)} rows")

        if df.empty:
            print("\nExcellent! No remaining un-embedded rows found in the database layer.")
            break

        remaining_time = MAX_RUN_TIME - current_elapsed
        print(f"[Time remaining: {remaining_time/60:.1f} mins] Processing next {len(df)} empty rows...")

        row_items = list(df.iterrows())

        t_embed = time.time()
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            results = list(tqdm(executor.map(process_single_row, row_items), total=len(row_items)))
        print(f"[embed] {time.time() - t_embed:.2f}s for {len(row_items)} rows")

        update_payloads = []
        for res in results:
            if "error" in res:
                print(f"Skipped ID {res['id']} due to generation failure: {res['error']}")
            else:
                update_payloads.append({"vector": res["vector"], "id": res["id"]})

        t_write = time.time()
        try:
            write_batch(update_payloads)
            print(f"[write] {time.time() - t_write:.2f}s for {len(update_payloads)} rows -> Batch written to Azure.")
        except Exception as db_err:
            print(f"Database transaction error occurred (batch rolled back): {db_err}")
            time.sleep(2)


if __name__ == "__main__":
    try:
        seed_embeddings_for_one_hour()
    except KeyboardInterrupt:
        print("\nScript manually terminated by developer. Progress committed up to this point is safe.")