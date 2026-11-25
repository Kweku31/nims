# One-slide flowchart template

`flowchart.tex` is an editable 16:9 Beamer slide using TikZ. `flowchart.pdf` is the compiled single-slide version. It illustrates this project's six phases and final TOPSIS decision.

Compile from this directory:

```bash
pdflatex -interaction=nonstopmode -halt-on-error flowchart.tex
```

Upload `flowchart.tex` to Overleaf and select pdfLaTeX, or compile locally with a TeX installation containing Beamer, PGF/TikZ and Latin Modern fonts. No external images are needed.

Edit `\slidetitle`, `\slidesubtitle`, the six `\phasebox` calls and the final decision node. The arrows follow a left-to-right top row and right-to-left second row. To reuse the diagram in a larger presentation, copy the color definitions, TikZ libraries and `\phasebox` command into its preamble, then copy the single frame.

The slide distinguishes model preparation from repeated transfers, and local receiver checks from actual SSH measurements. It reflects the default transfer repetition policy; explicitly configured overrides can change trial counts. Clinical screens are descriptive checks, not proof of clinical safety.

## Departmental defence

The [eight-slide presentation](defence/defence.pdf), [timed speaker notes](defence/speaker_notes.pdf) and [TeXstudio build instructions](defence/README.md) are in the defence subdirectory.
