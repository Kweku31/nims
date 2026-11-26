#!/usr/bin/env bash
# Run the same pdfLaTeX build as TeXstudio until the references settle.
set -euo pipefail
cd -- "$(dirname -- "$0")"
for pass in 1 2 3; do
    pdflatex -synctex=1 -file-line-error -interaction=nonstopmode -halt-on-error thesis.tex > thesis-build.log || {
        tail -35 thesis-build.log >&2
        exit 1
    }
done
