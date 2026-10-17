# PyBaMM固定環境の公開機能一覧（自動抽出）

版: `26.10.1.0`。取得日: 2026-10-16。計算実行・組合せ互換性の確認ではありません。

再生成: `.\.venv-research\Scripts\python.exe scripts/inventory_pybamm.py`

## lithium_ion

`BaseModel`, `Basic3DThermalSPM`, `BasicDFN`, `BasicDFN2D`, `BasicDFNComposite`, `BasicDFNHalfCell`,
`BasicDFNUnstructured`, `BasicSPM`, `DFN`, `ElectrodeSOHComposite`, `ElectrodeSOHHalfCell`, `MPM`, `MSMR`,
`NewmanTobias`, `SPM`, `SPMe`, `SplitOCVR`, `Yang2017`

## lithium_metal

## sodium_ion

`BasicDFN`

## lead_acid

`BaseModel`, `BasicFull`, `Full`, `LOQS`

## equivalent_circuit

`Thevenin`

## BatteryModelOptions 全項目

| キー                                           | 候補値                                                                                                                                                                                                                                                                     |
|------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `calculate discharge energy`                   | `false`, `true`                                                                                                                                                                                                                                                            |
| `calculate heat source for isothermal models`  | `false`, `true`                                                                                                                                                                                                                                                            |
| `cell geometry`                                | `arbitrary`, `pouch`, `cylindrical`                                                                                                                                                                                                                                        |
| `contact resistance`                           | `false`, `true`                                                                                                                                                                                                                                                            |
| `convection`                                   | `none`, `uniform transverse`, `full transverse`                                                                                                                                                                                                                            |
| `current collector`                            | `uniform`, `potential pair`, `potential pair quite conductive`                                                                                                                                                                                                             |
| `diffusivity`                                  | `single`, `current sigmoid`                                                                                                                                                                                                                                                |
| `dimensionality`                               | `0`, `1`, `2`, `3`                                                                                                                                                                                                                                                         |
| `electrolyte conductivity`                     | `default`, `full`, `leading order`, `composite`, `integrated`                                                                                                                                                                                                              |
| `exchange-current density`                     | `single`, `current sigmoid`                                                                                                                                                                                                                                                |
| `heat of mixing`                               | `false`, `true`                                                                                                                                                                                                                                                            |
| `hydrolysis`                                   | `false`, `true`                                                                                                                                                                                                                                                            |
| `intercalation kinetics`                       | `symmetric Butler-Volmer`, `asymmetric Butler-Volmer`, `linear`, `Marcus`, `Marcus-Hush-Chidsey`, `MSMR`                                                                                                                                                                   |
| `interface utilisation`                        | `full`, `constant`, `current-driven`                                                                                                                                                                                                                                       |
| `lithium plating`                              | `none`, `reversible`, `partially reversible`, `irreversible`                                                                                                                                                                                                               |
| `lithium plating porosity change`              | `false`, `true`                                                                                                                                                                                                                                                            |
| `loss of active material`                      | `none`, `stress-driven`, `asymmetric stress-driven`, `reaction-driven`, `current-driven`, `stress and reaction-driven`, `asymmetric stress and reaction-driven`                                                                                                            |
| `number of MSMR reactions`                     | `none`                                                                                                                                                                                                                                                                     |
| `open-circuit potential`                       | `single`, `current sigmoid`, `MSMR`, `one-state hysteresis`, `one-state differential capacity hysteresis`                                                                                                                                                                  |
| `operating mode`                               | `current`, `voltage`, `power`, `differential power`, `explicit power`, `resistance`, `differential resistance`, `explicit resistance`, `CCCV`                                                                                                                              |
| `particle`                                     | `Fickian diffusion`, `uniform profile`, `quadratic profile`, `quartic profile`, `MSMR`                                                                                                                                                                                     |
| `particle mechanics`                           | `none`, `swelling only`, `swelling and cracking`                                                                                                                                                                                                                           |
| `particle phases`                              | `1`, `2`                                                                                                                                                                                                                                                                   |
| `particle shape`                               | `spherical`, `no particles`                                                                                                                                                                                                                                                |
| `particle size`                                | `single`, `distribution`                                                                                                                                                                                                                                                   |
| `SEI`                                          | `none`, `constant`, `reaction limited`, `reaction limited (asymmetric)`, `solvent-diffusion limited`, `electron-migration limited`, `interstitial-diffusion limited`, `ec reaction limited`, `ec reaction limited (asymmetric)`, `VonKolzenberg2020`, `tunnelling limited` |
| `SEI film resistance`                          | `none`, `distributed`, `average`                                                                                                                                                                                                                                           |
| `SEI on cracks`                                | `false`, `true`                                                                                                                                                                                                                                                            |
| `SEI porosity change`                          | `false`, `true`                                                                                                                                                                                                                                                            |
| `stress-induced diffusion`                     | `false`, `true`                                                                                                                                                                                                                                                            |
| `surface form`                                 | `false`, `differential`, `algebraic`                                                                                                                                                                                                                                       |
| `surface temperature`                          | `ambient`, `lumped`                                                                                                                                                                                                                                                        |
| `thermal`                                      | `isothermal`, `lumped`, `x-lumped`, `x-full`                                                                                                                                                                                                                               |
| `total interfacial current density as a state` | `false`, `true`                                                                                                                                                                                                                                                            |
| `transport efficiency`                         | `Bruggeman`, `ordered packing`, `hyperbola of revolution`, `overlapping spheres`, `tortuosity factor`, `random overlapping cylinders`, `heterogeneous catalyst`, `cation-exchange membrane`                                                                                |
| `voltage as a state`                           | `false`, `true`                                                                                                                                                                                                                                                            |
| `working electrode`                            | `both`, `positive`                                                                                                                                                                                                                                                         |
| `x-average side reactions`                     | `false`, `true`                                                                                                                                                                                                                                                            |
| `use lumped thermal capacity`                  | `false`, `true`                                                                                                                                                                                                                                                            |

## parameter_sets

`Ai2020`, `Bonkile2024`, `Chayambuka2022`, `Chen2020`, `Chen2020_composite`, `ECM_Example`, `Ecker2015`,
`Ecker2015_graphite_halfcell`, `MSMR_Example`, `Marquis2019`, `Mohtat2020`, `NCA_Kim2011`, `OKane2022`,
`OKane2022_graphite_SiOx_halfcell`, `ORegan2022`, `Prada2013`, `Ramadass2004`, `Sulzer2019`, `Xu2019`

## solvers

`AlgebraicSolver`, `BaseSolver`, `CasadiAlgebraicSolver`, `CasadiSolver`, `CompositeSolver`, `DummySolver`,
`IDAKLUSolver`, `JaxSolver`, `NonlinearSolver`, `ScipySolver`

## experiment_steps

`BaseStep`, `BaseStepExplicit`, `BaseStepImplicit`, `BaseTermination`, `CRate`, `CRateTermination`, `ControlKind`,
`CrateTermination`, `Current`, `CurrentTermination`, `CustomStepExplicit`, `CustomStepImplicit`, `CustomTermination`,
`Power`, `Resistance`, `Rest`, `Voltage`, `VoltageTermination`, `c_rate`, `current`, `power`, `resistance`, `rest`,
`string`, `voltage`

