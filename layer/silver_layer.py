import pandas as pd
from pathlib import Path
from datetime import datetime


def silver_transform(bronze_path: str = None):
    repo_dir = Path(__file__).resolve().parents[1]
    bronze_dir = repo_dir / 'data' / 'bronze'
    # If bronze_path provided by XCom, validate it; otherwise auto-discover latest bronze file
    if bronze_path:
        bronze_path = Path(bronze_path)
        if not bronze_path.exists():
            raise FileNotFoundError(f"bronze_path proporcionado no existe: {bronze_path}")
    else:
        # auto-discover latest bronze file
        files = sorted(list(bronze_dir.glob('bronze_*.parquet')) + list(bronze_dir.glob('bronze_*.csv')))
        if not files:
            raise FileNotFoundError('No se encontró archivo bronze en data/bronze')
        bronze_path = files[-1]

    # Read bronze: support parquet or csv
    try:
        if str(bronze_path).lower().endswith('.parquet'):
            df = pd.read_parquet(bronze_path, engine='pyarrow')
        else:
            df = pd.read_csv(bronze_path)
    except Exception:
        # fallback: try reading CSV without header
        df = pd.read_csv(bronze_path, header=None)
import pandas as pd
from pathlib import Path
from datetime import datetime
import pyarrow.dataset as ds


def _normalize_and_finalize_df(df: pd.DataFrame) -> pd.DataFrame:
    # Normalizar nombres de columnas
    df.columns = [str(c).lower().strip() for c in df.columns]

    # Si el archivo vino sin encabezado y contiene las 9 columnas esperadas,
    # reasignar nombres para facilitar transformaciones posteriores
    expected = ['title', 'rank', 'date', 'artist', 'url', 'region', 'chart', 'trend', 'streams']
    if df.shape[1] >= len(expected) and not set(expected).issubset(set(df.columns)):
        df = df.iloc[:, :len(expected)]
        df.columns = expected

    # Limpieza básica de cadenas
    obj_cols = df.select_dtypes(include=['object']).columns.tolist()
    for c in obj_cols:
        df[c] = df[c].astype(str).str.strip().replace({'nan': None})

    # Parsing y conversión de tipos
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # Extraer track id desde la URL si existe (último segmento)
    if 'url' in df.columns:
        df['track_id'] = df['url'].astype(str).apply(lambda u: str(u).rstrip('/').split('/')[-1] if pd.notna(u) and '/' in str(u) else None)

    # Normalizar artist
    if 'artist' in df.columns:
        df['artist'] = df['artist'].fillna('').astype(str).apply(lambda s: ', '.join([a.strip() for a in s.split(',') if a.strip()]))

    # Streams -> numérico
    if 'streams' in df.columns:
        df['streams'] = pd.to_numeric(df['streams'].astype(str).str.replace(r"[^0-9]", "", regex=True).replace('', '0'), errors='coerce').fillna(0)

    # Eliminar filas sin title
    if 'title' in df.columns:
        df = df[df['title'].notna()]

    # Deduplicado por keys preferidas
    dedup_keys = []
    if 'track_id' in df.columns and 'date' in df.columns:
        dedup_keys = ['track_id', 'date']
    elif 'track_id' in df.columns:
        dedup_keys = ['track_id']
    elif 'title' in df.columns and 'date' in df.columns:
        dedup_keys = ['title', 'date']

    if dedup_keys:
        if 'streams' in df.columns:
            df = df.sort_values('streams', ascending=False)
        df = df.drop_duplicates(subset=dedup_keys, keep='first')
    else:
        df = df.drop_duplicates()

    # Columnas derivadas
    if 'streams' in df.columns:
        df['streams_millions'] = (df['streams'] / 1_000_000).round(3)

    return df


def silver_transform(bronze_path: str = None, batch_size: int = 20_000):
    """Transformación silver procesando Parquet por batches para ahorrar memoria.

    Si `bronze_path` apunta a un Parquet, usa `pyarrow.dataset` para iterar por
    RecordBatches y escribe el CSV en `data/silver/` por append.
    Para CSV de entrada cae a `pandas.read_csv` (sin chunksize por compatibilidad).
    """
    repo_dir = Path(__file__).resolve().parents[1]
    bronze_dir = repo_dir / 'data' / 'bronze'

    # Resolver bronze_path
    if bronze_path:
        bronze_path = Path(bronze_path)
        if not bronze_path.exists():
            raise FileNotFoundError(f"bronze_path proporcionado no existe: {bronze_path}")
    else:
        files = sorted(list(bronze_dir.glob('bronze_*.parquet')) + list(bronze_dir.glob('bronze_*.csv')))
        if not files:
            raise FileNotFoundError('No se encontró archivo bronze en data/bronze')
        bronze_path = files[-1]

    out_dir = repo_dir / 'data' / 'silver'
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_path = out_dir / f'silver_{ts}.csv'

    # Si es parquet, procesar por batches
    if str(bronze_path).lower().endswith('.parquet'):
        dataset = ds.dataset(str(bronze_path), format='parquet')
        scanner = dataset.scanner(batch_size=batch_size)

        first = True
        total_rows = 0
        for batch in scanner.to_batches():
            try:
                df_batch = batch.to_pandas()
            except Exception:
                # fallback mínimo: convertir via Table
                try:
                    import pyarrow as pa
                    table = pa.Table.from_batches([batch])
                    df_batch = table.to_pandas()
                except Exception:
                    continue

            df_batch = _normalize_and_finalize_df(df_batch)
            if first:
                df_batch.to_csv(out_path, index=False, mode='w')
                first = False
            else:
                df_batch.to_csv(out_path, index=False, header=False, mode='a')
            total_rows += len(df_batch)

        if total_rows == 0:
            raise RuntimeError('No se generó ninguna fila durante silver_transform (dataset vacío?)')

        print(f"Silver guardado en: {out_path} (filas: {total_rows})")
        return str(out_path)

    # Si es CSV, leer con pandas (no es lo ideal para CSVs enormes)
    try:
        df = pd.read_csv(bronze_path)
    except Exception:
        df = pd.read_csv(bronze_path, header=None)

    df = _normalize_and_finalize_df(df)
    df.to_csv(out_path, index=False)
    print(f"Silver guardado en: {out_path} (filas: {len(df)})")
    return str(out_path)
