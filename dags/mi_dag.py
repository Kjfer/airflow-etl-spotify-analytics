from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

# Importar funciones de las capas
from layer.bronze_layer import bronze_transform
from layer.silver_layer import silver_transform
from layer.gold_layer import gold_transform


with DAG(
	dag_id='etl_charts_pipeline',
	start_date=datetime(2025, 11, 20),
	schedule_interval=None,
	catchup=False,
	tags=['etl', 'charts'],
) as dag:

	task_bronze = PythonOperator(
		task_id='bronze_transform',
		python_callable=bronze_transform,
		do_xcom_push=True,
	)

	task_silver = PythonOperator(
		task_id='silver_transform',
		python_callable=silver_transform,
		op_kwargs={'bronze_path': '{{ ti.xcom_pull(task_ids="bronze_transform") }}'},
		do_xcom_push=True,
	)

	task_gold = PythonOperator(
		task_id='gold_transform',
		python_callable=gold_transform,
		op_kwargs={
			'silver_path': '{{ ti.xcom_pull(task_ids="silver_transform") }}',
			'top_n': 20,
		},
	)

	task_bronze >> task_silver >> task_gold



