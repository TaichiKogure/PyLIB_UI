# Cathode reference data, catalog 2026-10-16.1

`cathodes.v1.json` contains processed reference curves with per-dataset provenance,
original SHA-256, attribution, licence links, experimental conditions, and explicit
processing records. These are cathode/Li references, not validated full-cell OCVs.
See [Japanese methods and operation notes](../../docs/10_公開正極曲線の収集と充放電計算.md).

- NMC111 and NMC523: PyBEP, University of Ljubljana, Faculty of Mechanical
  Engineering, LICeM and contributors; commit f65b19ca5a94648c114c3bdda97c9badc5e65991.
  [Repository](https://github.com/JonPisek/PyBEP), **CC BY-NC-SA 4.0**.
  Original notice is preserved in `PyBEP-LICENSE.txt`. Derived coordinates and
  simplification remain under these data terms.
- LCO: Qian et al. (2018), DOI 10.1038/s41467-018-07296-6, **CC BY 4.0**.
- NMC811: Mao et al. (2023), DOI 10.1038/s41467-023-36853-x, **CC BY 4.0**.
- LMFP/LFP: Su et al. (2022), DOI 10.1038/s41467-022-31792-5, **CC BY 4.0**.
  Curves were extracted from embedded vector figures, not instrument raw tables.
- NMC622/graphite: Wan et al. (2026), DOI 10.1016/j.joule.2026.102531,
  [Zenodo record 20259651](https://zenodo.org/records/20259651), **CC BY 4.0**.

Changes: branch separation, capacity-coordinate normalization, explicit duplicate
or retraced-coordinate handling, and linear-knot simplification. Voltage error
from simplification alone is bounded at 0.5 mV on original advancing coordinates.
Figure-reading and experimental uncertainties are additional. No source-domain
extrapolation is included. Each source's terms apply to its data separately.

`acquisition.json` records fixed PyBEP URLs and the Wan ZIP-member range extraction.
CRC/member SHA verification does not verify the complete 14.4 GB archive MD5.
