"""Step 0 compatibility probe, isolated per case with a wall-clock timeout."""
import argparse
import copy
import csv
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / ".test_tmp" / "matplotlib"))
ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "spme_chen": ("SPMe", "Chen2020", {}),
    "dfn_chen": ("DFN", "Chen2020", {}),
    "pybop_spme": ("SPMe", "Chen2020", {}),
    "spme_thermal": ("SPMe", "Chen2020", {"thermal": "lumped"}),
    "dfn_thermal": ("DFN", "Chen2020", {"thermal": "lumped"}),
    "dfn_composite": ("DFN", "Chen2020_composite", {"particle phases": ("2", "1"),
                                                    "open-circuit potential": (("single", "current sigmoid"),
                                                                               "single")}),
    "dfn_plating": ("DFN", "OKane2022", {"lithium plating": "partially reversible"}),
    "dfn_composite_thermal_hysteresis": ("DFN", "Chen2020_composite", {"particle phases": ("2", "1"),
                                                                       "open-circuit potential": (
                                                                           ("single", "current sigmoid"), "single"),
                                                                       "thermal": "lumped"}),
    "dfn_composite_plating_thermal": ("DFN", "Chen2020_composite", {"particle phases": ("2", "1"),
                                                                    "open-circuit potential": (
                                                                        ("single", "current sigmoid"), "single"),
                                                                    "thermal": "lumped",
                                                                    "lithium plating": "partially reversible"}),
}


def worker(case, output):
    import numpy as np
    import pybamm
    start = time.perf_counter()
    result = {"case": case, "enabled": False}
    try:
        model_name, parameter_set, original_options = CASES[case]
        options = copy.deepcopy(original_options)
        result.update(model=model_name, parameter_set=parameter_set, options=copy.deepcopy(options),
                      initial_soc=.5, protocol=["Discharge at C/5 for 30 seconds", "Rest for 10 seconds",
                                                "Charge at C/5 for 30 seconds"],
                      solver="CasadiSolver", rtol=1e-6, atol=1e-6, mesh="PyBaMM defaults")
        parameters = pybamm.ParameterValues(parameter_set)
        model = getattr(pybamm.lithium_ion, model_name)(options=options)
        experiment = pybamm.Experiment(result["protocol"], period="5 seconds")
        simulation = pybamm.Simulation(model, parameter_values=parameters, experiment=experiment,
                                       solver=pybamm.CasadiSolver(mode="safe", rtol=1e-6, atol=1e-6))
        if case == "pybop_spme":
            import pybop
            adapter = pybop.pybamm.Simulator(model, parameter_values=parameters,
                                             initial_state={"Initial SoC": .5}, protocol=experiment,
                                             solver=pybamm.CasadiSolver(mode="safe", rtol=1e-6, atol=1e-6))
            solution = adapter.solve()
        else:
            solution = simulation.solve(initial_soc=.5)
        times = np.linspace(0, float(solution.t[-1]), 71)
        columns = [times, solution["Terminal voltage [V]"](times), solution["Current [A]"](times),
                   solution["Volume-averaged cell temperature [K]"](times) - 273.15]
        if not all(np.isfinite(c).all() for c in columns):
            raise ValueError("nonfinite output")
        with (output / f"{case}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "voltage_v", "current_a", "temperature_c"])
            writer.writerows(zip(*columns))
        result.update(enabled=True, status="solved", termination=solution.termination,
                      end_time_s=float(solution.t[-1]), point_count=len(times),
                      voltage_start_v=float(columns[1][0]), voltage_end_v=float(columns[1][-1]),
                      elapsed_s=time.perf_counter() - start)
    except Exception as error:
        result.update(status="disabled", reason=f"{type(error).__name__}: {str(error)[:1200]}",
                      elapsed_s=time.perf_counter() - start)
    (output / f"{case}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "reference" / "baseline")
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.case:
        worker(args.case, args.output)
        return
    cases = []
    for case in CASES:
        try:
            subprocess.run([sys.executable, __file__, "--case", case, "--output", str(args.output)],
                           check=True, timeout=60, capture_output=True, text=True)
            result = json.loads((args.output / f"{case}.json").read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            result = {"case": case, "enabled": False, "status": "timeout", "reason": "60 s wall-clock limit"}
        except subprocess.CalledProcessError:
            result = {"case": case, "enabled": False, "status": "disabled",
                      "reason": "worker failed; no result accepted"}
        cases.append(result)
        print(f'{case}: {result["status"]}', flush=True)
    distributions = {}
    for dist in metadata.distributions():
        distributions[dist.metadata["Name"]] = {"version": dist.version,
                                                "license": dist.metadata.get("License-Expression") or dist.metadata.get(
                                                    "License") or "see installed LICENSE",
                                                "requires_python": dist.metadata.get("Requires-Python")}
    report = {"python": sys.version, "platform": platform.platform(), "processor": platform.processor(),
              "packages": distributions, "cases": cases,
              "scope": "short compatibility smoke checks; not mesh convergence, fitting, target-cell validation, or UI solver integration"}
    (args.output / "compatibility.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
