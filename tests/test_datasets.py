"""Import semantics, original preservation, project isolation and restart checks."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import test_simulation
from pylibstudy.datasets import import_curve, demo_request, table_preview
from pylibstudy.service import SimulationService, export_csv
from pylibstudy.storage import RunRepository


def request_data(text="t,v,i\n0,4100,-1000\n1,4000,-1000\n", **kwargs):
    result = {"text": text, "name": "試験", "current_sign": "charge_positive", "mapping": {
        "time_s": {"column": "t", "unit": "min"}, "voltage_v": {"column": "v", "unit": "mV"},
        "current_a": {"column": "i", "unit": "mA"}}}
    result.update(kwargs)
    return result


class ImportTests(unittest.TestCase):
    def test_units_sign_and_current_integral(self):
        run, _ = import_curve(request_data())
        last = run["points"][-1]
        self.assertEqual(last["time_s"], 60)
        self.assertEqual(last["voltage_v"], 4)
        self.assertEqual(last["current_a"], 1)
        self.assertAlmostEqual(last["capacity_ah"], 1 / 60)
        self.assertIsNone(last["soc"])
        self.assertIsNone(last["temperature_c"])
        self.assertEqual(run["validation_status"], "not_validated")

    def test_missing_reset_and_duplicate_preserved(self):
        run, _ = import_curve(request_data("t,v,i\n0,4100,-1000\n1,,-1000\n1,4000,0\n0,3900,-1000\n1,3800,-1000\n"))
        self.assertEqual(len(run["points"]), 5)
        self.assertEqual(run["quality"]["segment_count"], 2)
        self.assertIsNone(run["points"][1]["voltage_v"])
        self.assertEqual(run["points"][2]["current_a"], 0)
        self.assertEqual(run["points"][3]["capacity_ah"], 0)
        self.assertAlmostEqual(run["points"][4]["capacity_ah"], 1 / 60)
        self.assertEqual({i["kind"] for i in run["quality"]["issues"]}, {"missing", "time_reset", "duplicate_time"})

    def test_missing_current_never_bridges_integral(self):
        run, _ = import_curve(request_data("t,v,i\n0,4100,1000\n1,4000,\n2,3900,1000\n3,3800,1000\n"))
        self.assertTrue(all(p["capacity_ah"] is None for p in run["points"][1:]))

    def test_reversal_integrates_absolute_linear_current(self):
        run, _ = import_curve(request_data("t,v,i\n0,4100,-1000\n1,4000,1000\n"))
        self.assertAlmostEqual(run["points"][-1]["capacity_ah"], 1 / 120)

    def test_unsigned_current_requires_explicit_direction(self):
        data = request_data("t,v,i,md\n0,4100,1000,C\n1,4000,1000,D\n2,4000,0,R\n", current_sign="direction_column")
        data["mapping"]["direction"] = {"column": "md"}
        run, _ = import_curve(data)
        self.assertEqual([p["current_a"] for p in run["points"]], [-1, 1, 0])
        data["text"] = "t,v,i,md\n0,4100,1000,?\n"
        with self.assertRaisesRegex(ValueError, "区分値が未定義"):
            import_curve(data)

    def test_capacity_only_and_soc_ocv_do_not_invent_dynamic_values(self):
        run, _ = import_curve({"text": "q;v\n100;3,7\n200;3,6\n", "delimiter": ";", "decimal": ",",
                               "shape": "capacity_voltage", "mode": "discharge", "mapping": {
                "capacity_ah": {"column": "q", "unit": "mAh"}, "voltage_v": {"column": "v", "unit": "V"}}})
        self.assertEqual(run["points"][0]["capacity_ah"], .1)
        self.assertEqual(run["points"][0]["voltage_v"], 3.7)
        self.assertIsNone(run["points"][0]["time_s"])
        self.assertIsNone(run["points"][0]["current_a"])
        ocv, _ = import_curve({"text": "soc,v,T\n50,3.7,298.15\n", "shape": "soc_ocv", "mapping": {
            "soc": {"column": "soc", "unit": "%"}, "voltage_v": {"column": "v", "unit": "V"},
            "temperature_c": {"column": "T", "unit": "K"}}})
        self.assertEqual(ocv["points"][0]["soc"], .5)
        self.assertAlmostEqual(ocv["points"][0]["temperature_c"], 25)

    def test_nonfinite_text_and_bad_shape_rejected(self):
        for value in ["NaN", "inf", "1e999", "invalid"]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "3行目"):
                import_curve(request_data(f"t,v,i\n0,4100,-1000\n1,{value},-1000\n"))
        for changes in [{"source_type": "public_measured"}, {"shape": "capacity_voltage"},
                        {"current_sign": "absolute"}, {"header_row": 0}, {"mapping": {}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                import_curve(request_data(**changes))

    def test_cp932_header_and_original_exact_bytes(self):
        raw = "試験記録\r\nt,v,i\r\n0,4100,-1000\r\n1,4000,-1000\r\n".encode("cp932")
        data = request_data(content_base64=base64.b64encode(raw).decode(), encoding="cp932", header_row=2)
        run, original = import_curve(data)
        self.assertEqual(raw, original)
        self.assertEqual(run["original"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(run["points"][0]["source_row"], 3)
        self.assertEqual(table_preview(data)["headers"], ["t", "v", "i"])

    def test_demo_seed_repeatable_and_recorded(self):
        first, raw = import_curve(demo_request(seed=42))
        again, second = import_curve(demo_request(seed=42))
        other, third = import_curve(demo_request(seed=7))
        self.assertEqual(raw, second)
        self.assertNotEqual(raw, third)
        self.assertEqual(first["source_type"], "synthetic_demo")
        self.assertIn("seed=42", first["notes"])

    def test_restart_original_duplicate_project_and_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            repository = RunRepository(path)
            service = SimulationService(repository)
            project = repository.create_project("公開実測")
            data = request_data(project_id=project["id"], notes="原条件を保持")
            run = service.preview_import(data)
            self.assertEqual(repository.list(), [])
            service.save(run["id"]);
            service.save(run["id"])
            data["notes"] = "編集してもsnapshot不変"
            self.assertEqual(run["notes"], "原条件を保持")
            comparison = repository.save_comparison({"project_id": project["id"], "dataset_ids": [run["id"]],
                                                     "name": "比較", "notes": "区間比較", "variable": "voltage_v",
                                                     "x_axis": "time_s"})
            restarted = SimulationService(RunRepository(path))
            self.assertEqual(restarted.get(run["id"]), run)
            self.assertEqual(restarted.original(run["id"]), data["text"].encode())
            self.assertEqual(restarted.repository.list("default"), [])
            self.assertEqual(len(restarted.repository.list(project["id"])), 1)
            self.assertEqual(restarted.repository.comparisons(project["id"]), [comparison])
            self.assertEqual(restarted.preview_import(data)["duplicate_ids"], [run["id"]])
            self.assertIn("# source_type: \"user_measured\"", export_csv(run).decode("utf-8-sig"))
            with self.assertRaises(ValueError):
                repository.save_comparison(
                    {"project_id": "default", "dataset_ids": [run["id"]], "x_axis": "time_s", "variable": "voltage_v"})


class ImportHttpTests(unittest.TestCase):
    setUp = test_simulation.HttpTests.setUp
    tearDown = test_simulation.HttpTests.tearDown
    request = test_simulation.HttpTests.request

    def test_import_preview_save_original_and_projects(self):
        with self.request("/api/projects", {"name": "実測"}) as response:
            project = json.load(response)
        data = request_data(project_id=project["id"])
        with self.request("/api/import/inspect", data) as response:
            self.assertEqual(json.load(response)["row_count"], 2)
        with self.request("/api/import/preview", data) as response:
            run = json.load(response)
        with self.request("/api/save", {"id": run["id"]}):
            pass
        with self.request(f'/api/results/{run["id"]}/original') as response:
            self.assertEqual(response.read(), data["text"].encode())
        with self.request(f'/api/runs?project_id={project["id"]}') as response:
            self.assertEqual(len(json.load(response)), 1)
        with self.request("/api/runs") as response:
            self.assertEqual(json.load(response), [])
        with self.request("/api/import/demo", {"seed": 42}) as response:
            self.assertEqual(json.load(response)["source_type"], "synthetic_demo")


if __name__ == "__main__":
    unittest.main()
