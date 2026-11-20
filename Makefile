PYTHON ?= python3

.PHONY: all verify mainline figures
all: mainline
	"$(PYTHON)" -B run_all.py figures

verify:
	"$(PYTHON)" -B run_all.py verify

mainline:
	"$(PYTHON)" -B run_all.py mainline

figures:
	"$(PYTHON)" -B run_all.py figures
