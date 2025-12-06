from pathlib import Path
from datetime import datetime
import logging
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def bronze_transform(batch_size: int = 20_000):
    """Lee todos los archivos Parquet en `raw/` por batches (pyarrow.dataset) y escribe
    un único archivo Parquet en `data/bronze/bronze_<ts>.parquet`.

    Esto evita concatenar todos los parciales en memoria y permite limpieza por batch.
    Retorna la ruta del Parquet generado.
    """
    repo_dir = Path(__file__).resolve().parents[1]
    raw_dir = repo_dir / 'raw'
    # Buscar recursivamente parquet en `raw/` (p. ej. `raw/unificada/`)
    parquet_files = sorted(raw_dir.rglob('*.parquet'))
    if not parquet_files:
        raise FileNotFoundError(f"No se encontraron archivos parquet en: {raw_dir}")

    dataset = ds.dataset(str(raw_dir), format='parquet')
    scanner = dataset.scanner(batch_size=batch_size)

    out_dir = repo_dir / 'data' / 'bronze'
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_path = out_dir / f'bronze_{ts}.parquet'

    writer = None
    written_batches = 0

    # Attempt to write RecordBatches directly to Parquet to reduce RAM pressure
    for batch in scanner.to_batches():
        try:
            table = pa.Table.from_batches([batch])
        except Exception as e:
            logging.warning(f"No se pudo convertir RecordBatch a Table directamente: {e}. Intentando vía pandas fallback.")
            # Fallback to pandas conversion (slower, higher memory). Keep it minimal.
            try:
                df = batch.to_pandas()
                table = pa.Table.from_pandas(df, preserve_index=False)
            except Exception as e2:
                logging.error(f"Fallback tambien falló: {e2}. Saltando batch.")
                continue

        if writer is None:
            writer = pq.ParquetWriter(str(out_path), table.schema, compression='snappy')

        writer.write_table(table)
        written_batches += 1

    if writer:
        writer.close()

    if written_batches == 0:
        raise RuntimeError('No se escribieron batches al archivo Parquet (dataset vacío?)')

    print(f"Bronze guardado en: {out_path} (batches: {written_batches})")
    return str(out_path)
