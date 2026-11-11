"""OJT2 Stage 4: conservative metadata-based requirement discovery.

Only reads a catalog snapshot; never executes SQL from SQL definitions or documents.
Names and scores are SEARCH EVIDENCE, not proof of business semantics or runtime lineage.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import io
import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
import uuid
from pathlib import Path
from ojt2_analysis_runtime import runtime_for_context
from typing import Any

VERSION = "0.3.0-stage41"
RULE_VERSION = "curated-semantic-demo-v1"
APPDATA = Path(os.environ.get('OJT2_APP_DATA_DIR', str(Path.home() / "OJT2_Discovery_Data"))).expanduser()
HISTORY_DB = APPDATA / "discovery_app.sqlite"

GDL_FIELDS = [
    "Directorate", "Type Material", "Sonumb", "Sitename", "Regional",
    "PO Number", "Supplier", "GDL No", "Qty GDL", "GDL Date", "WH Origin",
    "Mitra Service", "Month", "Year", "Amount Order", "Qty Order",
    "Price/Unit", "Amount GDL", "Status",
]
DEMO_GDL = {
    "purpose": "Monitoring closing alokasi material GDL List Outbound",
    "source_hint": "GDL_List_Outbond",
    "filtering": "All Data",
    "required_fields": GDL_FIELDS,
    "origin": "Demo synthetic GDL example",
}

# Curated aliases for SYNTHETIC demo only; no silent semantic-equivalence claim for production.
DEMO_FIELD_ALIASES = {"priceunit": "priceperunit"}
STOP = {"data", "the", "dan", "untuk", "dari", "yang", "hasil", "report", "laporan", "all", "list", "berdasarkan", "monitoring", "closing"}


def norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def tokens(text: Any) -> list[str]:
    return [x for x in re.findall(r"[a-z0-9]+", str(text or "").casefold()) if len(x) > 2 and x not in STOP]


def unique_fields(values: Any) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[,;\r\n]+", values)
    seen, result = set(), []
    for v in values or []:
        v = str(v).strip()
        k = norm(v)
        if not k or k in seen:
            continue
        seen.add(k)
        result.append(v)
    return result


def parse_excel_requirement(file_bytes: bytes, filename: str = "uploaded.xlsx", sheet: str | None = None) -> dict:
    """Best-effort parser, not a claim of compatibility with every TBIGData template.

    Supports label/value vertical templates, a column list below 'Columns Required',
    and a row-wise table with Purpose, Data Source, Filtering, Columns Required headers.
    Ambiguity is explicitly delegated to PIC review/edit.
    """
    import pandas as pd
    name = filename.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str, keep_default_na=False, nrows=400)
        sheet_used = "CSV"
    elif name.endswith((".xlsx", ".xlsm")):
        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
        sheet_used = sheet or xl.sheet_names[0]
        if sheet_used not in xl.sheet_names:
            raise ValueError(f"Sheet tidak tersedia: {sheet_used}")
        df = pd.read_excel(xl, sheet_name=sheet_used, header=None, dtype=str, keep_default_na=False, nrows=400)
    else:
        raise ValueError("Format belum didukung. Unggah .xlsx, .xlsm, atau .csv")
    rows = [[str(v).strip() for v in row] for row in df.fillna("").values.tolist()]
    info = {"purpose": "", "source_hint": "", "filtering": "", "required_fields": [],
            "origin": f"Upload: {filename} / {sheet_used}", "parse_notes": []}
    labels = {
        "purpose": ("purpose", "tujuan", "kegunaan", "data purpose"),
        "source_hint": ("data source", "source hint", "sumber data", "source", "aplikasi sumber"),
        "filtering": ("filtering", "filter", "kriteria filter", "periode"),
        "required_fields": ("columns required", "required column", "required fields", "kolom yang dibutuhkan", "kolom kebutuhan", "column required"),
    }
    field_section = False
    fields = []
    for row in rows:
        nonempty = [(j, x) for j, x in enumerate(row) if x and x.casefold() not in {"nan", "none"}]
        if not nonempty:
            if field_section:
                field_section = False
            continue
        lead_j, lead = nonempty[0]
        key = next((k for k, names in labels.items() if norm(lead) in {norm(q) for q in names}), None)
        if key:
            if key == "required_fields":
                field_section = True
                fields.extend(x for j, x in nonempty[1:] if x)
            else:
                value = next((x for j, x in nonempty if j > lead_j), "")
                if value and not info[key]:
                    info[key] = value
                field_section = False
            continue
        if field_section:
            # Numbered required-fields rows (e.g. "1", "GDL No")
            for _, candidate in nonempty:
                if candidate.isdigit() or norm(candidate) in {"no", "number", "column", "description"}:
                    continue
                fields.append(candidate)
    # Try table-format (horizontal) headers when no labelled fields were found.
    if not fields:
        for r, row in enumerate(rows[:-1]):
            colnames = {next((k for k, names in labels.items() if norm(x) in {norm(q) for q in names}), ""): j
                        for j, x in enumerate(row) if x}
            if "required_fields" in colnames:
                next_row = rows[r + 1]
                for k in ("purpose", "source_hint", "filtering"):
                    if k in colnames and colnames[k] < len(next_row):
                        info[k] = info[k] or next_row[colnames[k]].strip()
                fcol = colnames["required_fields"]
                fields += [next_row[fcol]] if fcol < len(next_row) else []
                for more in rows[r + 2:]:
                    if fcol < len(more) and more[fcol].strip():
                        fields.append(more[fcol])
                break
    info["required_fields"] = unique_fields(fields)
    if not info["purpose"]: info["parse_notes"].append("Purpose tidak terdeteksi otomatis; isi manual.")
    if not info["source_hint"]: info["parse_notes"].append("Data Source hint tidak terdeteksi otomatis; isi manual jika diketahui.")
    if not info["required_fields"]: info["parse_notes"].append("Columns Required belum terdeteksi; cek sheet/struktur Excel dan isi manual.")
    info["sheet"] = sheet_used
    info["preview_rows"] = rows[:15]
    return info


def _field_matches(columns: list[dict], requested: str) -> dict:
    requested_n = norm(requested)
    for col in columns:
        if norm(col["column_name"]) == requested_n:
            return {"requested": requested, "actual": col["column_name"], "status": "NAME_MATCH", "evidence": "Exact name after punctuation/space normalization"}
    alias = DEMO_FIELD_ALIASES.get(requested_n)
    if alias:
        for col in columns:
            if norm(col["column_name"]) == alias:
                return {"requested": requested, "actual": col["column_name"], "status": "DEMO_ALIAS_REVIEW", "evidence": "Curated demo alias; PIC must verify meaning"}
    return {"requested": requested, "actual": None, "status": "MISSING", "evidence": "Not found in output schema"}


def _context_score(obj: dict, requirement: dict) -> tuple[float, float]:
    name = norm(obj["object_name"])
    hint = norm(requirement.get("source_hint", ""))
    hint_rel = 0.0
    if hint:
        a = name
        for p in ("vw", "rpt", "usp", "sp", "load", "report"):
            if a.startswith(p): a = a[len(p):]
        hint_rel = max(SequenceMatcher(None, name, hint).ratio(), SequenceMatcher(None, a, hint).ratio())
        if hint in name or a in hint: hint_rel = max(hint_rel, 0.95)
    keywords = tokens(requirement.get("purpose", "") + " " + requirement.get("source_hint", ""))
    hay = (obj["object_name"] + " " + obj["database_name"]).lower()
    purpose_rel = (sum(1 for t in keywords if t in hay) / len(keywords)) if keywords else 0.0
    return min(hint_rel, 1.0), min(purpose_rel, 1.0)


def discover(data: dict, index: dict, requirement: dict, allowed_databases: list[str] | None = None,
             limit: int = 20) -> list[dict]:
    """Rank output-like tables/views and SP context; score = heuristic, NOT confidence.

    With required columns, field evidence is primary (70%), then hint (20%) and
    business context (10%). No availability penalty for non-DGA sources.
    """
    reqfields = unique_fields(requirement.get("required_fields", []))
    allow = set(allowed_databases or [o["database_name"] for o in data["objects"]])
    results = []
    for obj in data["objects"]:
        if obj["database_name"] not in allow: continue
        kind = str(obj["object_type"]).strip()
        if kind not in {"U", "V", "P"}: continue
        key = obj["object_key"]
        cols = index["columns"].get(key, [])
        field_map = [_field_matches(cols, f) for f in reqfields]
        matches = sum(x["status"] != "MISSING" for x in field_map)
        coverage = (matches / len(reqfields)) if reqfields else None
        hint, context = _context_score(obj, requirement)
        if reqfields:
            score = (70.0 * coverage) + 20.0 * hint + 10.0 * context
        else:
            # Context/hint-only router when Document Requirement has no fields.
            score = 75.0 * hint + 25.0 * context
        # Do not infer stored procedure output columns from SQL definition.
        if kind == "P":
            score = min(score, 32.0)
        score = round(min(max(score, 0.0), 100.0), 1)
        if score < 1.0: continue
        results.append({"object_key": key, "object": obj, "score": score,
                        "field_map": field_map, "matched": matches,
                        "total": len(reqfields), "coverage": coverage,
                        "hint_score": round(hint*100, 1), "context_score": round(context*100, 1),
                        "type": {"U":"Table", "V":"View", "P":"Stored Procedure"}[kind],
                        "confidence_label": "HEURISTIC_DEMO", "availability": obj["logical_server"],
                        "warnings": (["SP output schema not indexed; find its WRITES_TO targets"] if kind == "P" else [])})
    return sorted(results, key=lambda x: (-x["score"], -(x["matched"]),
                                          0 if x["type"]=="View" else 1, x["object"]["object_name"]))[:limit]


def find_supporting(data: dict, index: dict, candidate: dict, requirement: dict,
                    allowed_databases: list[str] | None = None, limit_per_field: int = 12) -> list[dict]:
    """Candidates only. Shared names are POTENTIAL keys, never validated joins."""
    allowed = set(allowed_databases or [o["database_name"] for o in data["objects"]])
    main = candidate["object"]
    main_key = main["object_key"]
    maincols = {norm(c["column_name"]): c["column_name"] for c in index["columns"].get(main_key, [])}
    out = []
    for missing in [x["requested"] for x in candidate["field_map"] if x["status"] == "MISSING"]:
        found = []
        for obj in data["objects"]:
            if obj["database_name"] not in allowed or obj["object_key"] == main_key: continue
            if str(obj["object_type"]).strip() not in {"V","U"}: continue
            mapping = _field_matches(index["columns"].get(obj["object_key"], []), missing)
            if mapping["status"] == "MISSING": continue
            supporting_cols = {norm(c["column_name"]):c["column_name"] for c in index["columns"].get(obj["object_key"], [])}
            common = [maincols[k] for k in maincols.keys() & supporting_cols.keys()
                      if k.endswith(("id", "no", "number", "code"))]
            # Heuristic list of likely entity identifiers; no unique/foreign key validation.
            common.sort(key=lambda x: (0 if norm(x)=="gdldetailid" else 1, x))
            same_family = any(t in norm(obj["object_name"]) for t in tokens(requirement.get("source_hint", "")))
            found.append({"missing_field":missing,"source":obj,"actual_field":mapping["actual"],
                          "match_status":mapping["status"],"shared_id_candidates":common,
                          "needs_join_validation":True,
                          "same_logical_server": obj["logical_server"] == main["logical_server"],
                          "priority": (2 if common else 0) + (1 if same_family else 0) +
                                      (1 if str(obj["object_type"]).strip()=="U" else 0)})
        out.extend(sorted(found,key=lambda x:(-x["priority"],x["source"]["database_name"],x["source"]["object_name"]))[:limit_per_field])
    return out


def evidence_summary(candidate: dict, support: list[dict]) -> dict:
    """Potential coverage is a *proposal*, not verified coverage."""
    possible = {p["missing_field"] for p in support}
    missing = {r["requested"] for r in candidate["field_map"] if r["status"]=="MISSING"}
    direct = candidate["matched"]
    return {"direct": direct, "total":candidate["total"],
            "potential":direct + len(possible & missing),
            "unresolved":[f for f in missing if f not in possible],
            "status":"NEEDS_JOIN_AND_BUSINESS_VALIDATION" if possible else "PARTIAL_OR_UNRESOLVED"}


def _open_history_conn(path: Path = HISTORY_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cn = sqlite3.connect(path, timeout=15)
    try:
        cn.row_factory = sqlite3.Row
        cn.execute("PRAGMA foreign_keys=ON")
        cn.executescript("""
            CREATE TABLE IF NOT EXISTS mapping_history (
              id TEXT PRIMARY KEY,
              saved_at TEXT NOT NULL,
              actor TEXT NOT NULL,
              status TEXT NOT NULL,
              engine_version TEXT NOT NULL,
              rule_version TEXT NOT NULL,
              catalog_run_id INTEGER NOT NULL,
              source_scope TEXT NOT NULL,
              requirement_json TEXT NOT NULL,
              candidate_key TEXT NOT NULL,
              candidate_fqn TEXT NOT NULL,
              score_json TEXT NOT NULL,
              selected_support_json TEXT NOT NULL,
              notes TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
              setting_key TEXT PRIMARY KEY,
              setting_value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_time ON mapping_history(saved_at DESC);
        """)
        return cn
    except BaseException:
        cn.close()
        raise


@contextmanager
def _history_conn(path: Path = HISTORY_DB):
    """Commit/rollback before closing; close on both normal and exceptional exit."""
    with closing(_open_history_conn(path)) as cn:
        with cn:
            yield cn


def save_review(requirement: dict, candidate: dict, selected_support: list[dict],
                actor: str, notes: str, source_scope: list[str], catalog_run_id: int,
                path: Path = HISTORY_DB) -> str:
    if not actor.strip():
        raise ValueError("Isi identitas/reviewer sebelum menyimpan.")
    if not notes.strip():
        raise ValueError("Isi alasan/hasil review. Jangan menyatakan JOIN validated tanpa bukti.")
    item_id = str(uuid.uuid4())
    # Approved source candidate != approved complete field mapping.
    status = "REVIEWED_PARTIAL" if candidate["total"] != candidate["matched"] else "REVIEWED_CANDIDATE"
    summary = {"score":candidate["score"],"matched":candidate["matched"],
               "total":candidate["total"],"field_map":candidate["field_map"],
               "score_type":candidate["confidence_label"]}
    runtime = runtime_for_context(candidate.get('analysis_runtime'), requirement, source_scope, catalog_run_id)
    if runtime and runtime['status'] == 'completed':
        summary['analysis_runtime'] = runtime
    with _history_conn(path) as cn:
        cn.execute("""INSERT INTO mapping_history
              (id,saved_at,actor,status,engine_version,rule_version,catalog_run_id,
               source_scope,requirement_json,candidate_key,candidate_fqn,score_json,
               selected_support_json,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (item_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), actor.strip(), status,
                candidate.get('engine_version',VERSION), candidate.get('rule_version',RULE_VERSION), catalog_run_id, json.dumps(source_scope),
                json.dumps(requirement,ensure_ascii=False), candidate["object_key"],
                ".".join([candidate["object"]["database_name"],candidate["object"]["schema_name"],candidate["object"]["object_name"]]),
                json.dumps(summary,ensure_ascii=False), json.dumps(selected_support,ensure_ascii=False), notes.strip()))
    return item_id


def list_reviews(path: Path = HISTORY_DB) -> list[dict]:
    with _history_conn(path) as cn:
        return [dict(x) for x in cn.execute("SELECT * FROM mapping_history ORDER BY saved_at DESC")]


def get_setting(key: str, fallback: Any = None, path: Path = HISTORY_DB) -> Any:
    with _history_conn(path) as cn:
        r = cn.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else fallback


def set_setting(key: str, value: Any, path: Path = HISTORY_DB) -> None:
    with _history_conn(path) as cn:
        cn.execute("INSERT INTO app_settings VALUES (?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at",
                   (key,json.dumps(value),datetime.now(timezone.utc).isoformat(timespec="seconds")))
