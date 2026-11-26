# Reproducing Figures 4.1–4.5

From the directory containing thesis.tex, run the following command. Base R with PNG support is sufficient.

    Rscript Codes/generate_figures.R

The script reads Codes/figure_values.csv and recreates the five PNG files in images/. Titles and figure numbers are supplied by the LaTeX captions in 4.results.tex.

| Figure | Image | Measurements |
|---|---|---|
| 4.1 | baseline_sizes.png | Five direct files, byte count divided by 1,000,000 |
| 4.2 | baseline_times.png | Mean preparation and mean SCP copy times, stacked; checksum time is outside this benchmark |
| 4.3 | feature_retention.png | Seven selected sets, with the 40 original candidate predictors as reference |
| 4.4 | reconstruction_r2.png | Original feature set, standardised observed-cell reconstruction R² for PCA and AE at widths 2, 4, 8 and 16 |
| 4.5 | fresh_data_times.png | Eleven original-feature-set candidates, fresh data, verified SCP and remote recovery, one use per fit |

The extract contains aggregate measurements only. To recreate it from the archived reports and redraw the figures, supply the snapshot directory as the argument.

    Rscript Codes/generate_figures.R /path/to/20261120_083420_390853_UTC_hy7dh134

The source run is 66c57caa1bd63d2ea403. The SHA-256 digests of the input reports are:

    cd1512b697916008b1517d557a257c90cc339ad596ed39415e15aef23328f4cf  03_phase_overview.csv
    71260ecc331fa997792fac6a133a6224a8d14602345a9465ebcbd98c79aeac28  01_integrated_evidence.csv
