.PHONY: help demo datos clean transform figuras verificar todo limpiar

help:
	@echo "make demo      - pipeline completo con datos sinteticos (30 seg)"
	@echo "make datos     - descarga los ultimos 14 dias reales de SEPA"
	@echo "make todo      - clean + transform + figuras + verificacion"
	@echo "make limpiar   - borra data/interim y data/processed"

demo:
	python -m tests.make_fixture --dias 14 --sucursales 180
	$(MAKE) todo

datos:
	python -m src.extract --ultimos 14

todo: clean transform figuras dashboard verificar

clean:
	python -m src.clean

transform:
	python -m src.transform

figuras:
	python -m src.figuras

limpiar:
	rm -rf data/interim/* data/processed/*

verificar:
	python -m tests.test_pipeline

dashboard:
	python -m src.dashboard
