# AASIM_PROJECT

uv sync --locked
uv run ruff check .
uv run ruff check . --fix
# Corrección de errores seguros
uv run ruff format --check .
uv run ruff format .
# Correción de formato

# Ejecute el reproducible con el siguiente comando:

latexmk -pdf -xelatex -interaction=nonstopmode -halt-on-error -outdir=build/reports reports/informe.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build/presentacion slides/presentacion.tex
