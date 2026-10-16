"""Explicit, lossless curve import. No file paths or remote fetches from input."""
import base64
import binascii
import csv
import hashlib
import io
import math
import random
from datetime import datetime, timezone
from uuid import uuid4

SOURCE_TYPES = {"synthetic_demo", "simulation", "public_measured", "user_measured", "digitized"}
UNITS = {
    "time_s": {"s": (1, 0), "min": (60, 0), "h": (3600, 0)},
    "voltage_v": {"V": (1, 0), "mV": (.001, 0)},
    "current_a": {"A": (1, 0), "mA": (.001, 0)},
    "capacity_ah": {"Ah": (1, 0), "mAh": (.001, 0)},
    "soc": {"1": (1, 0), "%": (.01, 0)},
    "temperature_c": {"degC": (1, 0), "K": (1, -273.15)},
}
FIELDS = tuple(UNITS)
MAX_BYTES = 2 * 1024 * 1024
MAX_POINTS = 20000


def text_field(data, key, default="", limit=500):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} は{limit}文字以内の文字列で指定してください。")
    return value.strip()


def decode_original(data):
    if not isinstance(data, dict):
        raise ValueError("取込条件はオブジェクトで指定してください。")
    if "content_base64" in data:
        encoded = data["content_base64"]
        if not isinstance(encoded, str) or len(encoded) > MAX_BYTES * 4 // 3 + 8:
            raise ValueError("原本は2 MiB以内です。")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("原本のエンコードを確認してください。") from None
    else:
        content = data.get("text")
        if not isinstance(content, str):
            raise ValueError("CSV/TSVの原本または表テキストが必要です。")
        raw = content.encode("utf-8")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("空でない2 MiB以内の原本を指定してください。")
    encoding = text_field(data, "encoding", "utf-8-sig")
    if encoding not in {"utf-8-sig", "cp932"}:
        raise ValueError("文字コードはUTF-8またはCP932を指定してください。")
    try:
        content = raw.decode(encoding)
    except UnicodeError:
        raise ValueError("文字コードが一致しません。UTF-8／CP932を確認してください。") from None
    if "\x00" in content:
        raise ValueError("テキスト形式のCSV/TSVを指定してください。")
    return raw, content, encoding


def inspect_table(data):
    raw, content, encoding = decode_original(data)
    delimiter = data.get("delimiter", "auto")
    header_row = data.get("header_row", 1)
    if isinstance(header_row, bool) or not isinstance(header_row, int) or not 1 <= header_row <= 200:
        raise ValueError("ヘッダ行は1〜200の整数で指定してください。")
    if delimiter == "auto":
        delimiter = "\t" if "\t" in content.splitlines()[min(header_row - 1, len(content.splitlines()) - 1)] else ","
    if not isinstance(delimiter, str) or delimiter not in {",", "\t", ";"}:
        raise ValueError("区切りはカンマ・タブ・セミコロンを指定してください。")
    try:
        reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True)
        numbered = [(reader.line_num, row) for row in reader if row]
        numbered = [(line, row) for line, row in numbered if line >= header_row]
        rows = [row for _, row in numbered]
    except csv.Error:
        raise ValueError("引用符や区切りを確認してください。") from None
    if len(rows) < 2 or len(rows) > MAX_POINTS + 1:
        raise ValueError(f"ヘッダと1〜{MAX_POINTS:,}行のデータが必要です。")
    headers = rows[0]
    if len(headers) > 64 or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
        raise ValueError("ヘッダは重複や空欄のない64列以内で指定してください。")
    if not numbered or numbered[0][0] != header_row:
        raise ValueError("ヘッダ行が空欄です。行番号を確認してください。")
    return raw, encoding, delimiter, headers, list(zip([line for line, _ in numbered[1:]], rows[1:]))


def table_preview(data):
    raw, encoding, delimiter, headers, rows = inspect_table(data)
    return {"headers": headers, "sample": [row for _, row in rows[:8]], "row_count": len(rows),
            "encoding": encoding, "delimiter": delimiter, "sha256": hashlib.sha256(raw).hexdigest()}


def import_curve(data):
    raw, encoding, delimiter, headers, rows = inspect_table(data)
    name = text_field(data, "name", "取込カーブ", 100)
    if not name:
        raise ValueError("データ名を入力してください。")
    source_type = data.get("source_type", "user_measured")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES - {"simulation"}:
        raise ValueError("取込データの種別を選択してください。計算結果は計算経由で登録します。")
    source = text_field(data, "source", limit=2000)
    if source_type in {"public_measured", "digitized"} and not source:
        raise ValueError("公開実測・図読取データは出典を入力してください。")
    mapping = data.get("mapping")
    if not isinstance(mapping, dict) or any(k not in FIELDS + ("step", "direction") for k in mapping):
        raise ValueError("列の対応付けを確認してください。")
    selected = {}
    for field, spec in mapping.items():
        if not isinstance(spec, dict) or spec.get("column") not in headers:
            raise ValueError(f"{field} の列を確認してください。")
        if field not in {"step", "direction"} and (
                not isinstance(spec.get("unit"), str) or spec.get("unit") not in UNITS[field]):
            raise ValueError(f"{field} の単位を確認してください。")
        selected[field] = (headers.index(spec["column"]), spec.get("unit"))
    shape = data.get("shape", "time_series")
    if not isinstance(shape, str):
        raise ValueError("データ形態を選択してください。")
    required = {"time_series": {"time_s", "voltage_v", "current_a"},
                "capacity_voltage": {"capacity_ah", "voltage_v"},
                "soc_ocv": {"soc", "voltage_v"}}.get(shape)
    if required is None or not required <= selected.keys():
        raise ValueError("データ形態に必要な列を対応付けてください。")
    mode = data.get("mode", "unknown")
    if not isinstance(mode, str) or mode not in {"discharge", "charge", "rest", "mixed", "unknown"}:
        raise ValueError("充放電区分を確認してください。")
    if shape == "capacity_voltage" and mode not in {"charge", "discharge"}:
        raise ValueError("容量–電圧カーブは充電／放電を明示してください。")
    sign = data.get("current_sign", "discharge_positive")
    if not isinstance(sign, str) or sign not in {"discharge_positive", "charge_positive", "direction_column"}:
        raise ValueError("電流符号を明示してください。")
    direction_values = {key: text_field(data, key, default, 50) for key, default in
                        (("charge_value", "C"), ("discharge_value", "D"), ("rest_value", "R"))}
    direction_codes = {key: {c.strip() for c in value.split("|")} for key, value in direction_values.items()}
    all_codes = [c for codes in direction_codes.values() for c in codes]
    if sign == "direction_column" and (
            "direction" not in selected or "" in all_codes or len(set(all_codes)) != len(all_codes)):
        raise ValueError("区分列と重複しない充電／放電／休止の値を指定してください。")
    decimal = data.get("decimal", ".")
    if not isinstance(decimal, str) or decimal not in {".", ","} or decimal == delimiter:
        raise ValueError("小数点と列区切りは異なる記号を指定してください。")
    points, issues = [], []
    missing = {field: 0 for field in selected if field not in {"step", "direction"}}
    segment = 0
    previous = None
    for line, row in rows:
        if len(row) != len(headers):
            raise ValueError(f"{line}行目：ヘッダと列数が一致しません。")
        point = {field: None for field in FIELDS}
        point.update(source_row=line, segment_id=segment)
        step = row[selected["step"][0]] if "step" in selected else None
        for field, (index, unit) in selected.items():
            if field in {"step", "direction"}:
                continue
            cell = row[index].strip()
            if not cell:
                missing[field] += 1
                continue
            try:
                number = float(cell.replace(",", ".") if decimal == "," else cell)
            except ValueError:
                raise ValueError(f"{line}行目・{headers[index]}：数値でない値があります。") from None
            scale, offset = UNITS[field][unit]
            number = number * scale + offset
            if not math.isfinite(number):
                raise ValueError(f"{line}行目・{headers[index]}：NaN／無限値は取り込めません。")
            if field in {"time_s",
                         "capacity_ah"} and number < 0 or field == "soc" and not 0 <= number <= 1 or field == "temperature_c" and number < -273.15:
                raise ValueError(f"{line}行目・{headers[index]}：値の範囲を確認してください。")
            point[field] = -number if field == "current_a" and sign == "charge_positive" else number
        if sign == "direction_column":
            direction = row[selected["direction"][0]].strip()
            if direction not in all_codes:
                raise ValueError(f"{line}行目：充放電の区分値が未定義です。")
            if point["current_a"] is not None:
                if direction in direction_codes["rest_value"] and point["current_a"] != 0:
                    raise ValueError(f"{line}行目：休止区分の電流が0ではありません。")
                point["current_a"] = abs(point["current_a"]) * (
                    -1 if direction in direction_codes["charge_value"] else 1)
        if previous:
            reset = point["time_s"] is not None and previous["time_s"] is not None and point["time_s"] < previous[
                "time_s"]
            if step != previous["step"] or reset:
                segment += 1
                if reset:
                    issues.append({"row": line, "kind": "time_reset",
                                   "message": "時間逆転／リセットを区間境界として保持。積分・線の接続をしません。"})
            elif point["time_s"] is not None and point["time_s"] == previous["time_s"]:
                issues.append({"row": line, "kind": "duplicate_time", "message": "同時刻の行を保持しました。"})
        point.update(segment_id=segment, step=step)
        points.append(point)
        previous = point
    if not any(all(p.get(f) is not None for f in required) for p in points):
        raise ValueError("必要列がそろったデータ行がありません。")
    for field, count in missing.items():
        if count:
            issues.append({"kind": "missing", "field": field, "count": count,
                           "message": f"{field}：{count}件の欠損をnullのまま保持。補間・ゼロ埋めはしません。"})
    # Throughput is derived only inside a segment with both adjacent measurements.
    if shape == "time_series" and "capacity_ah" not in selected:
        total = 0.0
        for index, point in enumerate(points):
            prev = points[index - 1] if index else None
            complete = point["time_s"] is not None and point["current_a"] is not None
            if not complete:
                point["capacity_ah"] = None
            elif prev is None or prev["segment_id"] != point["segment_id"]:
                total = 0.0
                point["capacity_ah"] = total
            elif prev["time_s"] is None or prev["current_a"] is None or prev["capacity_ah"] is None:
                point["capacity_ah"] = None
            else:
                a, b = abs(prev["current_a"]), abs(point["current_a"])
                # Integrate |I| exactly for linear interpolation through zero.
                mean = (a + b) / 2 if prev["current_a"] * point["current_a"] >= 0 else (a * a + b * b) / (2 * (a + b))
                total += mean * (point["time_s"] - prev["time_s"]) / 3600
                point["capacity_ah"] = total
    return {
        "schema_version": "2.0", "record_type": "dataset", "id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(), "name": name,
        "source_type": source_type, "validation_status": "not_validated",
        "project_id": text_field(data, "project_id", "default", 100),
        "source": source, "license": text_field(data, "license"), "notes": text_field(data, "notes", limit=4000),
        "specimen_id": text_field(data, "specimen_id", limit=100),
        "temperature_position": text_field(data, "temperature_position", "unknown", 100),
        "shape": shape, "mode": mode, "points": points,
        "units": {key: next(iter(options)) for key, options in UNITS.items()},
        "sign_convention": "current_a: discharge positive; capacity_ah: specified axis or segment throughput",
        "transform": {"mapping": mapping, "encoding": encoding, "delimiter": delimiter, "decimal": decimal,
                      "header_row": data.get("header_row", 1),
                      "current_sign": sign, "time_policy": "preserve order; split on reset or step; no interpolation",
                      "direction_values": direction_values if sign == "direction_column" else None,
                      "capacity_policy": "provided" if "capacity_ah" in selected else "segment integral of linearly interpolated |I|; missing intervals not integrated"},
        "quality": {"row_count": len(points), "segment_count": segment + 1, "missing": missing,
                    "issue_count": len(issues), "issues": issues[:200], "issues_truncated": len(issues) > 200},
        "original": {"filename": text_field(data, "filename", "pasted.csv", 200), "encoding": encoding,
                     "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw)},
        "limitations": ["取込・単位変換の確認は物理的な検証ではありません。",
                        "欠損、時刻リセット、区間境界を保持。区間を跨ぐ積分・自動整列はしません。"],
    }, raw


def demo_request(project_id="default", seed=42):
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2 ** 32 - 1:
        raise ValueError("seedは0〜4294967295の整数で指定してください。")
    rng = random.Random(seed)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["time", "voltage", "current", "temperature"])
    for second in range(0, 601, 10):
        writer.writerow([second, f"{4.1 - .0004 * second + rng.gauss(0, .002):.8f}", 1, 25 + second / 1200])
    return {"project_id": project_id, "seed": seed, "name": f"操作デモ seed={seed}",
            "text": stream.getvalue(), "filename": f"synthetic-demo-{seed}.csv", "source_type": "synthetic_demo",
            "source": "PyLiBStudy demo formula v1; voltage=4.1-0.0004*t+Gaussian(0,0.002); I=1 A; T=25+t/1200 degC; t=0..600 s, dt=10 s",
            "notes": f"generator=python.random.Random.gauss; seed={seed}; 合成・未校正。実測ではありません。",
            "mode": "discharge", "shape": "time_series", "mapping": {
            "time_s": {"column": "time", "unit": "s"}, "voltage_v": {"column": "voltage", "unit": "V"},
            "current_a": {"column": "current", "unit": "A"},
            "temperature_c": {"column": "temperature", "unit": "degC"}}}
