"""Smart Data Source Discovery — Stage 3: real metadata/lineage explorer.

Reads the persistent SQLite catalog created by:
    07_build_metadata_catalog.py
    09_build_lineage_edges.py

No SQL Server connection is made. No code here executes source SQL or SPs.
This is a local DEMO reader, not a production authorization / access layer.

Start:
    python -m streamlit run 11_metadata_explorer_streamlit.py
"""
from __future__ import annotations

import os
import sqlite3
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from ojt2_object_definition import definition_label, render_object_definition

DEFAULT_CATALOG = Path.home() / "OJT2_Discovery_Data" / "metadata_catalog.sqlite"
ALLOWED_RELATIONS = {"READS_FROM", "GENERATED_BY", "WRITES_TO"}
DISPLAY_TYPE = {
    "U": "Table", "V": "View", "P": "Stored Procedure",
    "FN": "Scalar Function", "IF": "Inline Function", "TF": "Table Function",
}


def catalog_path() -> Path:
    return Path(os.getenv("OJT2_CATALOG_PATH", str(DEFAULT_CATALOG))).expanduser().resolve()


def read_catalog(path: Path) -> dict[str, Any]:
    """Read snapshot via SQLite URI mode=ro; never creates or modifies the database."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite metadata catalog tidak ditemukan: {path}")
    # pathlib.as_uri handles spaces and Windows drive letters correctly.
    uri = path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as cn:
        cn.row_factory = sqlite3.Row
        required = {"catalog_objects", "catalog_columns", "catalog_runs",
                    "lineage_edges", "lineage_runs"}
        existing = {r[0] for r in cn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(required - existing)
        if missing:
            raise RuntimeError(f"Table katalog belum tersedia: {missing}. Jalankan 07 lalu 09.")
        objects = [dict(r) for r in cn.execute("SELECT * FROM catalog_objects")]
        columns = [dict(r) for r in cn.execute(
            "SELECT * FROM catalog_columns ORDER BY object_key, column_id")]
        edges = [dict(r) for r in cn.execute("SELECT * FROM lineage_edges")]
        metadata_run = cn.execute(
            "SELECT * FROM catalog_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        lineage_run = cn.execute(
            "SELECT * FROM lineage_runs ORDER BY id DESC LIMIT 1").fetchone()
        raw_refs = cn.execute("SELECT COUNT(*) FROM catalog_dependencies").fetchone()[0]
    if not metadata_run or not lineage_run:
        raise RuntimeError("Belum ada catatan extraction/lineage run. Jalankan 07 lalu 09.")
    if not objects or any(not str(o["database_name"]).startswith("DEMO_") for o in objects):
        raise RuntimeError("Safety stop: Explorer Stage 3 hanya mendukung DEMO_ catalog.")
    return {
        "objects": objects, "columns": columns, "edges": edges,
        "metadata_run": dict(metadata_run), "lineage_run": dict(lineage_run),
        "raw_ref_count": raw_refs,
    }


def fqn(obj: dict[str, Any]) -> str:
    return f"{obj['database_name']}.{obj['schema_name']}.{obj['object_name']}"


def typed_label(obj: dict[str, Any]) -> str:
    return f"{fqn(obj)}  ·  {DISPLAY_TYPE.get(str(obj['object_type']).strip(), obj['object_type_desc'])}"


def make_index(data: dict[str, Any]) -> dict[str, Any]:
    objects = {o["object_key"]: o for o in data["objects"]}
    columns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in data["columns"]:
        columns[c["object_key"]].append(c)
    forward: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reverse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in data["edges"]:
        forward[e["source_key"]].append(e)
        if e["target_key"]:
            reverse[e["target_key"]].append(e)
    return {"objects": objects, "columns": columns,
            "forward": forward, "reverse": reverse}


def search_objects(data: dict[str, Any], index: dict[str, Any],
                   term: str = "", logical_server: str = "All",
                   database: str = "All", object_type: str = "All",
                   search_columns: bool = True) -> list[dict[str, Any]]:
    raw_term = term.strip()
    term = raw_term.casefold()
    matches = []
    for obj in data["objects"]:
        if logical_server != "All" and obj["logical_server"] != logical_server:
            continue
        if database != "All" and obj["database_name"] != database:
            continue
        if object_type != "All" and str(obj["object_type"]).strip() != object_type:
            continue
        searchable = " ".join([obj["database_name"], obj["schema_name"],
                               obj["object_name"], obj["object_type_desc"]]).casefold()
        if search_columns:
            searchable += " " + " ".join(
                c["column_name"] for c in index["columns"].get(obj["object_key"], [])
            ).casefold()
        if not term or term in searchable:
            matches.append(obj)
    if not matches and term and search_columns:
        # Alias-aware fallback, only when a literal object/column lookup found nothing.
        # This is still a search HYPOTHESIS, not verified metadata equivalence.
        proposed = field_candidates(data, index, raw_term,
                   logical_server=logical_server, database=database, object_type=object_type,
                   limit=100)
        # Avoid retrieving unrelated objects merely because embedding cosine
        # is moderately high. Semantic-only object search needs very strong
        # evidence; Field Finder remains available for broader review.
        keys = {x['Object'] for x in proposed
                if (x['Status']!='SEMANTIC_REVIEW' and x['Ranking Signal'] >= .76)
                or (x['Status']=='SEMANTIC_REVIEW' and x['Ranking Signal'] >= .86)}
        matches = [o for o in data['objects'] if fqn(o) in keys and
                   (logical_server=='All' or o['logical_server']==logical_server) and
                   (database=='All' or o['database_name']==database) and
                   (object_type=='All' or str(o['object_type']).strip()==object_type)]
    return sorted(matches, key=lambda o: (o["logical_server"], o["database_name"],
                                           o["object_name"].casefold()))


def field_presence(index: dict[str, Any], object_key: str, field_name: str) -> bool:
    return any(c["column_name"].casefold() == field_name.strip().casefold()
               for c in index["columns"].get(object_key, []))


def infer_domain(obj: dict[str, Any]) -> str | None:
    """Best-effort domain hint from object name for vocabulary/feedback scope.

    Object names are evidence only; this is not business-domain validation.
    """
    from ojt2_adaptive_core import DOMAIN_RULES
    candidate = str(obj.get('object_name', '')).casefold()
    scores = [(sum(tok.casefold() in candidate for tok in cfg.get('object_tokens', ())), domain)
              for domain,cfg in DOMAIN_RULES.items()]
    scores = sorted((score,domain) for score,domain in scores if score)
    if not scores:
        return None
    best = scores[-1][0]
    winners = [domain for score,domain in scores if score==best]
    return winners[0] if len(winners)==1 else None


def field_candidates(data: dict[str, Any], index: dict[str, Any], query: str, *,
                     logical_server: str = 'All', database: str = 'All',
                     object_type: str = 'All', limit: int = 100) -> list[dict[str, Any]]:
    """Metadata field finder shares the SAME matcher as Requirement Discovery.

    Reads only the SQLite catalog and persistent vocabulary/feedback registry.
    A proposal is never counted as verified mapping, join, or field coverage.
    """
    from ojt2_discovery_core import norm
    from ojt2_field_matching import get_alias_decisions, get_term_rules
    from ojt2_adaptive_core import _field_evidence
    requested = query.strip()
    if not requested:
        return []
    from ojt2_shared_learning import load_shared_feedback
    shared_feedback = load_shared_feedback()
    terms_by_domain: dict[str | None,dict] = {}
    decisions_by_domain: dict[str | None,dict] = {}
    rows=[]
    for obj in data['objects']:
        if logical_server != 'All' and obj['logical_server']!=logical_server:
            continue
        if database != 'All' and obj['database_name']!=database:
            continue
        if object_type != 'All' and str(obj['object_type']).strip()!=object_type:
            continue
        obj_key = obj['object_key']
        cols = index['columns'].get(obj_key,[])
        if not cols:
            continue
        domain = infer_domain(obj)
        if domain not in terms_by_domain:
            terms_by_domain[domain] = get_term_rules(domain)
            decisions_by_domain[domain] = get_alias_decisions(domain)
        terms = terms_by_domain[domain]
        decisions = decisions_by_domain[domain]
        resolution = _field_evidence(cols, requested, domain, obj_key,
            decisions, terms, object_name=obj['object_name'], shared_feedback=shared_feedback)
        ambiguous=resolution['status'] in {'AMBIGUOUS_MATCH_REVIEW',
            'MULTIPLE_CONTEXT_OPTIONS_REVIEW','MULTIPLE_ATTRIBUTE_OPTIONS_REVIEW'}
        proposals=resolution.get('suggestions',[])
        if resolution.get('actual'):
            proposals=[next((p for p in proposals if p['actual']==resolution['actual']),
                {'actual':resolution['actual'],'status':resolution['status'],
                 'rank_score':1.0 if resolution['status']=='NAME_MATCH' else 0.0,
                 'evidence':resolution['evidence']})]
        elif ambiguous:
            proposals=proposals[:5]
        else:
            proposals=proposals[:1]
        by_col = {c['column_name']: c for c in cols}
        for prop in proposals:
            col = by_col.get(prop['actual'])
            if not col:
                continue
            rows.append({
                'Logical Server': obj['logical_server'], 'Database': obj['database_name'],
                'Object': fqn(obj),
                'Type': DISPLAY_TYPE.get(str(obj['object_type']).strip(), obj['object_type_desc']),
                'Column': col['column_name'], 'SQL Type': col['sql_type'],
                'Status': resolution['status'] if ambiguous else prop['status'], 'Ranking Signal': prop['rank_score'],
                'Evidence': prop['evidence'], 'Domain': domain or 'Unspecified',
                'ObjectKey': obj_key,
            })
    rows.sort(key=lambda r: (-r['Ranking Signal'],r['Object'],r['Column']))
    return rows[:max(1,limit)]


def traverse(index: dict[str, Any], start_key: str,
             direction: str = "Upstream", depth: int = 3,
             max_nodes: int = 60) -> tuple[list[dict[str, Any]], set[str]]:
    """Upstream: view->table->generator SP->inputs.

    Downstream: table->consuming view/SP->SP output; SP->output.
    Returned steps use the *visual* from->to direction; they are read-only edges.
    """
    if start_key not in index["objects"]:
        return [], set()
    seen = {start_key}
    q = deque([(start_key, 0)])
    rows = []
    while q and len(seen) <= max_nodes:
        node, level = q.popleft()
        if level >= depth:
            continue
        next_edges = []
        if direction == "Upstream":
            for e in index["forward"].get(node, []):
                if e["relation_type"] in ("READS_FROM", "GENERATED_BY"):
                    next_edges.append((node, e.get("target_key"), e))
        else:
            for e in index["reverse"].get(node, []):
                if e["relation_type"] == "READS_FROM":
                    next_edges.append((node, e["source_key"], e))
            for e in index["forward"].get(node, []):
                if e["relation_type"] == "WRITES_TO":
                    next_edges.append((node, e.get("target_key"), e))
        for source, target, e in next_edges:
            if target is None or target not in index["objects"] or target == source:
                continue
            rows.append({"from": source, "to": target, "relation": e["relation_type"],
                         "status": e["evidence_status"],
                         "operations": e["operations"], "depth": level + 1})
            if target not in seen and len(seen) < max_nodes:
                seen.add(target)
                q.append((target, level + 1))
    return rows, seen


def dot_graph(index: dict[str, Any], steps: list[dict[str, Any]], start_key: str) -> str:
    """DOT diagram. Node IDs are generated numbers, never interpreted as SQL."""
    keys = {start_key}
    for s in steps:
        keys.update((s["from"], s["to"]))
    order = [start_key] + sorted(keys - {start_key})
    names = {key: f"n{i}" for i, key in enumerate(order)}
    lines = ['digraph G {', 'rankdir=LR;', 'graph [bgcolor="transparent", pad="0.2"];',
             'node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10];',
             'edge [fontname="Arial", fontsize=9, arrowsize=0.65];']
    for key in order:
        o = index["objects"].get(key, {})
        label = (str(o.get("object_name", "Unknown")) + "\\n" +
                 str(o.get("database_name", "")))
        label = label.replace('"', "'").replace("\\", "\\\\")
        fill = "#dbeafe" if key == start_key else "#f1f5f9"
        lines.append(f'{names[key]} [label="{label}", fillcolor="{fill}", color="#94a3b8"];')
    seen_edges = set()
    for s in steps:
        tup = (s["from"], s["to"], s["relation"])
        if tup in seen_edges:
            continue
        seen_edges.add(tup)
        lbl = s["relation"].replace('"', "")
        lines.append(f'{names[s["from"]]} -> {names[s["to"]]} [label="{lbl}"];')
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Metadata Explorer | OJT 2", page_icon="🧭",
                       layout="wide", initial_sidebar_state="expanded")
    st.title("Smart Data Source Discovery")
    st.caption("Stage 3 · Metadata Explorer — membaca katalog SQLite lokal, bukan database SQL Server secara live")

    path = catalog_path()
    if not path.exists():
        st.error(f"Katalog belum ditemukan: `{path}`")
        st.code(r".\.venv\Scripts\python.exe .\07_build_metadata_catalog.py\n"
                r".\.venv\Scripts\python.exe .\09_build_lineage_edges.py", language="powershell")
        st.stop()

    @st.cache_data(show_spinner="Loading SQLite metadata catalog...", ttl=120)
    def cached_catalog(path_str: str, mtime_ns: int) -> dict[str, Any]:
        return read_catalog(Path(path_str))

    try:
        data = cached_catalog(str(path), path.stat().st_mtime_ns)
    except Exception as exc:
        st.error(f"Gagal membaca katalog: {exc}")
        st.stop()

    index = make_index(data)
    run = data["metadata_run"]
    lineage_run = data["lineage_run"]
    fresh = int(lineage_run["source_run_id"]) == int(run["run_id"])
    if not fresh:
        st.error("Lineage sudah STALE setelah refresh metadata. Jalankan script 09 kembali sebelum membaca hasil lineage.")
    else:
        st.info("Static lineage: *inferred* dari SQL definition + dependency. Bukan bukti SP pernah dieksekusi.")

    a, b, c, d = st.columns(4)
    a.metric("Databases", len({o["database_name"] for o in data["objects"]}))
    b.metric("Objects", len(data["objects"]))
    c.metric("Columns", len(data["columns"]))
    d.metric("Lineage edges", len(data["edges"]))

    if "search_text" not in st.session_state:
        st.session_state.search_text = "STIP"
    st.sidebar.header("Search Scope")
    demo1, demo2 = st.sidebar.columns(2)
    if demo1.button("STIP demo", use_container_width=True):
        st.session_state.search_text = "STIP"
    if demo2.button("GDL demo", use_container_width=True):
        st.session_state.search_text = "GDL"
    st.sidebar.text_input("Object / column / database keyword", key="search_text")
    logical_values = ["All"] + sorted({o["logical_server"] for o in data["objects"]})
    logical_server = st.sidebar.selectbox("Logical Server", logical_values)
    databases = sorted({o["database_name"] for o in data["objects"]
                        if logical_server == "All" or o["logical_server"] == logical_server})
    database = st.sidebar.selectbox("Database", ["All"] + databases)
    objtypes = sorted({str(o["object_type"]).strip() for o in data["objects"]})
    object_type = st.sidebar.selectbox("Object Type", ["All"] + objtypes,
                                       format_func=lambda x: DISPLAY_TYPE.get(x, x) if x != "All" else x)
    incl_columns = st.sidebar.checkbox("Include column names in search", value=True)
    st.sidebar.divider()
    st.sidebar.caption(f"Local snapshot: {run['indexed_at']} UTC")
    st.sidebar.caption("Physical SQL Server: one local SQLEXPRESS instance. DGA/IT/HR labels are simulations.")

    matches = search_objects(data, index, st.session_state.search_text,
                             logical_server, database, object_type, incl_columns)
    st.subheader("Search Results")
    st.caption(f"{len(matches)} matching objects. All searches run against the SQLite snapshot.")
    if not matches:
        st.warning("Tidak ada objek yang cocok. Reset keyword/filter di sidebar.")
        st.stop()
    preview = [{"Logical Server": o["logical_server"], "Database": o["database_name"],
                "Schema": o["schema_name"], "Object": o["object_name"],
                "Type": DISPLAY_TYPE.get(str(o["object_type"]).strip(), o["object_type_desc"]),
                "Columns": len(index["columns"].get(o["object_key"], [])),
                "Definition": definition_label(o, index["columns"].get(o["object_key"], []))} for o in matches]
    st.dataframe(preview, hide_index=True, use_container_width=True, height=min(320, 52 + len(preview) * 35))
    key_choices = [o["object_key"] for o in matches]
    selected_key = st.selectbox("Inspect object", key_choices,
                                format_func=lambda k: typed_label(index["objects"][k]))
    obj = index["objects"][selected_key]
    st.markdown(f"**Selected:** `{fqn(obj)}` · **Logical server:** `{obj['logical_server']}` · **Type:** `{DISPLAY_TYPE.get(str(obj['object_type']).strip(), obj['object_type_desc'])}`")
    tab_fields, tab_definition, tab_lineage, tab_gap, tab_health = st.tabs([
        "Columns", "SQL Definition", "Recursive Lineage", "Field Finder / Gap", "Catalog Health"
    ])

    with tab_fields:
        rows = index["columns"].get(selected_key, [])
        st.caption(f"{len(rows)} SQL columns. For SPs, output result-set columns are not automatically captured by sys.columns.")
        if rows:
            st.dataframe([{"Order": r["column_id"], "Column": r["column_name"],
                           "SQL Type": r["sql_type"], "Nullable": bool(r["is_nullable"]),
                           "Identity": bool(r["is_identity"])} for r in rows],
                         hide_index=True, use_container_width=True)
        else:
            st.info("Objek ini tidak memiliki baris di catalog_columns (umum untuk Stored Procedure).")

    with tab_definition:
        render_object_definition(obj, index["columns"].get(selected_key, []))

    with tab_lineage:
        if not fresh:
            st.warning("Lineage tidak boleh digunakan sampai diregenerasi dengan script 09.")
        else:
            direction = st.radio("Traversal direction", ["Upstream", "Downstream"], horizontal=True)
            max_depth = st.slider("Maximum hops", 1, 6, 3)
            steps, nodes = traverse(index, selected_key, direction, max_depth)
            st.caption(f"Connected objects: {len(nodes)} · Traced links: {len(steps)} · Maximum depth: {max_depth}")
            if steps:
                try:
                    st.graphviz_chart(dot_graph(index, steps, selected_key), use_container_width=True)
                except Exception as exc:
                    st.warning(f"Diagram tidak dapat dirender; daftar lineage tetap tersedia: {exc}")
                summary = []
                for step in steps:
                    summary.append({"Hop": step["depth"], "From": fqn(index["objects"][step["from"]]),
                                    "Relation": step["relation"], "To": fqn(index["objects"][step["to"]]),
                                    "Operation": step["operations"], "Evidence": step["status"]})
                st.dataframe(summary, hide_index=True, use_container_width=True)
                st.warning("GENERATOR SP = static inferred relationship, bukan konfirmasi runtime. JOIN key/cardinality belum tervalidasi di tahap ini.")
            else:
                st.info("Tidak ada lineage ter-resolve untuk arah dan kedalaman yang dipilih.")
            st.caption("`READS_FROM`: query merujuk ke tabel; `GENERATED_BY`: inverse SP writer; `WRITES_TO`: SP target DML.")

    with tab_gap:
        st.caption("Alias-aware candidate search memakai matcher yang sama dengan Discovery Results. Semua hasil non-exact tetap memerlukan review PIC.")
        field_query = st.text_input("Kolom yang dibutuhkan", value="WHOrigin")
        if field_query.strip():
            present = field_presence(index, selected_key, field_query)
            if present:
                st.success(f"Kolom `{field_query}` sudah tersedia langsung pada `{fqn(obj)}`.")
            else:
                st.warning(f"Kolom `{field_query}` tidak ditemukan langsung pada `{fqn(obj)}`.")
            found = field_candidates(data, index, field_query)
            selected_hits=[r for r in found if r['Object']==fqn(obj)]
            if not present and selected_hits:
                st.info('Saran di objek ini: ' + ', '.join(
                    f"{r['Column']} ({r['Status']})" for r in selected_hits[:5])
                    + '. Verifikasi bisnis tetap diperlukan.')
            st.caption(f"Candidate fields (exact + unverified suggestions): {len(found)}")
            if found:
                st.dataframe(found, hide_index=True, use_container_width=True)
            else:
                st.info("Belum ada kandidat nama/alias yang cukup kuat. Ini bukan bukti kolom secara bisnis tidak ada.")
            st.info("Coverage gabungan 100% tidak boleh disimpulkan dari nama kolom saja. Perlu validasi meaning, join key, cardinality, filter dan availability DGA.")

    with tab_health:
        x1, x2, x3 = st.columns(3)
        x1.metric("Raw metadata refs", data["raw_ref_count"])
        x2.metric("Unresolved edges", sum(e["target_key"] is None for e in data["edges"]))
        x3.metric("Distinct generator SP", len({e["source_key"] for e in data["edges"]
                                                 if e["relation_type"] == "WRITES_TO" and e["target_key"]}))
        st.write("**Metadata snapshot**", run)
        st.write("**Lineage snapshot**", lineage_run)
        st.write("**Edge evidence statuses**", dict(Counter(e["evidence_status"] for e in data["edges"])))
        st.caption("No SQL Server or SQLite data modifications happen in this app. To refresh: run 07, then 09; reload browser page.")

    st.divider()
    st.caption("OJT 2 · Stage 3 functional prototype · This is NOT the final ranking/discovery/approval workflow.")


if __name__ == "__main__":
    main()
