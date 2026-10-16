"""Conservation, event handling, provenance and transport regression checks."""
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pylibstudy.models import EquivalentCircuitModel, synthetic_ocv
from pylibstudy.schema import SimulationInput
from pylibstudy.server import create_server
from pylibstudy.service import SimulationService, export_csv
from pylibstudy.storage import RunRepository


class ModelTests(unittest.TestCase):
    def run_model(self, **changes):
        return EquivalentCircuitModel().simulate(replace(SimulationInput(), **changes))

    def test_coulomb_counting_and_charge_sign(self):
        for mode, sign in [("discharge", 1), ("charge", -1)]:
            result = self.run_model(mode=mode, initial_soc=0.5, duration_min=10, c_rate=0.5)
            self.assertEqual(result.termination, "duration")
            self.assertAlmostEqual(result.summary["final_soc"], 0.5 - sign / 12, places=10)
            self.assertAlmostEqual(result.summary["capacity_ah"], 5 / 12, places=10)
            self.assertGreater(sign * result.summary["energy_wh"], 0)

    def test_rest_preserves_charge_and_has_analytic_cooling(self):
        result = self.run_model(mode="rest", initial_temp_c=40, duration_min=10)
        self.assertEqual(result.summary["capacity_ah"], 0)
        self.assertEqual(result.summary["energy_wh"], 0)
        self.assertEqual(result.summary["final_soc"], 0.95)
        area = result.summary["surface_area_m2"]
        expected = 25 + 15 * math.exp(-10 * area * 600 / 70)
        self.assertAlmostEqual(result.points[-1]["temperature_c"], expected, places=10)

    def test_soc_boundary_not_overshot(self):
        result = self.run_model(initial_soc=0.1, dt_s=60, min_voltage_v=1.5)
        self.assertEqual(result.termination, "soc_empty")
        self.assertAlmostEqual(result.summary["duration_s"], 360, places=8)
        self.assertAlmostEqual(result.summary["capacity_ah"], 0.5, places=8)
        self.assertTrue(all(0 <= p["soc"] <= 1 for p in result.points))

    def test_voltage_event_is_located_between_samples(self):
        for mode, initial, limit, reason in [("discharge", 0.8, 3.6, "lower_voltage"),
                                             ("charge", 0.3, 3.8, "upper_voltage")]:
            config = {"mode": mode, "initial_soc": initial, "dt_s": 60}
            config["min_voltage_v" if mode == "discharge" else "max_voltage_v"] = limit
            result = self.run_model(**config)
            self.assertEqual(result.termination, reason)
            self.assertAlmostEqual(result.summary["final_voltage_v"], limit, places=10)
            self.assertGreater(result.summary["duration_s"], 0)

    def test_initial_outside_limit_stops_at_zero(self):
        result = self.run_model(mode="charge", initial_soc=1)
        self.assertEqual(result.termination, "upper_voltage")
        self.assertEqual(len(result.points), 1)
        self.assertEqual(result.summary["duration_s"], 0)

    def test_lossless_adiabatic_cell_and_rc_response(self):
        result = self.run_model(r0_mohm=0, r1_mohm=0, heat_transfer_w_m2_k=0, duration_min=1)
        self.assertTrue(all(p["temperature_c"] == 25 for p in result.points))
        rc = self.run_model(duration_min=1)
        last = rc.points[-1]
        polarization = synthetic_ocv(last["soc"], "NMC") - 5 * 0.025 - last["voltage_v"]
        self.assertAlmostEqual(polarization, 5 * 0.01 * (1 - math.exp(-60 / 40)), places=12)

    def test_ohmic_adiabatic_heat_balance(self):
        result = self.run_model(r1_mohm=0, heat_transfer_w_m2_k=0, duration_min=10)
        expected = 25 + 5 ** 2 * 0.025 * 600 / 70
        self.assertAlmostEqual(result.points[-1]["temperature_c"], expected, places=10)

    def test_timestep_convergence(self):
        coarse = self.run_model(dt_s=20, duration_min=10)
        fine = self.run_model(dt_s=1, duration_min=10)
        self.assertAlmostEqual(coarse.summary["final_voltage_v"], fine.summary["final_voltage_v"], places=10)
        self.assertLess(abs(coarse.summary["max_temperature_c"] - fine.summary["max_temperature_c"]), 0.01)
        self.assertLess(abs(coarse.summary["energy_wh"] - fine.summary["energy_wh"]), 0.001)

    def test_invalid_and_unbounded_input_rejected(self):
        for data in [{"capacity_ah": float("nan")}, {"dt_s": 0}, {"capacity_ah": True}, {"c_rate": "2"},
                     {"min_voltage_v": 4.3}, {"duration_min": 360, "dt_s": 1}, {"unexpected": 1}, []]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                SimulationInput.from_dict(data)

    def test_templates_finite_in_all_modes(self):
        for chemistry in ["NMC", "LFP"]:
            for mode in ["charge", "discharge", "rest"]:
                result = self.run_model(chemistry=chemistry, mode=mode, initial_soc=0.5)
                self.assertTrue(all(math.isfinite(v) for p in result.points for v in p.values()))


class StorageTests(unittest.TestCase):
    def test_explicit_save_roundtrip_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            service = SimulationService(RunRepository(path))
            data = SimulationInput().snapshot()
            run = service.run(data)
            self.assertEqual(service.repository.list(), [])
            data["capacity_ah"] = 9
            self.assertEqual(run["input"]["capacity_ah"], 5)
            service.save(run["id"])
            service.save(run["id"])
            restarted = SimulationService(RunRepository(path))
            self.assertEqual(restarted.get(run["id"]), run)
            self.assertEqual(len(restarted.repository.list()), 1)
            self.assertNotIn("points", restarted.repository.list()[0])
            self.assertEqual(run["source_type"], "synthetic")
            self.assertEqual(run["validation_status"], "uncalibrated")
            csv = export_csv(run).decode("utf-8-sig")
            self.assertIn("# source_type: synthetic", csv)
            self.assertIn("time_s,voltage_v,current_a,soc,temperature_c,capacity_ah,energy_wh", csv)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = create_server(0, self.directory.name)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, headers=None):
        raw = json.dumps(data).encode() if data is not None else None
        request = Request(self.url + path, data=raw,
                          headers=headers or ({"Content-Type": "application/json"} if raw else {}))
        return urlopen(request, timeout=10)

    def test_simulate_save_read_export_and_static(self):
        for path in ["/", "/app.js", "/model-tabs.js", "/style.css", "/api/config"]:
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
        with self.request("/api/simulate", {"duration_min": 1}) as response:
            run = json.load(response)
        with self.request("/api/runs") as response:
            self.assertEqual(json.load(response), [])
        with self.request("/api/save", {"id": run["id"]}) as response:
            self.assertTrue(json.load(response)["saved"])
        with self.request(f'/api/results/{run["id"]}.json') as response:
            self.assertEqual(json.load(response), run)
            self.assertIn("attachment", response.headers["Content-Disposition"])
        with self.request(f'/api/results/{run["id"]}.csv') as response:
            self.assertIn(b"synthetic", response.read())

    def test_bad_input_and_cross_origin_rejected(self):
        for data, headers, status in [({"capacity_ah": -1}, None, 400),
                                      ({}, {"Content-Type": "application/json", "Origin": "https://example.com"}, 403),
                                      ({}, {"Content-Type": "application/json", "Host": "attacker.invalid"}, 403)]:
            with self.assertRaises(HTTPError) as error:
                self.request("/api/simulate", data, headers)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
        request = Request(self.url + "/api/simulate", data=b"{bad", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=10)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
