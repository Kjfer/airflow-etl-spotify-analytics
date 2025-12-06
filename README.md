**Airflow ETL Spotify Analytics**

Guía paso a paso para iniciar, configurar y ejecutar este proyecto ETL orquestado con Apache Airflow.

**Resumen**: Este repositorio contiene un pipeline ETL sencillo (capas bronze -> silver -> gold) que lee un CSV fuente (`raw/charts.csv`), realiza transformaciones con `pandas` y produce métricas y gráficos guardados en `processed/gold/<timestamp>/`.

**Requisitos previos**:
- **Docker Desktop** (Windows) o Docker Engine y Docker Compose v2.
- Espacio libre: al menos 10 GB y 4 GB de RAM recomendados para ejecutar Airflow con Docker.
- `git` y acceso a la terminal PowerShell.

**Estructura del proyecto (resumen)**
- `dags/` : DAGs de Airflow (`mi_dag.py`, `mi_pipeline.py`)
- `layer/` : implementaciones de las capas ETL (`bronze_layer.py`, `silver_layer.py`, `gold_layer.py`)
- `raw/charts.csv` : CSV fuente (debe existir localmente)
- `data/` : salidas intermedias `data/bronze/`, `data/silver/`, `data/gold/`
- `processed/` : métricas y gráficas (ej. `processed/gold/<timestamp>/`)
- `requirements.txt` : dependencias Python del proyecto
- `docker-compose.yaml` : stack de desarrollo para Airflow (Postgres + Redis + Airflow)

1) Clonar y preparar el repositorio
```powershell
cd C:\ruta\donde\quieras
git clone <url-del-repo>
cd airflow-etl-spotify-analytics
```

2) Revisar/añadir `requirements.txt`
- Asegúrate de que `requirements.txt` contenga las librerías necesarias (ej. `pandas`, `requests`, `python-dotenv`, `matplotlib`, `seaborn`).
- Si vas a añadir paquetes que necesitan compilación nativa (por ejemplo `lxml`, `some-c-ext`), deberás instalar dependencias de sistema en la imagen Docker.

3) Opciones para instalar dependencias en los contenedores Airflow

Opción A (recomendada): construir imagen Docker personalizada (persistente)
- El `docker-compose.yaml` está configurado para usar `build:` en la sección común; lo ideal es tener un `Dockerfile` en la raíz con contenido como el siguiente (si no existe, crea un archivo `Dockerfile`):

```dockerfile
FROM apache/airflow:2.7.1
USER root
COPY requirements.txt /requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    libpq-dev libxml2-dev libxslt1-dev ca-certificates && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r /requirements.txt
USER airflow
```

- Construir y levantar (PowerShell):
```powershell
cd C:\airflow-etl\airflow-etl-spotify-analytics
docker-compose build
docker-compose up -d
```

Opción B (rápida / temporal): usar `_PIP_ADDITIONAL_REQUIREMENTS` al levantar
- Esto instala las dependencias cada vez que se inicia el contenedor (más lento):
```powershell
$env:_PIP_ADDITIONAL_REQUIREMENTS = "pandas requests python-dotenv matplotlib seaborn"
docker-compose up -d
```

4) Comprobar que Airflow está arriba
- Abre `http://localhost:8080` en tu navegador. Usuario y contraseña por defecto (si no los cambiaste) suelen ser `airflow`/`airflow` (el `docker-compose.yaml` tiene opciones para crear el usuario inicial).
- Logs del webserver (PowerShell):
```powershell
docker-compose logs -f airflow-webserver
```

5) Inicializar/metadatos si es necesario
- El servicio `airflow-init` en `docker-compose.yaml` suele encargarse de inicializar la DB. Si necesitas crear un usuario manualmente:
```powershell
docker-compose exec airflow-webserver airflow users create \
  --username admin --firstname Admin --lastname User --role Admin --email admin@example.com
```

6) Ver y ejecutar el DAG
- El DAG principal se encuentra en `dags/mi_dag.py`. Abre Airflow UI y habilita / desencadena el DAG (id dentro del archivo `mi_dag.py`).
- Alternativa desde CLI (trigger):
```powershell
docker-compose exec airflow-cli airflow dags trigger <dag_id>
```

7) Ejecutar tareas manualmente (debug / pruebas)
- Puedes ejecutar las funciones de las capas dentro del contenedor para debug rápido:
```powershell
docker-compose exec airflow-webserver bash
python -c "from layer.bronze_layer import bronze_transform; print(bronze_transform())"
python -c "from layer.silver_layer import silver_transform; print(silver_transform())"
python -c "from layer.gold_layer import gold_transform; print(gold_transform())"
```

8) Rutas de datos y artefactos
- CSV fuente: `raw/charts.csv` (proporciónalo antes de lanzar el DAG)
- Bronze: `data/bronze/bronze_<ts>.csv`
- Silver: `data/silver/silver_<ts>.csv`
- Gold: `data/gold/gold_<ts>.csv` (top-N)
- Métricas y plots: `processed/gold/<timestamp>/metrics_<ts>.json` y `processed/gold/<timestamp>/plots/*.png`

9) Actualizar dependencias
- Si actualizas `requirements.txt`, reconstruye la imagen:
```powershell
docker-compose build
docker-compose up -d
```

10) Troubleshooting común
- Error pip install por falta de headers / compilador: añade dependencias de sistema al `Dockerfile` (ej. `build-essential`, `libpq-dev`, `libxml2-dev`) y reconstruye.
- Volúmenes en Windows: si ves errores de permisos, crea las carpetas locales manualmente (`dags`, `logs`, `plugins`) y asegúrate de que Docker Desktop tiene acceso al disco.
- Si Airflow no muestra DAGs: revisa que `dags` esté mapeado correctamente en `docker-compose.yaml` y que el archivo tenga sintaxis válida y esté en la ruta correcta.

11) Buenas prácticas y próximos pasos
- Hacer determinista el paso de artefactos entre tareas del DAG usando XComs o `op_kwargs` (actualmente las funciones buscan el archivo más reciente en `data/silver`).
- Añadir validaciones de esquema (`pandera`) y pruebas unitarias para las transformaciones.
- Añadir CI que construya la imagen y ejecute pruebas.

Si quieres, puedo:
- (A) Añadir un `Dockerfile` aquí con dependencias de sistema listadas listo para usar.  
- (B) Modificar `docker-compose.yaml` para usar `image:` + `build:` consistentemente o dejar instrucciones para usar `_PIP_ADDITIONAL_REQUIREMENTS`.
- (C) Añadir comandos de ejemplo para Windows que creen el `Dockerfile` automáticamente.

---

Archivo de referencia rápido (ejemplo de `Dockerfile` para copiar):
```dockerfile
FROM apache/airflow:2.7.1
USER root
COPY requirements.txt /requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev libxml2-dev libxslt1-dev ca-certificates && \
    pip install --upgrade pip && pip install --no-cache-dir -r /requirements.txt
USER airflow
```

Gracias — dime si quieres que yo cree el `Dockerfile` automáticamente o pruebe levantar el stack desde aquí.
