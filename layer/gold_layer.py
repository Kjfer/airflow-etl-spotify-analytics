import pandas as pd
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import json


def gold_transform(silver_path: str = None, top_n: int = 20, save_plots: bool = True):
    """Genera métricas, gráficas y un dataset agregado (top N) a partir del CSV/Parquet de silver.

    - Lee `silver_path` si se pasa (valida existencia), si no busca el último `silver_*.csv` o `silver_*.parquet`.
    - Produce `data/gold/gold_<ts>.csv` (top-N por streams/rank) y guarda métricas/plots en `processed/gold/<ts>/`.
    - Retorna un dict con rutas: {'csv','metrics','plots', 'count'}
    """
    repo_dir = Path(__file__).resolve().parents[1]
    silver_dir = repo_dir / 'data' / 'silver'

    # Validate or auto-discover
    if silver_path:
        silver_path = Path(silver_path)
        if not silver_path.exists():
            raise FileNotFoundError(f"silver_path proporcionado no existe: {silver_path}")
    else:
        files = sorted(list(silver_dir.glob('silver_*.csv')) + list(silver_dir.glob('silver_*.parquet')))
        if not files:
            raise FileNotFoundError('No se encontró archivo silver en data/silver')
        silver_path = files[-1]

    # Read silver (csv or parquet)
    try:
        if str(silver_path).lower().endswith('.parquet'):
            df = pd.read_parquet(silver_path, engine='pyarrow')
        else:
            df = pd.read_csv(silver_path)
    except Exception:
        df = pd.read_csv(silver_path, header=None)

    # Ensure expected schema
    expected = ['title', 'rank', 'date', 'artist', 'url', 'region', 'chart', 'trend', 'streams']
    if not set(expected).issubset(set(df.columns)):
        if df.shape[1] >= len(expected):
            df = df.iloc[:, :len(expected)]
            df.columns = expected
        else:
            df.columns = [str(c) for c in df.columns]

    # Prepare output dirs
    out_dir = repo_dir / 'data' / 'gold'
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    processed_dir = repo_dir / 'processed' / 'gold' / ts
    plots_dir = processed_dir / 'plots'
    processed_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Normalizations
    if 'url' in df.columns:
        df['track_id'] = df['url'].astype(str).apply(lambda u: str(u).rstrip('/').split('/')[-1] if pd.notna(u) and '/' in str(u) else None)
    if 'streams' in df.columns:
        df['streams'] = pd.to_numeric(df['streams'].astype(str).str.replace(r"[^0-9]", "", regex=True).replace('', '0'), errors='coerce').fillna(0)
    if 'artist' in df.columns:
        df['artist'] = df['artist'].fillna('').astype(str).apply(lambda s: ', '.join([a.strip() for a in s.split(',') if a.strip()]))
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # Select top-N
    if 'streams' in df.columns and df['streams'].notna().any():
        top = df.sort_values('streams', ascending=False).head(top_n)
    elif 'rank' in df.columns:
        df['rank'] = pd.to_numeric(df['rank'], errors='coerce')
        top = df.sort_values('rank', ascending=True).head(top_n)
    else:
        top = df.head(top_n)

    # Save top-N CSV
    csv_path = out_dir / f'gold_{ts}.csv'
    top.to_csv(csv_path, index=False)

    # Metrics
    total_tracks = int(len(df))
    unique_artists = None
    if 'artist' in df.columns:
        exploded = df['artist'].str.split(',').explode().str.strip()
        unique_artists = int(exploded.nunique())
    total_streams = float(df['streams'].sum()) if 'streams' in df.columns else None
    avg_streams = float(df['streams'].mean()) if 'streams' in df.columns else None
    median_streams = float(df['streams'].median()) if 'streams' in df.columns else None

    metrics = {
        'timestamp': ts,
        'total_tracks': total_tracks,
        'unique_artists': unique_artists,
        'total_streams': total_streams,
        'avg_streams': avg_streams,
        'median_streams': median_streams,
        'top_n': top_n,
        'gold_csv': str(csv_path)
    }
    metrics_path = processed_dir / f'metrics_{ts}.json'
    with open(metrics_path, 'w', encoding='utf-8') as mf:
        json.dump(metrics, mf, ensure_ascii=False, indent=2)

    plot_paths = {}
    if save_plots:
        sns.set(style='whitegrid')

        # Streams histogram
        if 'streams' in df.columns:
            plt.figure(figsize=(8, 5))
            sns.histplot(df['streams'].dropna(), bins=30, kde=False)
            plt.title('Distribución de Streams')
            plt.xlabel('Streams')
            plt.ylabel('Count')
            p1 = plots_dir / f'streams_hist_{ts}.png'
            plt.tight_layout()
            plt.savefig(p1)
            plt.close()
            plot_paths['streams_hist'] = str(p1)

        # Top artists by total streams
        if 'artist' in df.columns and 'streams' in df.columns:
            exploded = df[['artist', 'streams']].assign(artist=lambda d: d['artist'].str.split(',')).explode('artist')
            exploded['artist'] = exploded['artist'].str.strip()
            artists_agg = exploded.groupby('artist', dropna=True)['streams'].sum().sort_values(ascending=False).head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=artists_agg.values, y=artists_agg.index)
            plt.title('Top Artists by Streams')
            plt.xlabel('Total Streams')
            plt.ylabel('Artist')
            p2 = plots_dir / f'top_artists_streams_{ts}.png'
            plt.tight_layout()
            plt.savefig(p2)
            plt.close()
            plot_paths['top_artists_streams'] = str(p2)

            top_artists_path = processed_dir / f'top_artists_streams_{ts}.csv'
            artists_agg.reset_index().rename(columns={'artist': 'artist', 'streams': 'total_streams'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_streams_csv'] = str(top_artists_path)

        # Trend distribution
        if 'trend' in df.columns:
            tr = df['trend'].fillna('UNKNOWN')
            tr_counts = tr.value_counts()
            plt.figure(figsize=(8, 5))
            sns.barplot(x=tr_counts.values, y=tr_counts.index)
            plt.title('Trend Distribution')
            plt.xlabel('Count')
            plt.ylabel('Trend')
            p3 = plots_dir / f'trend_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p3)
            plt.close()
            plot_paths['trend_counts'] = str(p3)

        # Tracks per region
        if 'region' in df.columns:
            region_counts = df['region'].fillna('UNKNOWN').value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=region_counts.values, y=region_counts.index)
            plt.title('Tracks per Region')
            plt.xlabel('Count')
            plt.ylabel('Region')
            p4 = plots_dir / f'region_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p4)
            plt.close()
            plot_paths['region_counts'] = str(p4)

        # Time series: streams by date
        if 'date' in df.columns and 'streams' in df.columns:
            try:
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                if df['date_parsed'].notna().sum() > 1:
                    ts_agg = df.groupby('date_parsed')['streams'].sum().sort_index()
                    plt.figure(figsize=(10, 5))
                    sns.lineplot(x=ts_agg.index, y=ts_agg.values)
                    plt.title('Streams over Time')
                    plt.xlabel('Date')
                    plt.ylabel('Total Streams')
                    p5 = plots_dir / f'streams_timeseries_{ts}.png'
                    plt.tight_layout()
                    plt.savefig(p5)
                    plt.close()
                    plot_paths['streams_timeseries'] = str(p5)
            except Exception:
                pass

        # Top artists by appearances (fallback)
        if 'artist' in df.columns:
            top_artists = df['artist'].str.split(',').explode().str.strip().value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=top_artists.values, y=top_artists.index)
            plt.title('Top Artists by Appearances')
            plt.xlabel('Appearances')
            plt.ylabel('Artist')
            p6 = plots_dir / f'top_artists_{ts}.png'
            plt.tight_layout()
            plt.savefig(p6)
            plt.close()
            plot_paths['top_artists'] = str(p6)

            top_artists_path = processed_dir / f'top_artists_{ts}.csv'
            top_artists.reset_index().rename(columns={'index': 'artist', 0: 'appearances'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_csv'] = str(top_artists_path)

    # Logs y retorno
    print(f"Gold CSV guardado: {csv_path}")
    print(f"Métricas guardadas en processed: {metrics_path}")
    if save_plots:
        print(f"Plots guardados en processed: {plots_dir}")

    return {
        'csv': str(csv_path),
        'metrics': str(metrics_path),
        'plots': plot_paths,
        'count': int(total_tracks)
    }
import pandas as pd
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import json


def gold_transform(silver_path: str = None, top_n: int = 20, save_plots: bool = True):
    """Genera métricas, gráficas y un dataset agregado (top N) a partir del CSV de silver.

    Usa las columnas esperadas: title, rank, date, artist, url, region, chart, trend, streams.
    - Guarda el CSV del top-N en `data/gold/`.
    - Guarda métricas y gráficas en `processed/gold/<timestamp>/`.
    """
    repo_dir = Path(__file__).resolve().parents[1]
    silver_dir = repo_dir / 'data' / 'silver'
    if silver_path is None:
        files = sorted(silver_dir.glob('silver_*.csv'))
        if not files:
            raise FileNotFoundError('No se encontró archivo silver en data/silver')
        silver_path = files[-1]

    # Leer CSV
    try:
        df = pd.read_csv(silver_path)
    except Exception:
        df = pd.read_csv(silver_path, header=None)

    # Asegurar nombres esperados
    expected = ['title', 'rank', 'date', 'artist', 'url', 'region', 'chart', 'trend', 'streams']
    if not set(expected).issubset(set(df.columns)):
        if df.shape[1] >= len(expected):
            df = df.iloc[:, :len(expected)]
            df.columns = expected
        else:
            df.columns = [str(c) for c in df.columns]

    # Preparar dirs
    out_dir = repo_dir / 'data' / 'gold'
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    processed_dir = repo_dir / 'processed' / 'gold' / ts
    plots_dir = processed_dir / 'plots'
    processed_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Normalizaciones
    if 'url' in df.columns:
        df['track_id'] = df['url'].astype(str).apply(lambda u: str(u).rstrip('/').split('/')[-1] if pd.notna(u) and '/' in str(u) else None)
    if 'streams' in df.columns:
        df['streams'] = pd.to_numeric(df['streams'].astype(str).str.replace(r"[^0-9]", "", regex=True).replace('', '0'), errors='coerce').fillna(0)
    if 'artist' in df.columns:
        df['artist'] = df['artist'].fillna('').astype(str).apply(lambda s: ', '.join([a.strip() for a in s.split(',') if a.strip()]))
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # Seleccionar top-N: por streams preferentemente, sino por rank (asc)
    if 'streams' in df.columns and df['streams'].notna().any():
        top = df.sort_values('streams', ascending=False).head(top_n)
    elif 'rank' in df.columns:
        df['rank'] = pd.to_numeric(df['rank'], errors='coerce')
        top = df.sort_values('rank', ascending=True).head(top_n)
    else:
        top = df.head(top_n)

    # Guardar CSV del top-N en data/gold
    csv_path = out_dir / f'gold_{ts}.csv'
    top.to_csv(csv_path, index=False)

    # Métricas
    total_tracks = int(len(df))
    unique_artists = None
    if 'artist' in df.columns:
        exploded = df['artist'].str.split(',').explode().str.strip()
        unique_artists = int(exploded.nunique())
    total_streams = float(df['streams'].sum()) if 'streams' in df.columns else None
    avg_streams = float(df['streams'].mean()) if 'streams' in df.columns else None
    median_streams = float(df['streams'].median()) if 'streams' in df.columns else None

    metrics = {
        'timestamp': ts,
        'total_tracks': total_tracks,
        'unique_artists': unique_artists,
        'total_streams': total_streams,
        'avg_streams': avg_streams,
        'median_streams': median_streams,
        'top_n': top_n,
        'gold_csv': str(csv_path)
    }
    metrics_path = processed_dir / f'metrics_{ts}.json'
    with open(metrics_path, 'w', encoding='utf-8') as mf:
        json.dump(metrics, mf, ensure_ascii=False, indent=2)

    plot_paths = {}
    if save_plots:
        sns.set(style='whitegrid')

        # Streams histogram
        if 'streams' in df.columns:
            plt.figure(figsize=(8, 5))
            sns.histplot(df['streams'].dropna(), bins=30, kde=False)
            plt.title('Distribución de Streams')
            plt.xlabel('Streams')
            plt.ylabel('Count')
            p1 = plots_dir / f'streams_hist_{ts}.png'
            plt.tight_layout()
            plt.savefig(p1)
            plt.close()
            plot_paths['streams_hist'] = str(p1)

        # Top artists by total streams
        if 'artist' in df.columns and 'streams' in df.columns:
            exploded = df[['artist', 'streams']].assign(artist=lambda d: d['artist'].str.split(',')).explode('artist')
            exploded['artist'] = exploded['artist'].str.strip()
            artists_agg = exploded.groupby('artist', dropna=True)['streams'].sum().sort_values(ascending=False).head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=artists_agg.values, y=artists_agg.index)
            plt.title('Top Artists by Streams')
            plt.xlabel('Total Streams')
            plt.ylabel('Artist')
            p2 = plots_dir / f'top_artists_streams_{ts}.png'
            plt.tight_layout()
            plt.savefig(p2)
            plt.close()
            plot_paths['top_artists_streams'] = str(p2)

            top_artists_path = processed_dir / f'top_artists_streams_{ts}.csv'
            artists_agg.reset_index().rename(columns={'artist': 'artist', 'streams': 'total_streams'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_streams_csv'] = str(top_artists_path)

        # Trend distribution
        if 'trend' in df.columns:
            tr = df['trend'].fillna('UNKNOWN')
            tr_counts = tr.value_counts()
            plt.figure(figsize=(8, 5))
            sns.barplot(x=tr_counts.values, y=tr_counts.index)
            plt.title('Trend Distribution')
            plt.xlabel('Count')
            plt.ylabel('Trend')
            p3 = plots_dir / f'trend_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p3)
            plt.close()
            plot_paths['trend_counts'] = str(p3)

        # Tracks per region
        if 'region' in df.columns:
            region_counts = df['region'].fillna('UNKNOWN').value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=region_counts.values, y=region_counts.index)
            plt.title('Tracks per Region')
            plt.xlabel('Count')
            plt.ylabel('Region')
            p4 = plots_dir / f'region_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p4)
            plt.close()
            plot_paths['region_counts'] = str(p4)

        # Time series: streams by date
        if 'date' in df.columns and 'streams' in df.columns:
            try:
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                if df['date_parsed'].notna().sum() > 1:
                    ts_agg = df.groupby('date_parsed')['streams'].sum().sort_index()
                    plt.figure(figsize=(10, 5))
                    sns.lineplot(x=ts_agg.index, y=ts_agg.values)
                    plt.title('Streams over Time')
                    plt.xlabel('Date')
                    plt.ylabel('Total Streams')
                    p5 = plots_dir / f'streams_timeseries_{ts}.png'
                    plt.tight_layout()
                    plt.savefig(p5)
                    plt.close()
                    plot_paths['streams_timeseries'] = str(p5)
            except Exception:
                pass

        # Top artists by appearances (fallback)
        if 'artist' in df.columns:
            top_artists = df['artist'].str.split(',').explode().str.strip().value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=top_artists.values, y=top_artists.index)
            plt.title('Top Artists by Appearances')
            plt.xlabel('Appearances')
            plt.ylabel('Artist')
            p6 = plots_dir / f'top_artists_{ts}.png'
            plt.tight_layout()
            plt.savefig(p6)
            plt.close()
            plot_paths['top_artists'] = str(p6)

            top_artists_path = processed_dir / f'top_artists_{ts}.csv'
            top_artists.reset_index().rename(columns={'index': 'artist', 0: 'appearances'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_csv'] = str(top_artists_path)

    # Logs y retorno
    print(f"Gold CSV guardado: {csv_path}")
    print(f"Métricas guardadas en processed: {metrics_path}")
    if save_plots:
        print(f"Plots guardados en processed: {plots_dir}")

    return {
        'csv': str(csv_path),
        'metrics': str(metrics_path),
        'plots': plot_paths,
        'count': int(total_tracks)
    }
import pandas as pd
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import json


def gold_transform(silver_path: str = None, top_n: int = 20, save_plots: bool = True):
    """Genera métricas, gráficas y un dataset agregado (top N) a partir del CSV de silver.

    - Guarda el CSV del top-N en `data/gold/`.
    - Guarda métricas y gráficas en `processed/gold/<timestamp>/`.

    Retorna un dict con rutas: {'csv','metrics','plots': {...}, 'count'}
    """
    repo_dir = Path(__file__).resolve().parents[1]
    silver_dir = repo_dir / 'data' / 'silver'
    if silver_path is None:
        files = sorted(silver_dir.glob('silver_*.csv'))
        if not files:
            raise FileNotFoundError('No se encontró archivo silver en data/silver')
        silver_path = files[-1]

    # Intentar leer CSV; soporta casos sin header
    try:
        df = pd.read_csv(silver_path)
    except Exception:
        df = pd.read_csv(silver_path, header=None)

    # Nombres esperados basados en el sample
    expected_cols = ['track_name', 'position', 'date', 'artists', 'url', 'country', 'chart', 'movement', 'streams']
    if not set(expected_cols).issubset(set(df.columns)):
        if df.shape[1] >= len(expected_cols):
            df = df.iloc[:, :len(expected_cols)]
            df.columns = expected_cols
        else:
            # mantener nombres originales si no encaja
            df.columns = [str(c) for c in df.columns]

    # Preparar directorios
    out_dir = repo_dir / 'data' / 'gold'
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    processed_dir = repo_dir / 'processed' / 'gold' / ts
    plots_dir = processed_dir / 'plots'
    processed_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Normalizaciones y extracción
    if 'url' in df.columns:
        df['track_id'] = df['url'].astype(str).apply(lambda u: str(u).rstrip('/').split('/')[-1] if pd.notna(u) and '/' in str(u) else None)

    if 'streams' in df.columns:
        df['streams'] = (df['streams'].astype(str).str.replace(r"[^0-9]", "", regex=True).replace('', '0').astype(float))

    # Determinar top-N: preferir streams, sino position, sino filas
    if 'streams' in df.columns and df['streams'].notna().any():
        top = df.sort_values('streams', ascending=False).head(top_n)
    elif 'position' in df.columns:
        df['position'] = pd.to_numeric(df['position'], errors='coerce')
        top = df.sort_values('position', ascending=True).head(top_n)
    else:
        top = df.head(top_n)

    # Guardar CSV del top-N en data/gold
    csv_path = out_dir / f'gold_{ts}.csv'
    top.to_csv(csv_path, index=False)

    # Calcular métricas
    total_tracks = int(len(df))
    unique_artists = None
    if 'artists' in df.columns:
        artists_series = df['artists'].fillna('')
        exploded = artists_series.str.split(',').explode().str.strip()
        unique_artists = int(exploded.nunique())

    total_streams = float(df['streams'].sum()) if 'streams' in df.columns else None
    avg_streams = float(df['streams'].mean()) if 'streams' in df.columns else None
    median_streams = float(df['streams'].median()) if 'streams' in df.columns else None

    metrics = {
        'timestamp': ts,
        'total_tracks': total_tracks,
        'unique_artists': unique_artists,
        'total_streams': total_streams,
        'avg_streams': avg_streams,
        'median_streams': median_streams,
        'top_n': top_n,
        'gold_csv': str(csv_path)
    }

    metrics_path = processed_dir / f'metrics_{ts}.json'
    with open(metrics_path, 'w', encoding='utf-8') as mf:
        json.dump(metrics, mf, ensure_ascii=False, indent=2)

    plot_paths = {}
    if save_plots:
        sns.set(style='whitegrid')

        # Streams histogram
        if 'streams' in df.columns:
            plt.figure(figsize=(8, 5))
            sns.histplot(df['streams'].dropna(), bins=30, kde=False)
            plt.title('Distribución de Streams')
            plt.xlabel('Streams')
            plt.ylabel('Count')
            p1 = plots_dir / f'streams_hist_{ts}.png'
            plt.tight_layout()
            plt.savefig(p1)
            plt.close()
            plot_paths['streams_hist'] = str(p1)

        # Top artists by total streams
        if 'artists' in df.columns and 'streams' in df.columns:
            exploded = df[['artists', 'streams']].assign(artists=lambda d: d['artists'].str.split(',')).explode('artists')
            exploded['artists'] = exploded['artists'].str.strip()
            artists_agg = exploded.groupby('artists', dropna=True)['streams'].sum().sort_values(ascending=False).head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=artists_agg.values, y=artists_agg.index)
            plt.title('Top Artists by Streams')
            plt.xlabel('Total Streams')
            plt.ylabel('Artist')
            p2 = plots_dir / f'top_artists_streams_{ts}.png'
            plt.tight_layout()
            plt.savefig(p2)
            plt.close()
            plot_paths['top_artists_streams'] = str(p2)

            top_artists_path = processed_dir / f'top_artists_streams_{ts}.csv'
            artists_agg.reset_index().rename(columns={'artists': 'artist', 'streams': 'total_streams'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_streams_csv'] = str(top_artists_path)

        # Movement distribution
        if 'movement' in df.columns:
            mv = df['movement'].fillna('UNKNOWN')
            mv_counts = mv.value_counts()
            plt.figure(figsize=(8, 5))
            sns.barplot(x=mv_counts.values, y=mv_counts.index)
            plt.title('Movement Distribution')
            plt.xlabel('Count')
            plt.ylabel('Movement')
            p3 = plots_dir / f'movement_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p3)
            plt.close()
            plot_paths['movement_counts'] = str(p3)

        # Tracks per country
        if 'country' in df.columns:
            country_counts = df['country'].fillna('UNKNOWN').value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=country_counts.values, y=country_counts.index)
            plt.title('Tracks per Country')
            plt.xlabel('Count')
            plt.ylabel('Country')
            p4 = plots_dir / f'country_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p4)
            plt.close()
            plot_paths['country_counts'] = str(p4)

        # Time series: streams by date (si hay varias fechas)
        if 'date' in df.columns and 'streams' in df.columns:
            try:
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                if df['date_parsed'].notna().sum() > 1:
                    ts_agg = df.groupby('date_parsed')['streams'].sum().sort_index()
                    plt.figure(figsize=(10, 5))
                    sns.lineplot(x=ts_agg.index, y=ts_agg.values)
                    plt.title('Streams over Time')
                    plt.xlabel('Date')
                    plt.ylabel('Total Streams')
                    p5 = plots_dir / f'streams_timeseries_{ts}.png'
                    plt.tight_layout()
                    plt.savefig(p5)
                    plt.close()
                    plot_paths['streams_timeseries'] = str(p5)
            except Exception:
                pass

        # Top artists by appearances (fallback) and save CSV
        if 'artists' in df.columns:
            artists_series = df['artists'].fillna('')
            top_artists = artists_series.str.split(',').explode().str.strip().value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=top_artists.values, y=top_artists.index)
            plt.title('Top Artists by Appearances')
            plt.xlabel('Appearances')
            plt.ylabel('Artist')
            p6 = plots_dir / f'top_artists_{ts}.png'
            plt.tight_layout()
            plt.savefig(p6)
            plt.close()
            plot_paths['top_artists'] = str(p6)

            top_artists_path = processed_dir / f'top_artists_{ts}.csv'
            top_artists.reset_index().rename(columns={'index': 'artist', 0: 'appearances'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_csv'] = str(top_artists_path)

    # Logs y retorno
    print(f"Gold CSV guardado: {csv_path}")
    print(f"Métricas guardadas en processed: {metrics_path}")
    if save_plots:
        print(f"Plots guardados en processed: {plots_dir}")

    return {
        'csv': str(csv_path),
        'metrics': str(metrics_path),
        'plots': plot_paths,
        'count': int(total_tracks)
    }
import pandas as pd
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import json
import os


def gold_transform(silver_path: str = None, top_n: int = 20, save_plots: bool = True):

    repo_dir = Path(__file__).resolve().parents[1]
    silver_dir = repo_dir / 'data' / 'silver'
    if silver_path is None:
        files = sorted(silver_dir.glob('silver_*.csv'))
        if not files:
            raise FileNotFoundError('No se encontró archivo silver en data/silver')
        silver_path = files[-1]



    out_dir = repo_dir / 'data' / 'gold'
    plots_dir = out_dir / 'plots'
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

    if save_plots:
        sns.set(style='whitegrid')

        # Streams histogram
        if 'streams' in df.columns:
            plt.figure(figsize=(8, 5))
            sns.histplot(df['streams'].dropna(), bins=30, kde=False)
            plt.title('Distribución de Streams')
            plt.xlabel('Streams')
            plt.ylabel('Count')
            p1 = plots_dir / f'streams_hist_{ts}.png'
            plt.tight_layout()
            plt.savefig(p1)
            plt.close()
            plot_paths['streams_hist'] = str(p1)

        # Top artists by total streams
        if 'artists' in df.columns and 'streams' in df.columns:
            artists_series = df['artists'].fillna('')
            exploded = df[['artists', 'streams']].assign(artists=lambda d: d['artists'].str.split(',')).explode('artists')
            exploded['artists'] = exploded['artists'].str.strip()
            artists_agg = exploded.groupby('artists', dropna=True)['streams'].sum().sort_values(ascending=False).head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=artists_agg.values, y=artists_agg.index)
            plt.title('Top Artists by Streams')
            plt.xlabel('Total Streams')
            plt.ylabel('Artist')
            p2 = plots_dir / f'top_artists_streams_{ts}.png'
            plt.tight_layout()
            plt.savefig(p2)
            plt.close()
            plot_paths['top_artists_streams'] = str(p2)

            top_artists_path = out_dir / f'top_artists_streams_{ts}.csv'
            artists_agg.reset_index().rename(columns={'artists': 'artist', 'streams': 'total_streams'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_streams_csv'] = str(top_artists_path)

        # Movement distribution
        if 'movement' in df.columns:
            mv = df['movement'].fillna('UNKNOWN')
            mv_counts = mv.value_counts()
            plt.figure(figsize=(8, 5))
            sns.barplot(x=mv_counts.values, y=mv_counts.index)
            plt.title('Movement Distribution')
            plt.xlabel('Count')
            plt.ylabel('Movement')
            p3 = plots_dir / f'movement_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p3)
            plt.close()
            plot_paths['movement_counts'] = str(p3)

        # Tracks per country
        if 'country' in df.columns:
            country_counts = df['country'].fillna('UNKNOWN').value_counts().head(20)
            plt.figure(figsize=(10, 6))
            sns.barplot(x=country_counts.values, y=country_counts.index)
            plt.title('Tracks per Country')
            plt.xlabel('Count')
            plt.ylabel('Country')
            p4 = plots_dir / f'country_counts_{ts}.png'
            plt.tight_layout()
            plt.savefig(p4)
            plt.close()
            plot_paths['country_counts'] = str(p4)

        # Time series: streams by date (si hay varias fechas)
        if 'date' in df.columns and 'streams' in df.columns:
            try:
                df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
                if df['date_parsed'].notna().sum() > 1:
                    ts_agg = df.groupby('date_parsed')['streams'].sum().sort_index()
                    plt.figure(figsize=(10, 5))
                    sns.lineplot(x=ts_agg.index, y=ts_agg.values)
                    plt.title('Streams over Time')
                    plt.xlabel('Date')
                    plt.ylabel('Total Streams')
                    p5 = plots_dir / f'streams_timeseries_{ts}.png'
                    plt.tight_layout()
                    plt.savefig(p5)
                    plt.close()
                    plot_paths['streams_timeseries'] = str(p5)
            except Exception:
                pass
            sns.barplot(x=top_artists.values, y=top_artists.index)
            plt.title('Top Artists by Appearances')
            plt.xlabel('Appearances')
            plt.ylabel('Artist')
            p3 = plots_dir / f'top_artists_{ts}.png'
            plt.tight_layout()
            plt.savefig(p3)
            plt.close()
            plot_paths['top_artists'] = str(p3)

            # también guardar CSV de top artists
            top_artists_path = out_dir / f'top_artists_{ts}.csv'
            top_artists.reset_index().rename(columns={'index': 'artist', 0: 'appearances'}).to_csv(top_artists_path, index=False)
            plot_paths['top_artists_csv'] = str(top_artists_path)

    print(f"Gold CSV guardado: {csv_path}")
    print(f"Métricas guardadas: {metrics_path}")
    if save_plots:
        print(f"Plots guardados en: {plots_dir}")

    return {
        'csv': str(csv_path),
        'metrics': str(metrics_path),
        'plots': plot_paths,
        'count': int(total_tracks)
    }
