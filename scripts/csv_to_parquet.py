import argparse
from pathlib import Path
import pandas as pd


def csv_to_parquet(src_csv: str, out_dir: str, chunk_size: int = 500_000, compression: str = 'snappy'):

    src = Path(src_csv)
    out = Path(out_dir)
    if not src.exists():
        raise FileNotFoundError(f"CSV de origen no encontrado: {src}")

    # Prevent writing output into the same folder that contains the source CSV
    src_parent = src.parent.resolve()
    out_resolved = out.resolve()
    if out_resolved == src_parent or src_parent in out_resolved.parents:
        raise ValueError(f"Output directory '{out}' must not be the same as or a subdirectory of the source CSV folder '{src_parent}' — this can cause recursive or repeated outputs.")

    # write into a timestamped subdirectory to avoid collisions and repeated runs producing files in the same folder
    ts = pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out = out / f'parquet_{ts}'
    out.mkdir(parents=True, exist_ok=True)

    reader = pd.read_csv(src, chunksize=chunk_size, low_memory=False)
    written = []
    for i, chunk in enumerate(reader):
        # Opcional: aquí puedes aplicar transformaciones pequeñas antes de guardar
        part_path = out / f'part_{i:05d}.parquet'
        chunk.to_parquet(part_path, index=False, compression=compression, engine='pyarrow')
        written.append(str(part_path))
        print(f'Wrote {part_path}')

    print(f'Done. Wrote {len(written)} parquet files to {out}')
    return written


def main():
    p = argparse.ArgumentParser(description='Convert CSV large to chunked Parquet files')
    # Make positional args optional and provide sensible defaults when omitted
    p.add_argument('src_csv', nargs='charts.csv', default=None, help='CSV source file (example: data/charts.csv)')
    p.add_argument('out_dir', nargs='data/', default=None, help='Output directory for parquet files (example: raw/)')
    p.add_argument('--chunk-size', type=int, default=500_000)
    p.add_argument('--compression', default='snappy')
    args = p.parse_args()

    src = args.src_csv
    out = args.out_dir
    repo_root = Path(__file__).resolve().parents[1]
    if src is None:
        default_src = repo_root / 'data' / 'charts.csv'
        if default_src.exists():
            src = str(default_src)
            print(f"No src_csv proporcionado — usando por defecto: {src}")
        else:
            p.error("src_csv no proporcionado y no se encontró 'data/charts.csv' en el repositorio")
    if out is None:
        default_out = repo_root / 'raw'
        out = str(default_out)
        print(f"No out_dir proporcionado — usando por defecto: {out}")

    csv_to_parquet(src, out, args.chunk_size, args.compression)


if __name__ == '__main__':
    main()
