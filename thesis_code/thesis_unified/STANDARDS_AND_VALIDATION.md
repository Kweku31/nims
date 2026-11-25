# Thesis evaluation: standards, evidence and acceptance boundaries

This note documents methodological support for the integrated clinical-data transfer pipeline. These sources justify **which characteristics to measure**. They do **not** define clinical acceptability for a given PCA/autoencoder reconstruction, and the project does not claim ISO certification or regulatory compliance.

## Standards and frameworks

| Source | Scope and relevance to this thesis | Implementation and limitation |
|---|---|---|
| **ISO/IEC 25012:2008, Data quality model**, confirmed current by ISO in 2025 | Structured-data quality characteristics and quality requirements | Profiling, feature/measurement retention, validity and consistency. No standard clinical retention cutoff supplied. [ISO reference](https://committee.iso.org/standard/35736.html) |
| **ISO/IEC 25024:2015, Measurement of data quality**, confirmed current by ISO in 2022 | A quantitative measurement framework for characteristics in ISO/IEC 25012 | Use documented numerators, denominators, units and source/receiver comparison for each metric. The standard does not mandate the study's 80%/95% thresholds. [ISO reference](https://www.iso.org/standard/35749.html) |
| **Kahn et al. (2016)**, EHR data quality taxonomy; DOI 10.13063/2327-9214.1244 | Completeness, conformance and plausibility; verification versus external validation | Organize local checks of null masks, variable presence, value ranges and patient/time structure. Broad bounds are **verification screens**, not external clinical validation. [PubMed](https://pubmed.ncbi.nlm.nih.gov/27713905/) |
| **OHDSI Data Quality Framework** | Data quality in routinely collected health data; includes temporal plausibility | Check missingness, exact protected variables and possible temporal contradictions. OHDSI's published Dashboard is designed for OMOP CDM and is not automatically applicable to arbitrary PhysioNet CSV columns. [OHDSI](https://ohdsi.github.io/TheBookOfOhdsi/DataQuality.html) |
| **NIST FIPS 180-4 (2015), Secure Hash Standard** | Defines SHA-256; supports checking whether received bytes differ from sent bytes | Local file and remote received-file SHA-256; cryptographic hashing alone is not sender authentication. [NIST](https://csrc.nist.gov/pubs/fips/180-4/upd1/final) |
| **NIST SP 800-53 Rev. 5, SI-7** | Information integrity verification | Motivates integrity checks and fail-closed verification. It is guidance for controls; project does not claim certification. [NIST](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final) |
| **IETF RFC 4253 (2006), SSH transport** | Encrypted, authenticated and integrity-protected SSH transport | SCP to the university server with verified SSH host identity, authenticated credentials and remote SHA-256. [RFC](https://www.rfc-editor.org/rfc/rfc4253) |
| **IETF RFC 6349 (2011), TCP throughput testing** | Repeatable actual end-to-end TCP network measurement, conditions such as RTT and network state | Report 10 repeated SCP times, mean, median, standard deviation, p95 and number of successful checks; collect network context if possible. SCP of small files is **not** a conformant RFC 6349 sustained-throughput test. [RFC](https://www.rfc-editor.org/rfc/rfc6349) |

## Map research questions to measurements

1. **Storage and transfer efficiency:** total bytes, archive/payload/manifest overhead, baseline-relative savings, measured packaging time and (if SSH succeeds) repeated SCP upload and remote SHA-256 verification times.
2. **Data quality / analytic utility:** full feature retention and observed measurement retention, exact protected fields and missingness mask, per-feature MAE/RMSE, reconstruction-based R², pairwise-distance correlation and nearest-neighbor overlap; no predictive/clinical performance was measured.
3. **Plausibility:** the existing software currently screens **seven vital-sign variables** (HR, O2Sat, SaO2, Temp, SBP, MAP and DBP) with broad local rules. The percentage of **new** range violations is computed only over observed cells included in those seven screens, not all clinical variables. Even 0% new violations does not establish clinically adequate reconstruction: values may be wrong while remaining within these ranges.
4. **Reproducibility/integrity:** SHA-256 hashes, configurations, reference dataset digest, Phase 4 decoder and flags showing the distinction between local and verified university-side measurements.

## Clinical threshold policy

- No generally applicable ISO, NIST, OHDSI or IETF standard supplies a universal cutoff for PCA/autoencoder **reconstruction R²**, **RMSE**, **patient coverage**, **feature retention** or **new physiological-range violations** in downstream sepsis research.
- Thresholds such as 75% patient coverage, 80% feature retention and 95% observed-measurement retention are **study choices**. Explain and sensitivity-test them; do not cite them as clinically mandated.
- The pipeline explores new-violation cutoffs `0%`, `0.1%`, `0.5%`, `1%` and `5%` as **illustrations of policy sensitivity only**. Set `--maximum-new-violation-pct '1%'` if you wish to use an explicit exploratory gate. A `100%` gate is effectively nonrestrictive.
- For clinical acceptance, add clinician-reviewed variable-specific permissible errors with source and units, and validate downstream research tasks independently on held-out patients. The current study cannot certify clinical interchangeability of a reconstructed record.

## Network provenance policy

- `--transfer-mode ssh` means **real SCP is mandatory**. Missing remote credentials or failed preflight stops the run before Phase 1; failed SSH during Phase 2/6 must never be substituted with simulation.
- `--transfer-mode auto` permits fallback to an idealized transfer formula `size_bits / configured_bandwidth_bits_per_second`, prominently marked `simulated_ideal` and **not actual observed latency**.
- `--transfer-mode simulated` deliberately skips SSH and can be used for pipeline development only.
- `remote_sha256_verified` is true only after successful SSH checksum verification; `receiver_local_checksum_verified` and `receiver_recovery_passed` refer to tests run on the local machine.
- `measured_completely` requires criteria present **and** empirically verified SSH with at least one successful measured trial; a simulation can be ranked provisionally but is never marked fully empirically measured.
- Local unpack and reconstruction measurements are not university-server decoder benchmarks. To claim actual university-side receiver processing time, deploy and time the decoder on the remote system.

## TOPSIS interpretation

TOPSIS produces a preference score **conditional on candidate set, criteria directions, weights and eligibility policy**. Report all these choices and compare distinct balanced, transfer-priority and utility-priority profiles. A custom weight vector identical to an existing profile is not an independent sensitivity scenario; this version excludes such duplicates. Rankings of simulated and SSH-observed packages must never be combined in one pool. Full-fidelity rankings only admit **lossless** deliveries of all source columns, whereas selected-column fidelity only guarantees exact delivery of columns retained after Phase 3.

## Suggested citation for the methodology

Kahn, M. G., et al. (2016). *A Harmonized Data Quality Assessment Terminology and Framework for the Secondary Use of Electronic Health Record Data*. eGEMs 4(1), Article 18. https://doi.org/10.13063/2327-9214.1244

ISO/IEC (2008). *ISO/IEC 25012: Data quality model*. ISO/IEC (2015). *ISO/IEC 25024: Measurement of data quality*. NIST (2015). *FIPS 180-4: Secure Hash Standard*. IETF (2006). *RFC 4253: SSH Transport Layer Protocol*. IETF (2011). *RFC 6349: Framework for TCP Throughput Testing*.
