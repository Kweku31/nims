# Ten-minute Mathematics Department defence

Present `defence.pdf` in full-screen mode. Rehearse with `speaker_notes.pdf`. The notes give eight cues totalling ten minutes, with the clock running continuously from the opening to the recommendation.

| Clock | Slide | Point to make |
|---|---|---|
| 0:00–0:45 | Research question | The receiver needs usable measurements within a delivery budget. |
| 0:45–1:55 | Profile | Count hourly rows for missingness and people for coverage. |
| 1:55–3:10 | Benchmark and select | Changing a file format and dropping a predictor have different consequences. |
| 3:10–4:35 | Reduce | Derive the PCA projection and describe the autoencoder objective. |
| 4:35–5:55 | Evaluate | Read the observed-cell error ratio and the five-neighbour intersection. |
| 5:55–7:10 | Deliver | Trace the five delivery costs and charge initial preparation for fresh data. |
| 7:10–8:40 | Compare transports | Interpret the sign of the median within-block time difference. |
| 8:40–10:00 | Decide | Explain the ideal points, the conditional recommendation and the scope of the evidence. |

## Edit and compile

Keep `defence.tex`, `speaker_notes.tex` and `results.tex` in the same folder. Open either main document in TeXstudio and build with pdfLaTeX, or run the following in this directory.

```sh
pdflatex -halt-on-error defence.tex
pdflatex -halt-on-error defence.tex
pdflatex -halt-on-error speaker_notes.tex
```

The clinical example, definitions and interpretation follow Chapters 3 and 4. Numerical macros in `results.tex` and the dashboard's aggregate reference are generated together by `../../thesis_dashboard/build_thesis_reference.py`. The saved files suffice for offline presentation. The slides report the four widths actually evaluated in Chapter 4, including 16 where feasible.

## Optional demonstration during questions

Open **Thesis walkthrough** in the dashboard. On **Phase 6 · Deliver**, switch the payload from fresh to existing. Then select **Decision**, allow approximation, and compare the winners for the protected feature sets. A second example is **Phase 2 · Benchmark**, where the transport selector changes the paired direct-file ranking. These demonstrations are separate from the ten-minute speaking allocation.
