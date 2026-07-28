.PHONY: data warehouse train-fraud train-churn ensembles up down test

data:
	python data/generate_synthetic_data.py --out ./data/raw --n-users 20000 --n-clicks 300000

warehouse:
	cd services/churn_prediction/dbt && python load_raw.py && dbt run --profiles-dir . && dbt test --profiles-dir .

train-fraud:
	cd services/click_fraud/training && python train.py

train-churn:
	cd services/churn_prediction/training && python train.py

ensembles-fraud:
	cd shared_ensemble && python compare_ensembles.py --dataset click_fraud

ensembles-churn:
	cd shared_ensemble && python compare_ensembles.py --dataset churn

up:
	docker compose up --build

down:
	docker compose down -v

test:
	pytest services -q
