.PHONY: install test demo serve clean

install:
	python -m pip install -r incidentops/requirements.txt

test:
	PYTHONPATH=. python -m pytest -q incidentops/tests decision_monitor/tests

demo:
	PYTHONPATH=. python -m incidentops.demo all

serve:
	PYTHONPATH=. python -m uvicorn incidentops.api:app --reload --port 8090

clean:
	rm -f incidentops/data/*.db
	rm -rf incidentops/data/artifacts .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
