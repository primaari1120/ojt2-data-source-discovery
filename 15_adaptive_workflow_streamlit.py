"""Smart Data Source Discovery — guided Streamlit workspace.

Run from a folder containing:
  11_metadata_explorer_streamlit.py  (Stage 3 helper functions)
  ojt2_discovery_core.py            (Stage 4 engine)
  13_discovery_workflow_streamlit.py (this UI)

Reads a local metadata snapshot in SQLite read-only mode.
Writes user reviews to a separate persistent application database.
The product UI intentionally avoids exposing internal diagnostics by default.
"""
from __future__ import annotations

import importlib.util
import json
import hashlib
import os
from pathlib import Path

import streamlit as st
from ojt2_discovery_core import (
    HISTORY_DB,
    unique_fields, save_review, list_reviews, get_setting, set_setting,
)
from ojt2_adaptive_core import (
    VERSION, RULE_VERSION, parse_excel_requirement, plan_search,
    discover, find_supporting, evidence_summary,
    DOMAIN_RULES, ALIAS_REVIEW_STATUSES,
)
from ojt2_requirement_semantics import decompose_requirement
from ojt2_semantic_engine import semantic_status
from ojt2_bilingual_lexicon import lexicon_status
from ojt2_field_matching import (
    record_alias_decision, record_missing_field_correction, list_missing_field_corrections,
    list_alias_decisions, list_alias_audit, record_term_rule, list_term_rules,
)

HERE = Path(__file__).resolve().parent
PAGES = [
    "01  Upload Requirement",
    "02  Discovery Results",
    "03  Mapping History",
    "04  Metadata Explorer",
    "05  Dashboard",
    "06  Settings",
]


NAV_LABELS = (
    "Upload Requirement",
    "Discovery Results",
    "Mapping History",
    "Metadata Explorer",
    "Dashboard",
    "Settings",
)


@st.cache_resource
def stage3_helpers():
    modpath = HERE / "11_metadata_explorer_streamlit.py"
    if not modpath.is_file():
        raise FileNotFoundError("File 11_metadata_explorer_streamlit.py belum berada di folder yang sama.")
    spec = importlib.util.spec_from_file_location("ojt2_stage3_shared", modpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@st.cache_data(show_spinner="Membuka katalog metadata lokal...", ttl=60)
def load_catalog(modpath: str, path_str: str, stamp: int):
    _ = (modpath, stamp)
    m = stage3_helpers()
    return m.read_catalog(Path(path_str))


def go(target: str):
    st.session_state["_next_nav"] = target


def _nav_start():
    if "_next_nav" in st.session_state:
        st.session_state["nav_page"] = st.session_state.pop("_next_nav")
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGES[0]


def inject_style():
    st.markdown("""<style>
/* Presentation only: match the supplied HTML palette without adding UI content. */
:root {
  --sds-bg:#f5f8fd; --sds-navy:#0e2350; --sds-blue:#1466dd;
  --sds-ice:#e8f1ff; --sds-sub:#62738d; --sds-line:#dfe6f0;
  --sds-ink:#21324f; --sds-shadow:0 8px 26px rgba(17,50,102,.055);
  --primary-color:#1466dd; --text-color:#21324f;
  --background-color:#f5f8fd; --secondary-background-color:#ffffff;
}
html {scroll-behavior:smooth;}
body, [data-testid="stAppViewContainer"], input, textarea, button,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"],
[data-testid="stMetric"], h1, h2, h3, h4 {
  font-family:Inter,'Segoe UI',Arial,sans-serif!important;
}
[data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background:var(--sds-bg); color:var(--sds-ink);
}
[data-testid="stHeader"] {background:rgba(255,255,255,.96);border-bottom:1px solid var(--sds-line);}
.block-container {max-width:1510px;padding:2.2rem 1.4rem 2rem;}
[data-testid="stVerticalBlock"] {gap:.65rem;}
[data-testid="stHorizontalBlock"] {gap:1rem;}
h1 {color:var(--sds-navy)!important;font-size:1.5rem!important;font-weight:800!important;letter-spacing:-.035em!important;line-height:1.3!important;padding-bottom:.35rem!important;}
h2,h3,h4 {color:var(--sds-navy)!important;letter-spacing:-.02em!important;}
h2 {font-size:1.15rem!important;}
h3 {font-size:.96rem!important;font-weight:750!important;}
[data-testid="stMarkdownContainer"] p {color:var(--sds-ink);font-size:.83rem;line-height:1.5;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:var(--sds-sub)!important;font-size:.75rem;line-height:1.45;}
a {color:var(--sds-blue);}
hr {border-color:var(--sds-line)!important;margin:.5rem 0!important;}
/* Sidebar keeps the original labels, ordering, and click callbacks. */
[data-testid="stSidebar"] {background:#fff;border-right:1px solid #e4eaf4;}
[data-testid="stSidebarContent"] {padding:0!important;scrollbar-gutter:auto!important;}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {padding:0 10px 16px!important;width:100%!important;max-width:none!important;box-sizing:border-box;}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:4px;}
[data-testid="stSidebar"] [data-testid="stElementContainer"] {width:100%!important;}
[data-testid="stSidebarHeader"] {height:28px;min-height:28px;margin:0!important;padding:3px 8px!important;background:#0c4baa;}
[data-testid="stSidebarHeader"] button, [data-testid="stSidebarHeader"] [data-testid="stIconMaterial"] {color:#fff!important;}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(> .workspace-brand) {margin-bottom:0!important;}
[data-testid="stSidebarContent"] {background:linear-gradient(#0c4baa 0 28px,#fff 28px);}

.workspace-brand {
  background:linear-gradient(130deg,#0c4baa,#0a63db);color:#fff!important;
  margin:0 -10px 12px;min-height:88px;padding:12px 16px 18px;
  display:flex;align-items:center;gap:12px;box-sizing:border-box;
}
.workspace-brand-logo {
  width:56px;height:56px;flex:0 0 56px;display:flex;align-items:center;
  justify-content:center;background:#fff;border:1px solid #e5edf7;
  border-radius:12px;padding:5px;box-sizing:border-box;overflow:hidden;
}
.workspace-brand-logo img {
  display:block;width:100%;height:100%;object-fit:contain;
}
.workspace-brand-title {
  color:#fff!important;font-size:13px;font-weight:650;line-height:1.45;
  letter-spacing:0;min-width:0;
}
.workspace-brand-title span {display:block;white-space:nowrap;}
[data-testid="stSidebar"] .stButton > button {
  width:100%;justify-content:flex-start;text-align:left;border:1px solid transparent;
  border-radius:10px;padding:.7rem .8rem;min-height:43px;box-shadow:none;
  font-weight:600;transition:background-color .14s ease,color .14s ease;
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"] {background:transparent;color:#485976;}
[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {background:#f0f6ff;border-color:transparent;}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background:#e6f0ff!important;color:#0e5ed1!important;border-color:transparent;
  box-shadow:inset 4px 0 #1872ec;font-weight:750;
}
[data-testid="stSidebar"] .stButton > button p {color:inherit;font-size:.81rem!important;}
[data-testid="stSidebarCollapseButton"] button {color:#fff;}
[data-testid="stSidebar"] .stButton > button > div {justify-content:flex-start;}
/* Existing forms and bordered containers become the mockup's white cards. */
[data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlock"][data-border="true"],
[class*="st-key-ui_"][class*="_card"] {
  background:#fff;border-color:var(--sds-line)!important;border-radius:15px;
  box-shadow:var(--sds-shadow);
}
[data-testid="stForm"] {padding:.9rem;}
[class*="st-key-ui_"][class*="_card"] {padding:16px!important;border:1px solid var(--sds-line);}
.st-key-ui_requirement_card [data-testid="stForm"],
.st-key-ui_vocabulary_card [data-testid="stForm"] {padding:0;border:0;box-shadow:none;}
.st-key-ui_source_detail_card {margin-top:.2rem;}
[data-testid="stExpander"] {background:#fff;border:1px solid var(--sds-line);border-radius:12px;box-shadow:0 3px 14px rgba(17,50,102,.025);}
[data-testid="stExpander"] details {border-color:transparent!important;}
[data-testid="stExpander"] summary {color:var(--sds-navy);font-weight:650;min-height:36px;}
[data-testid="stMetric"] {
  background:#fff;border:1px solid var(--sds-line);border-radius:15px;
  box-shadow:var(--sds-shadow);padding:.85rem .9rem;min-height:90px;
}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {color:var(--sds-sub)!important;font-size:.73rem!important;font-weight:600;}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div, [data-testid="stMetricValue"] p {color:#0f3c81!important;font-size:1.4rem!important;font-weight:750;line-height:1.3;}
[data-testid="stDataFrame"], [data-testid="stTable"] {background:#fff;border:1px solid var(--sds-line);border-radius:12px;overflow:hidden;box-shadow:var(--sds-shadow);}
/* Inputs, upload area, and actions retain native Streamlit behavior. */
[data-testid="stWidgetLabel"] p {color:#445573!important;font-size:.76rem!important;font-weight:650;}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"],
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"] {
  background:#fff!important;border-color:#cad7e9!important;border-radius:9px!important;
}
input,textarea {color:var(--sds-ink)!important;background:#fff!important;}
[data-testid="stTextInputRootElement"]:focus-within,[data-testid="stTextAreaRootElement"]:focus-within,
[data-baseweb="input"]:focus-within,[data-baseweb="select"]:focus-within > div,[data-baseweb="textarea"]:focus-within {
  border-color:var(--sds-blue)!important;box-shadow:0 0 0 3px rgba(20,102,221,.10)!important;
}
[data-baseweb="tag"] {background:#edf4ff!important;color:#185ca9!important;border-radius:99px;border:1px solid #dfebff;}
[data-testid="stFileUploaderDropzone"] {background:#f7fbff;border:2px dashed #9dbff5;border-radius:14px;padding:1.2rem .85rem;}
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius:9px;border:1px solid #c6d4e9;color:#21508b;font-weight:700;
  min-height:36px;padding:.45rem .8rem;transition:background-color .14s ease,box-shadow .14s ease;
}
.stButton > button[kind="secondary"],.stDownloadButton > button[kind="secondary"], [data-testid="stFormSubmitButton"] > button[kind="secondary"] {background:#fff;}
.stButton > button[kind="primary"],.stDownloadButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {
  background:linear-gradient(120deg,#186de2,#0e54be);border-color:#115ecf;color:#fff;
}
.stButton > button p,.stDownloadButton > button p,[data-testid="stFormSubmitButton"] > button p {color:inherit;font-size:.78rem!important;}
.stButton > button:hover,.stDownloadButton > button:hover {border-color:#7ca6e7;background:#f4f8ff;color:#1459b2;}
.stButton > button[kind="primary"]:hover,[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"]:hover {background:linear-gradient(120deg,#2479ec,#1466dd);color:white;}
button:focus-visible,a:focus-visible {outline:3px solid #92baff!important;outline-offset:3px;}
button:disabled {opacity:.5;cursor:not-allowed;}
[data-baseweb="tab-list"], [data-testid="stTabs"] [role="tablist"] {gap:.4rem;flex-wrap:wrap;height:auto;padding:.3rem 0 .65rem;}
button[data-baseweb="tab"], [data-testid="stTabs"] [role="tab"] {height:auto;border-radius:10px;padding:.45rem .7rem;background:#f3f6fb;border:1px solid #e6edf5;color:#61728b;}
button[data-baseweb="tab"][aria-selected="true"], [data-testid="stTabs"] [role="tab"][aria-selected="true"] {background:#e2efff;border-color:#9dc4ff;color:#125ac1;font-weight:700;}
button[data-baseweb="tab"] p, [data-testid="stTabs"] [role="tab"] p {color:inherit;font-size:.76rem!important;}
[data-baseweb="tab-highlight"] {background:var(--sds-blue);}
[data-testid="stTabs"] .react-aria-SelectionIndicator {background:var(--sds-blue)!important;height:2px;}
[data-testid="stTabs"] [role="tablist"] {border-color:var(--sds-line);}
[data-testid="stTabs"] [role="tab"] [data-testid="stMarkdownContainer"] {margin-bottom:0!important;}
[data-testid="stTabs"] [role="tab"] p {margin:0!important;}
[data-baseweb="tab-border"] {background:var(--sds-line);}
[data-testid="stProgress"] [role="progressbar"] {background:linear-gradient(90deg,#2882ef,#12a582);border-radius:99px;}
[data-testid="stCode"] {border-radius:10px;border:1px solid var(--sds-line);}
[data-testid="stAlert"] {border-radius:10px;}
[data-testid="stAlertContainer"], [data-testid="stAlert"] > div {padding:8px 12px!important;gap:8px!important;}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p,
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] li,
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] {
  margin:0!important;color:inherit;font-size:12px!important;line-height:1.5!important;overflow-wrap:anywhere;
}
[data-testid="stAlert"] p {margin:0!important;}
[data-testid="stAlert"] svg {width:16px;height:16px;flex-shrink:0;}
[data-testid="stAlert"] [data-testid="stIconMaterial"] {font-size:18px;}
/* Keep segmented controls visually consistent with the native detail tabs. */
[data-testid="stSegmentedControl"] button {font-size:12px;border-radius:8px;}

[role="dialog"] {background:#fff;border-radius:17px;box-shadow:0 25px 70px rgba(11,34,72,.24);border:1px solid var(--sds-line);}
.workspace-divider {height:1px;margin:1.1rem 0;background:var(--sds-line);}
.workspace-note {font-size:.8rem;color:var(--sds-sub);}
/* Preserve the controls already hidden by the preceding app theme. */
[data-testid="stDeployButton"], [data-testid="stAppDeployButton"] {display:none;}
footer {visibility:hidden;}
/* Width applies only while expanded. Native Streamlit collapse owns its width/margins. */
@media(min-width:901px) {
  [data-testid="stSidebar"][data-collapsed="false"],
  [data-testid="stSidebar"][aria-expanded="true"] {width:242px!important;min-width:242px!important;max-width:242px!important;}
}
@media(max-width:1150px) {
  [class*="st-key-ui_"][class*="_columns"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important;}
  [class*="st-key-ui_"][class*="_columns"] [data-testid="stColumn"] {flex:1 1 100%!important;width:100%!important;min-width:0!important;}
}

@media(max-width:900px) {
  .block-container {padding:2.2rem 1rem 2rem;}
  h1 {font-size:1.45rem!important;}
  [data-testid="stForm"] {padding:1rem;}
}
@media(max-width:640px) {
  [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important;}
  [data-testid="stColumn"] {flex:1 1 100%!important;min-width:0!important;width:100%!important;}
  [data-testid="stMetric"] {min-height:96px;}
  [data-baseweb="tab-list"], [data-testid="stTabs"] [role="tablist"] {gap:.35rem;}
  button[data-baseweb="tab"], [data-testid="stTabs"] [role="tab"] {padding:.5rem .65rem;}
}
@media(prefers-reduced-motion:reduce) {* {scroll-behavior:auto!important;transition:none!important;}}

</style>""", unsafe_allow_html=True)


def title_line(title: str, subtitle: str = ""):
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def workflow_steps(active: int):
    """Retained for compatible imports. Sidebar + page content now provide navigation."""
    return None


def _objname(o):
    return f"{o['database_name']}.{o['schema_name']}.{o['object_name']}"


def _pick_scope(data):
    all_db = sorted({o["database_name"] for o in data["objects"]})
    logical = {d: next(o["logical_server"] for o in data["objects"] if o["database_name"] == d)
               for d in all_db}
    with st.expander("Search Scope", expanded=False):
        custom = st.checkbox("Pilih database tertentu", value=False, key="custom_scope_enabled",
                             help="Secara default seluruh database terdaftar yang diizinkan akan ditelusuri.")
        if custom:
            display = {d: f"{logical[d]} · {d}" for d in all_db}
            allowed = st.multiselect("Database", all_db,
                                     format_func=lambda d: display[d], default=all_db,
                                     key="custom_dbs")
            if not allowed:
                st.warning("Pilih setidaknya satu database.")
            return allowed
    return all_db


def _sidebar(data, metadata_ok: bool):
    # data and metadata_ok are retained for API compatibility; internal counters are
    # intentionally hidden from the regular navigation UI.
    with st.sidebar:
        # Keep the supplied brand image local; no network request is needed.
        logo_path = HERE / "assets" / "sds_logo.png"
        logo_html = ""
        if logo_path.is_file():
            import base64
            try:
                logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
                logo_html = ('<span class="workspace-brand-logo" aria-hidden="true">'
                             f'<img src="data:image/png;base64,{logo_data}" alt="">'
                             '</span>')
            except OSError:
                pass  # An unavailable decorative image must not block discovery.
        st.markdown(
            '<div class="workspace-brand">' + logo_html +
            '<span class="workspace-brand-title"><span>Smart Data</span>'
            '<span>Source Discovery</span></span></div>',
            unsafe_allow_html=True)
        for i, (page_key, label) in enumerate(zip(PAGES, NAV_LABELS)):
            st.button(label,
                      key=f"workspace_nav_{i}",
                      on_click=go,
                      args=(page_key,),
                      type="primary" if st.session_state.get("nav_page") == page_key else "secondary",
                      use_container_width=True)


def page_upload(data, index):
    title_line("Upload Requirement", "Unggah dokumen kebutuhan data, periksa informasi, lalu temukan sumber yang relevan.")
    with st.container(key="ui_upload_columns"):
        document_panel, requirement_panel = st.columns([1, 1.18], gap="medium")
        with document_panel:
            with st.container(border=True, key="ui_document_card"):
                st.subheader("Document Requirement")
                uploaded = st.file_uploader("Pilih file Excel", type=["xlsx", "xlsm", "csv"],
                                            help="Gunakan dokumen requirement yang sudah biasa dipakai; format tidak perlu diubah.")
                if uploaded is not None:
                    import hashlib
                    data_bytes = uploaded.getvalue()
                    digest = hashlib.sha256(data_bytes).hexdigest()
                    if st.session_state.get("upload_hash") != digest:
                        # Never show stale fields from a previous file after a parsing failure.
                        st.session_state["req_ctx"] = {}
                        st.session_state["upload_hash"] = None
                        try:
                            parsed = parse_excel_requirement(data_bytes, uploaded.name)
                            st.session_state["req_ctx"] = parsed
                            st.session_state["upload_hash"] = digest
                            st.success("Dokumen berhasil dibaca. Periksa hasilnya sebelum Analyze.")
                        except Exception as exc:
                            st.error(f"Dokumen belum dapat diproses: {exc}")
                    if st.session_state.get("upload_hash") == digest:
                        parsed = st.session_state.get("req_ctx", {})
                        with st.expander("Pratinjau dokumen", expanded=False):
                            st.dataframe(parsed.get("preview_rows", []), use_container_width=True)
                            for note in parsed.get("parse_notes", []):
                                st.warning(note)
        with requirement_panel:
            with st.container(border=True, key="ui_requirement_card"):
                st.subheader("Review Requirement")
                st.caption("Pastikan hasil pembacaan sesuai sebelum memulai pencarian.")
                req = st.session_state.get("req_ctx", {})
                allowed = _pick_scope(data)
                with st.form("requirement_review_form", clear_on_submit=False):
                    purpose = st.text_area("Purpose / Business Context", value=req.get("purpose", ""), height=100)
                    left, right = st.columns(2, gap="medium")
                    source_hint = left.text_input("Data Source / Report / Menu", value=req.get("source_hint", ""))
                    filtering = right.text_input("Filtering", value=req.get("filtering", ""))
                    required_text = st.text_area("Columns Required (satu field per baris)",
                                                 value="\n".join(req.get("required_fields", [])), height=190)
                    submitted = st.form_submit_button("Analyze Sources", type="primary", use_container_width=True)
    if submitted:
        if not allowed:
            st.error("Search scope kosong.")
        elif not (purpose.strip() or source_hint.strip() or required_text.strip()):
            st.error("Isi minimal Purpose, Data Source, atau Columns Required.")
        else:
            context = {"purpose":purpose.strip(), "source_hint":source_hint.strip(),
                       "filtering":filtering.strip(), "required_fields":unique_fields(required_text),
                       "origin":req.get("origin", "User input")}
            st.session_state["req_ctx"] = context
            st.session_state["allowed_dbs"] = allowed
            plan = plan_search(context)
            st.session_state["adaptive_plan"] = plan
            if plan["primary"] == "INSUFFICIENT_EVIDENCE":
                st.warning("Informasi belum cukup. Tambahkan Purpose, Data Source, atau field yang lebih spesifik.")
            else:
                results = discover(data, index, context, allowed_databases=allowed,
                                   limit=int(get_setting("max_candidates", 12)))
                st.session_state["discovery_results"] = results
                st.session_state["selected_candidate"] = results[0]["object_key"] if results else ""
                go(PAGES[1])
                st.rerun()


def _load_demo():
    """Legacy no-op: sample/test-case UI is intentionally excluded."""
    return None


def _support_cache_key(req,candidate,allowed,metadata_run_id):
    revision=HISTORY_DB.stat().st_mtime_ns if HISTORY_DB.exists() else 0
    payload={'request':req,'candidate':candidate['object_key'],'mapping':candidate['field_map'],
             'scope':sorted(allowed),'catalog_run':metadata_run_id,'history_revision':revision,
             'engine':VERSION,'rules':RULE_VERSION}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def page_results(data, index, mod, metadata_fresh: bool, metadata_run_id: int):
    title_line("Discovery Results", "Bandingkan sumber data, periksa kecocokan field, dan tinjau rekomendasi.")
    req = st.session_state.get("req_ctx")
    ranked = st.session_state.get("discovery_results", [])
    if not req or not ranked:
        st.info("Belum ada hasil discovery. Silakan jalankan Analyze dari Upload Requirement.")
        st.button("Buka Upload Requirement", on_click=go, args=(PAGES[0],), type="primary")
        return
    allowed = st.session_state.get("allowed_dbs", [])
    plan=st.session_state.get("adaptive_plan") or plan_search(req)
    with st.container(key="ui_results_columns"):
        candidates_panel, context_panel = st.columns([1.18, .82], gap="medium")
        with candidates_panel:
            with st.container(border=True, key="ui_candidates_card"):
                st.subheader("Recommended Sources")
                short = []
                for i, r in enumerate(ranked,1):
                    short.append({"Rank": i, "Candidate Source":_objname(r["object"]),
                                  "Type":r["type"], "Relevance score":r["score"],
                                  "Exact fields":f"{r['matched']}/{r['total']}" if r["total"] else "N/A",
                                  "Alias proposed":r.get('alias_proposed',0),
                                  "Context review":max(0,r.get('context_proposed',0)-r.get('semantic_proposed',0)),
                                  "Semantic review":r.get('semantic_proposed',0),
                                  "Logical server":r["availability"]})
                st.dataframe(short, hide_index=True, use_container_width=True, height=min(410, 40+len(short)*36))
                options = [r["object_key"] for r in ranked]
                selected = st.selectbox("Inspect candidate", options,
                                        index=options.index(st.session_state.get("selected_candidate")) if st.session_state.get("selected_candidate") in options else 0,
                                        format_func=lambda k: next(f"{i+1}. {_objname(r['object'])} | exact {r['matched']} · alias {r.get('alias_proposed',0)} · review {r.get('context_proposed',0)}/{r['total']} | score {r['score']}" for i,r in enumerate(ranked) if r["object_key"]==k))
                st.session_state["selected_candidate"] = selected
        with context_panel:
            with st.container(border=True, key="ui_context_card"):
                with st.expander("Requirement Summary", expanded=False):
                    a,b,c=st.columns(3)
                    a.write("**Purpose**"); a.caption(req.get("purpose", "—"))
                    b.write("**Source Hint**"); b.caption(req.get("source_hint", "—"))
                    c.write("**Filtering**"); c.caption(req.get("filtering", "—"))
                    st.caption(f"{len(req.get('required_fields',[]))} fields · Search scope: {', '.join(allowed) if allowed else 'All'}")
                with st.expander("How results were selected", expanded=False):
                    st.write("**Search strategy:**", ", ".join(plan.get("strategies", [])))
                    st.write("**Business domain:**", plan.get("domain") or "Unspecified")
                    st.write("**Konteks yang cocok pada domain:**", plan.get('domain_patterns', []))
                    st.write("**Exact object hint:**", plan.get('exact_object') or 'Tidak ada')
                    st.write("**Application registry:**", plan.get('registry') or 'Tidak ada, URL tidak otomatis dipetakan')
                    semantic=semantic_status()
                    st.caption('Semantic retrieval: '+('local model available' if semantic['ready']
                               else f"not active ({semantic['reason']}); lexical/contextual engine remains operational"))
                    st.caption("Saran kemiripan belum merupakan konfirmasi makna bisnis. Perlu review PIC.")
                for warning in plan['warnings']: st.warning(warning)
                vocabulary=lexicon_status()
                if not vocabulary['ready']:
                    st.warning('File kamus bilingual bawaan belum tersedia atau tidak dapat dibaca. '
                               'Pastikan seluruh file paket pembaruan disalin bersama.')
                if not semantic_status()['ready']:
                    st.warning('Pencarian menggunakan kamus bilingual; model multilingual lokal belum aktif. '
                               'Kemiripan makna di luar kamus mungkin belum dikenali. Cek Settings untuk status model.')
                # Keep the PIC workspace clean, while exposing the parser interpretation
                # for audit and quick correction of long real-world requirements.
                with st.expander("Requirement interpretation", expanded=False):
                    st.dataframe([{
                        "Original Field": f,
                        "Field Concept": decompose_requirement(f).label,
                        "Additional Context / Formula": decompose_requirement(f).note or "—",
                        "Formula Review": decompose_requirement(f).formula,
                    } for f in req.get('required_fields',[])],hide_index=True,use_container_width=True)
                    st.caption("Deskripsi dan rumus dipertahankan untuk PIC review. Pemisahan teks bukan validasi mapping.")
    c = next(r for r in ranked if r["object_key"]==selected)
    cache_key=_support_cache_key(req,c,allowed,metadata_run_id)
    cached_support=st.session_state.get('_support_cache')
    if cached_support and cached_support['key']==cache_key:
        support=cached_support['value']
    else:
        support = find_supporting(data,index,c,req,allowed_databases=allowed)
        st.session_state['_support_cache']={'key':_support_cache_key(req,c,allowed,metadata_run_id),'value':support}
    summary = evidence_summary(c,support)
    with st.container(border=True, key="ui_source_detail_card"):
        st.subheader("Source Detail")
        st.caption(_objname(c["object"]))
        a,b,d,e=st.columns(4)
        a.metric("Relevance score", f"{c['score']:.1f}/100")
        b.metric("Exact fields", f"{summary['direct']}/{summary['total']}")
        d.metric("Needs PIC review", f"{summary.get('alias_proposed',0)+c.get('context_proposed',0)}")
        e.metric("Potential combined",f"{summary['potential']}/{summary['total']}",help="Proposed aliases + candidate supporting sources, NOT verified")
        # Technical engine/rule version is available in persisted audit records, not in the PIC workspace.
        if summary.get('reference_key_suggestions', 0):
            st.warning(f"{summary['reference_key_suggestions']} key candidate(s) detected (e.g. SelectionID). An identifier is NOT the Selection business value; verify lookup/meaning before marking mapped.")
        for warning in c.get('warnings', []): st.warning(warning)
        if c["type"]=="Stored Procedure":
            st.warning("Stored Procedure tidak punya result-set columns dari sys.columns. Coverage 0 bukan bukti SP tidak mengandung field yang diminta. Lihat target WRITES_TO dan lineage.")
        if not metadata_fresh:
            st.error("Metadata baru di-refresh tetapi lineage lama; jalankan script 09 sebelum mengandalkan lineage.")

        t_fields,t_gap,t_line,t_review=st.tabs(["Field Mapping","Source Gap","Lineage","PIC Review"])
        with t_fields:
            rows=[{"Required Field":m["requested"], "Matched Column":m["actual"] or "—",
                   "Status":m["status"],"Evidence":m["evidence"]} for m in c["field_map"]]
            if rows: st.dataframe(rows, hide_index=True,use_container_width=True)
            else: st.info("Dokumen tidak menyebut Columns Required. Ranking menggunakan Source Hint dan Purpose.")
            if c["total"]:
                st.progress(c["mapped_proposed"]/c["total"],text=f"Direct + lexical proposals: {c['mapped_proposed']}/{c['total']} (not verified)")
                if c.get('context_proposed'):
                    st.caption(f"{c['context_proposed']} contextual/semantic review hypotheses. "
                               "They are NOT included in field coverage or verified mapping.")
            # Present ONE best suggestion per requested field. Full hypotheses
            # remain available internally for PIC correction/feedback, but raw
            # semantic neighbors must never flood the review screen.
            alt_rows=[]
            for m in c['field_map']:
                if m['status']=='NAME_MATCH':
                    continue
                primary = None
                if m.get('actual'):
                    primary = next((v for v in m.get('suggestions',[])
                             if v['actual']==m['actual']), None)
                    if primary is None:
                        primary = {'actual':m['actual'],'status':m['status'],
                                   'rank_score':None,'evidence':m.get('evidence','')}
                elif m['status'] in {'AMBIGUOUS_MATCH_REVIEW','MULTIPLE_CONTEXT_OPTIONS_REVIEW','MULTIPLE_ATTRIBUTE_OPTIONS_REVIEW'}:
                    for option in m.get('suggestions',[])[:5]:
                        alt_rows.append({'Required Field':m['requested'],
                            'Suggested Column':option['actual'], 'Status':m['status'],
                            'Ranking signal (not confidence)':option.get('rank_score'),
                            'Reason':'Beberapa kandidat tersedia; pilih sesuai kebutuhan. '+option.get('evidence','')})
                    continue
                elif m.get('suggestions'):
                    primary = m['suggestions'][0]
                if primary:
                    alt_rows.append({
                        'Required Field':m['requested'],
                        'Suggested Column':primary['actual'],
                        'Status':primary['status'],
                        'Ranking signal (not confidence)':primary.get('rank_score'),
                        'Reason':primary.get('evidence',''),
                    })
            if alt_rows:
                with st.expander('Best suggestion per field — PIC review', expanded=False):
                    st.caption('Saran utama per field; jika ambigu, beberapa alternatif ditampilkan. Skor bukan probabilitas dan saran belum berarti mapping terverifikasi.')
                    st.dataframe(alt_rows, hide_index=True, use_container_width=True)
                    if any(x['Status'] in {'REFERENCE_KEY_REVIEW','IDENTIFIER_GRAIN_REVIEW'} for x in alt_rows):
                        st.warning('ID/key dapat berbeda granularitas atau merujuk lookup. Periksa dengan PIC sebelum approval.')
            # PIC feedback dropdown follows the same ONE-primary-candidate rule.
            # Other columns can still be chosen via Manual Missing Correction.
            proposed=[]
            reviewable = ALIAS_REVIEW_STATUSES | {
                'ATTRIBUTE_EXTENSION_REVIEW','OBJECT_CONTEXT_REVIEW',
                'ACTOR_ATTRIBUTE_REVIEW','EVENT_SEMANTIC_REVIEW',
                'ANNOTATION_CONTEXT_REVIEW','FORMULA_DEFINITION_REVIEW',
                'SEMANTIC_REVIEW','CROSS_DOMAIN_FEEDBACK_REVIEW',
                'SAME_DOMAIN_FEEDBACK_REVIEW','QUALIFIED_ATTRIBUTE_REVIEW',
                'IDENTIFIER_GRAIN_REVIEW','POTENTIAL_MATCH_REVIEW'}
            for m in c['field_map']:
                if m['status'] in {'AMBIGUOUS_MATCH_REVIEW','MULTIPLE_CONTEXT_OPTIONS_REVIEW','MULTIPLE_ATTRIBUTE_OPTIONS_REVIEW'}:
                    proposed.extend({'requested':m['requested'],'actual':option['actual'],'status':option['status']}
                        for option in m.get('suggestions',[]) if option['status'] in reviewable)
                    continue
                candidate = ({'actual':m['actual'],'status':m['status']}
                             if m.get('actual') and m['status'] in reviewable else None)
                if candidate is None and m.get('suggestions'):
                    best=m['suggestions'][0]
                    if best['status'] in reviewable:
                        candidate={'actual':best['actual'],'status':best['status']}
                if candidate:
                    proposed.append({'requested':m['requested'],**candidate})
            if proposed:
                st.info('Feedback PIC disimpan sebagai keputusan validasi pada object ini. '
                        'Secara terpisah, evidence-nya memengaruhi ranking suggestions di semua domain '
                        '(Learn Globally, Validate Locally); tidak otomatis memverifikasi object lain.')
                with st.expander('Alias Feedback & Learning — simpan keputusan PIC', expanded=False):
                    st.caption('Persetujuan berlaku pada objek ini saja. Objek/domain lain menerima '
                               'sinyal historical feedback untuk saran baru, BUKAN persetujuan otomatis.')
                    labels=[f"{m['requested']}  →  {m['actual']} [{m['status']}]" for m in proposed]
                    selected_label=st.selectbox('Field alias untuk dinilai', labels, key='alias_feedback_choice')
                    chosen_map=proposed[labels.index(selected_label)]
                    with st.form('alias_feedback_form'):
                        decision=st.selectbox('Keputusan', ['APPROVED', 'REJECTED'],
                                          format_func=lambda v: 'Approve alias' if v=='APPROVED' else 'Reject alias')
                        reviewer_alias=st.text_input('PIC reviewer alias', key='alias_feedback_reviewer')
                        notes_alias=st.text_area('Alasan dan bukti verifikasi (wajib)',
                               placeholder='Jelaskan alasan kedua field memiliki makna bisnis yang sama.')
                        submitted_alias=st.form_submit_button('Simpan feedback dan hitung ulang ranking', type='primary')
                    if submitted_alias:
                        try:
                            domain=plan.get('domain')
                            # 'GENERAL' scopes review to this object when no curated
                            # business domain is inferred; never invent a domain.
                            record_alias_decision(domain or 'GENERAL', c['object_key'], chosen_map['requested'], chosen_map['actual'],
                                                  decision, reviewer_alias, notes_alias)
                            st.session_state['discovery_results']=discover(data,index,req,allowed_databases=allowed,
                                                    limit=int(get_setting('max_candidates', 12)))
                            st.success('Feedback tersimpan di Alias Registry. Ranking dihitung ulang.')
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            # Recovery path for false negatives: the reviewer can select ANY real
            # catalog column even when neither lexical nor semantic retrieval found it.
            # A decision is saved in the SAME object-scoped Alias Registry and also
            # independently audited as a missed-candidate correction.
            unresolved=[m for m in c['field_map'] if m['status']!='NAME_MATCH']
            physical_columns=index['columns'].get(c['object_key'],[])
            if unresolved and physical_columns:
                with st.expander('Field tidak ditemukan? Koreksi mapping secara manual',expanded=False):
                    st.caption('Jika field sebenarnya tersedia tetapi engine tidak mengusulkannya, pilih kolom yang benar. '
                               'Koreksi akan dipakai ulang pada objek ini, bukan otomatis untuk semua database.')
                    labels=[f"{m['requested']}  [{m['status']}]" for m in unresolved]
                    chosen_label=st.selectbox('Required field yang akan dikoreksi',labels,key='missing_fix_field')
                    missed=unresolved[labels.index(chosen_label)]
                    with st.form('missing_field_correction_form'):
                        corrected=st.selectbox('Kolom SQL yang benar di tabel/View terpilih',
                                [col['column_name'] for col in physical_columns],key='missing_fix_col')
                        corrected_by=st.text_input('Reviewer / PIC',key='missing_fix_reviewer')
                        corrected_reason=st.text_area('Bukti dan alasan kesamaan makna (wajib)',
                            placeholder='Contoh: CreatedBy adalah pengaju pada workflow ini menurut konfirmasi PIC.')
                        corrected_ack=st.checkbox('Saya telah memverifikasi definisi bisnis kolom ini, termasuk event dan formula jika relevan.')
                        corrected_submit=st.form_submit_button('Simpan koreksi dan pelajari mapping',type='primary')
                    if corrected_submit:
                        if not corrected_ack:
                            st.error('Verifikasi PIC harus dikonfirmasi sebelum menyimpan koreksi.')
                        else:
                            try:
                                record_missing_field_correction(plan.get('domain') or 'GENERAL',
                                    c['object_key'],missed['requested'],corrected,missed['status'],
                                    corrected_by,corrected_reason,physical_columns)
                                st.session_state['discovery_results']=discover(data,index,req,
                                    allowed_databases=allowed,limit=int(get_setting('max_candidates',12)))
                                st.session_state['selected_candidate']=c['object_key']
                                st.success('Koreksi disimpan pada Alias Registry dan audit. Ranking diperbarui.')
                                st.rerun()
                            except Exception as exc:
                                st.error(f'Koreksi gagal disimpan: {exc}')
            if c["mapped_proposed"]<c["total"]:
                st.warning("Unmatched/derived fields require separate source, SQL expression or manual review; no automatic full-coverage claim.")

        with t_gap:
            st.markdown("#### Generalized Supporting Source Candidates")
            st.caption("Semua domain memakai shared field matcher dan metadata lineage. Tidak ada key khusus GDL/STIP. "
                       "Status JOIN masih proposal; data runtime belum diuji.")
            if not support:
                st.info("Tidak ditemukan supporting source dalam search scope. Cek requirement, scope, atau mapping derived/manual.")
            else:
                rows=[]
                for s in support:
                    k=s.get('suggested_key') or {}
                    rows.append({
                        "Missing Field":s['missing_field'],
                        "Supporting Source":_objname(s['source']),
                        "Matched Column":s['actual_field'],
                        "Field Evidence":s['match_status'],
                        "JOIN Status":s['join_status'],
                        "Top Key Proposal":(f"{k.get('main_column')} = {k.get('support_column')}" if k else "None"),
                        "Join candidates":len(s.get('join_candidates',[])),
                        "Ranking Signal":s['priority'],
                        "Runtime Verified":"No",
                    })
                st.dataframe(rows,hide_index=True,use_container_width=True)
                # Field + object: otherwise several missing fields from same source overwrite each other.
                entries={f"{i+1}. {s['missing_field']} | {_objname(s['source'])}":s
                         for i,s in enumerate(support)}
                selected_gap=st.selectbox("Inspect supporting source & JOIN proposals",list(entries),
                                         key="gap_source_choice")
                item=entries[selected_gap]
                st.write(f"**Missing field:** `{item['missing_field']}` → "
                         f"`{item['actual_field']}` ({item['match_status']})")
                st.write(f"**JOIN evidence:** `{item['join_status']}` · "
                         f"Physical instance same: `{item['same_physical_server']}` · "
                         f"Same lineage: `{item['same_lineage_source']}`")
                st.caption(item.get('match_evidence',''))
                if item.get('join_candidates'):
                    st.markdown("**Candidate JOIN keys — ranked, never auto-approved**")
                    st.dataframe([{
                        "Main Key":p['main_column'],"Supporting Key":p['support_column'],
                        "Key Evidence":p['match_type'],"Main Type":p['main_sql_type'],
                        "Supporting Type":p['support_sql_type'],
                        "Ranking Signal":p['ranking_signal'],
                        "Cardinality":"NOT MEASURED",
                    } for p in item['join_candidates']],hide_index=True,use_container_width=True)
                else:
                    st.warning("Tidak ada bukti candidate JOIN key. Sumber mungkin relevan secara field, "
                               "tetapi belum bisa diusulkan sebagai composite source.")
                for w in item.get('warnings',[]):st.caption("• " + w)
                if item['source'].get('sql_definition'):
                    with st.expander("Supporting source SQL definition (read-only)"):
                        st.code(item['source']['sql_definition'],language='sql')
                if any(s['source']['logical_server']!='DGA' for s in support):
                    st.info("Sumber di luar logical DGA perlu cek ketersediaan DGA / connectivity; "
                            "replication advisory bukan perintah replikasi otomatis.")
            st.markdown("#### Source solution comparison")
            st.write(f"**Exact direct:** {summary['direct']}/{summary['total']} · "
                     f"**Direct with alias proposals:** {summary['proposal_direct']}/{summary['total']}")
            st.write(f"**Potential with candidate JOIN evidence:** {summary['potential']}/{summary['total']} — NOT VERIFIED")
            st.caption("Coverage gabungan hanya potensi: alias, key uniqueness, row cardinality, "
                       "NULL, match rate, filters, business grain dan access policy belum tervalidasi.")
            if summary.get('unresolved'):
                st.warning("Belum punya bukti JOIN yang cukup untuk: " + ", ".join(summary['unresolved']))

        with t_line:
            if metadata_fresh:
                direction=st.selectbox("Lineage direction",["Upstream","Downstream"],key="result_dir")
                depth=st.slider("Maximum hops",1,6,3,key="result_depth")
                steps,nodes=mod.traverse(index,selected,direction,depth)
                st.caption(f"{len(nodes)} objects · {len(steps)} edges · STATIC INFERRED")
                if steps:
                    try: st.graphviz_chart(mod.dot_graph(index,steps,selected).replace("\\\\n", "\\n"),use_container_width=True)
                    except Exception as exc: st.warning(f"Graphviz failed: {exc}")
                    st.dataframe([{"Hop":s["depth"],"From":_objname(index["objects"][s["from"]]),
                                  "Relation":s["relation"],"To":_objname(index["objects"][s["to"]]),
                                  "Evidence":s["status"]} for s in steps],hide_index=True,use_container_width=True)
                else: st.info("Tidak ditemukan lineage pada arah ini.")
            st.markdown("#### SQL Definition")
            if c["object"].get("sql_definition"):
                with st.expander("Lihat SQL Definition",expanded=False):
                    st.code(c["object"]["sql_definition"],language="sql",line_numbers=True)
            elif c["type"]=="Table":
                st.caption("Tabel fisik tidak punya sys.sql_modules definition. Lihat GENERATED_BY untuk pembentuknya.")

        with t_review:
            st.markdown("#### PIC Source Review — Save to Mapping History")
            st.info("Tombol ini menyimpan **review kandidat**, bukan mengesahkan seluruh field mapping/relasi. Tidak ada SP yang dieksekusi.")
            reviewer=st.text_input("Reviewer / PIC",placeholder="Inisial atau ID PIC",key="reviewer")
            note=st.text_area("Review notes (wajib)",placeholder="Jelaskan kecocokan sumber, hal yang masih perlu diverifikasi, dan tindak lanjut.",key="review_notes")
            chosen=st.multiselect("Supporting sources yang ingin ditinjau",[s["source"]["object_key"] for s in support],
                                  format_func=lambda k:_objname(index["objects"][k]),key="review_support") if support else []
            consent=st.checkbox("Saya telah meninjau bahwa mapping dan JOIN masih memerlukan verifikasi.",key="review_ack")
            if st.button("Save PIC Review to History",type="primary",disabled=not consent,use_container_width=True):
                if not reviewer.strip() or not note.strip():
                    st.error("Reviewer dan review notes wajib diisi.")
                else:
                    try:
                        review_id=save_review(req,c,[{"object_key":k,"name":_objname(index["objects"][k])} for k in chosen],
                                              reviewer,note,allowed,metadata_run_id)
                        st.success(f"Review disimpan! ID: {review_id}. Data berada di SQLite persistent terpisah.")
                    except Exception as exc: st.error(f"Gagal simpan review: {exc}")


def page_history():
    title_line("Mapping History", "Tinjau hasil review dan keputusan mapping yang tersimpan.")
    with st.container(border=True, key="ui_history_card"):
        items=list_reviews()
        if not items:
            st.info("Belum ada riwayat. Review sebuah kandidat dari Discovery Results untuk membuat record pertama.")
            return
        rows=[]
        for x in items:
            req=json.loads(x["requirement_json"])
            rows.append({"Date UTC":x["saved_at"],"Reviewer":x["actor"],
                         "Purpose":req.get("purpose", "")[:80],"Candidate":x["candidate_fqn"],
                         "Review Status":x["status"], "Engine":x["engine_version"],"ID":x["id"]})
        st.dataframe(rows,hide_index=True,use_container_width=True)
        chosen=st.selectbox("View saved record",[item["id"] for item in items],
                            format_func=lambda k: next(f"{r['Date UTC']} · {r['Candidate']} · ID {k}" for r in rows if r["ID"]==k))
        item=next(x for x in items if x["id"]==chosen)
        st.write("**Reviewer notes:**",item["notes"])
        a,b,c=st.columns(3)
        a.caption(f"Catalog snapshot: {item['catalog_run_id']}")
        b.caption(f"Engine: {item['engine_version']}")
        c.caption(f"Rule: {item['rule_version']}")
        with st.expander("Stored requirement & evidence"):
            st.json({"requirement":json.loads(item["requirement_json"]),
                     "score_and_fields":json.loads(item["score_json"]),
                     "selected_supporting":json.loads(item["selected_support_json"]),
                     "scope":json.loads(item["source_scope"])})



def _refresh_discovery_if_available(data, index):
    """Recalculate existing results when the reviewer teaches an alias from Explorer."""
    request=st.session_state.get('req_ctx')
    if request and st.session_state.get('discovery_results') is not None:
        previous=st.session_state.get('selected_candidate')
        allowed=st.session_state.get('allowed_dbs')
        results=discover(data,index,request,allowed_databases=allowed,
                         limit=int(get_setting('max_candidates',12)))
        st.session_state['discovery_results']=results
        available={r['object_key'] for r in results}
        st.session_state['selected_candidate']=(previous if previous in available
             else results[0]['object_key'] if results else '')


def _meta_saved_widget(key: str, default, options=None):
    """Restore metadata controls from non-widget session state after navigation.

    Streamlit cleans widget keys when the user visits a different page; the
    separate _meta_workspace dictionary is not bound to any widget lifecycle.
    """
    saved=st.session_state.setdefault('_meta_workspace',{})
    if key not in st.session_state:
        value=saved.get(key,default)
        if options is not None and value not in options:
            value=default
        st.session_state[key]=value
    elif options is not None and st.session_state[key] not in options:
        st.session_state[key]=default
    saved[key]=st.session_state[key]


def _meta_remember(key: str):
    st.session_state.setdefault('_meta_workspace',{})[key]=st.session_state[key]


def page_metadata(data,index,mod, fresh):
    title_line('Metadata Explorer','Telusuri objek dan kolom yang tersedia pada Metadata Catalog.')
    with st.container(border=True, key="ui_metadata_filters_card"):
        search_panel, a, b = st.columns([2, 1, 1], gap="medium")
        _meta_saved_widget('meta_search','')
        q=search_panel.text_input('Search metadata',placeholder='Nama tabel, View, SP, atau kolom',
                        key='meta_search',on_change=_meta_remember,args=('meta_search',))
        servers=['All']+sorted({o['logical_server'] for o in data['objects']})
        _meta_saved_widget('meta_server','All',servers)
        logical=a.selectbox('Logical Server',servers,key='meta_server',
                            on_change=_meta_remember,args=('meta_server',))
        dbs=['All']+sorted({o['database_name'] for o in data['objects']
                           if logical=='All' or o['logical_server']==logical})
        _meta_saved_widget('meta_db','All',dbs)
        database=b.selectbox('Database',dbs,key='meta_db',
                             on_change=_meta_remember,args=('meta_db',))

    # Empty query intentionally lists ALL accessible objects; no empty-screen prompt.
    found=mod.search_objects(data,index,q,logical_server=logical,database=database)
    if not found:
        st.info('Tidak ada objek sesuai filter. Hapus pencarian untuk melihat seluruh objek.')
        return
    with st.container(key="ui_metadata_columns"):
        objects_panel, details_panel = st.columns([1.18, .82], gap="medium")
        with objects_panel:
            with st.container(border=True, key="ui_metadata_objects_card"):
                st.dataframe([{'Source':_objname(o),'Type':o['object_type_desc'],
                               'Logical Server':o['logical_server']} for o in found],
                             hide_index=True,use_container_width=True,height=min(380,40+len(found)*35))
                object_keys=[o['object_key'] for o in found]
                _meta_saved_widget('meta_object',object_keys[0],object_keys)
                key=st.selectbox('Inspect metadata object',object_keys,
                    format_func=lambda k:_objname(index['objects'][k]),key='meta_object',
                    on_change=_meta_remember,args=('meta_object',))
        with details_panel:
            with st.container(border=True, key="ui_metadata_detail_card"):
                obj=index['objects'][key]
                cols=index['columns'].get(key,[])
                view_options=['Columns','SQL Definition','Recursive Lineage','Field Finder']
                _meta_saved_widget('meta_view','Columns',view_options)
                # A controlled tab selector preserves the last active detail view across
                # sidebar navigation, unlike transient st.tabs in a conditional page.
                if hasattr(st,'segmented_control'):
                    active=st.segmented_control('Object details',view_options,key='meta_view',
                                 on_change=_meta_remember,args=('meta_view',)) or 'Columns'
                else:
                    active=st.selectbox('Object details',view_options,key='meta_view',
                                 on_change=_meta_remember,args=('meta_view',))
                if active=='Columns':
                    if cols:
                        st.dataframe([{'Field':c['column_name'],'Type':c['sql_type']}
                                      for c in cols],hide_index=True,use_container_width=True)
                    else:
                        st.info('Kolom output Stored Procedure tidak tersedia langsung dari sys.columns.')
                elif active=='SQL Definition':
                    if obj.get('sql_definition'):
                        st.code(obj['sql_definition'],language='sql',line_numbers=True)
                    else:
                        st.info('Tidak ada SQL module definition pada metadata snapshot.')
                elif active=='Recursive Lineage':
                    if not fresh:
                        st.error('Lineage snapshot belum sinkron dengan metadata. Jalankan refresh lineage.')
                    else:
                        _meta_saved_widget('meta_dir','Upstream',['Upstream','Downstream'])
                        direction=st.selectbox('Direction',['Upstream','Downstream'],key='meta_dir',
                                            on_change=_meta_remember,args=('meta_dir',))
                        _meta_saved_widget('meta_hops',3)
                        hop=st.slider('Hops',1,6,3,key='meta_hops',on_change=_meta_remember,args=('meta_hops',))
                        steps,nodes=mod.traverse(index,key,direction,hop)
                        if steps:
                            st.graphviz_chart(mod.dot_graph(index,steps,key).replace('\\n','\n'),use_container_width=True)
                            st.dataframe([{'Hop':r['depth'],'From':_objname(index['objects'][r['from']]),
                                          'Relation':r['relation'],'To':_objname(index['objects'][r['to']])}
                                          for r in steps],use_container_width=True,hide_index=True)
                        else:
                            st.info('Tidak ada lineage yang ter-resolve pada arah ini.')
                elif active=='Field Finder':
                    _meta_saved_widget('meta_field','')
                    field=st.text_input('Field name',placeholder='Masukkan nama field',key='meta_field',
                                     on_change=_meta_remember,args=('meta_field',))
                    candidates=mod.field_candidates(data,index,field,logical_server=logical,database=database)
                    local_hits=[r for r in candidates if r['Object']==_objname(obj)]
                    if local_hits:
                        st.info('Dalam objek terpilih: '+', '.join(
                            f"{r['Column']} [{r['Status']}]" for r in local_hits[:5]))
                    if candidates:
                        st.dataframe([{k:v for k,v in r.items() if k!='ObjectKey'}
                                      for r in candidates],hide_index=True,use_container_width=True)
                        feedback_options=[r for r in candidates if r['Status']!='NAME_MATCH'
                                          and r['Status']!='REFERENCE_KEY_REVIEW']
                        if feedback_options:
                            with st.expander('PIC Alias Feedback',expanded=False):
                                ids=list(range(len(feedback_options)))
                                _meta_saved_widget('meta_alias_choice',0,ids)
                                choice=st.selectbox('Pilih kandidat untuk ditinjau',ids,
                                  format_func=lambda i: f"{field} → {feedback_options[i]['Column']} @ {feedback_options[i]['Object']}",
                                  key='meta_alias_choice',on_change=_meta_remember,args=('meta_alias_choice',))
                                selected=feedback_options[choice]
                                with st.form('meta_alias_decision_form'):
                                    decision=st.selectbox('Keputusan',['APPROVED','REJECTED'])
                                    reviewer=st.text_input('PIC reviewer')
                                    reason=st.text_area('Alasan verifikasi (wajib)')
                                    submit=st.form_submit_button('Simpan feedback')
                                if submit:
                                    try:
                                        record_alias_decision(selected['Domain'] if selected['Domain']!='Unspecified' else 'GENERAL',
                                             selected['ObjectKey'],field,selected['Column'],decision,reviewer,reason)
                                        _refresh_discovery_if_available(data,index)
                                        st.success('Keputusan tersimpan pada shared Alias Registry.')
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                    elif field.strip():
                        st.info('Belum ada suggestion. PIC dapat menambahkan koreksi langsung di bawah.')
                    if field.strip() and cols:
                        with st.expander('Tidak muncul di suggestion? Koreksi manual',expanded=False):
                            st.caption('Pilih kolom asli dari objek yang sedang dibuka. Tidak perlu menunggu engine mengenal namanya.')
                            with st.form('metadata_manual_correction'):
                                colname=st.selectbox('Kolom SQL aktual',[c['column_name'] for c in cols])
                                reviewer=st.text_input('Reviewer / PIC')
                                evidence=st.text_area('Alasan dan bukti kesetaraan (wajib)')
                                accepted=st.checkbox('Saya sudah memverifikasi arti bisnisnya untuk objek ini')
                                saved=st.form_submit_button('Simpan koreksi')
                            if saved:
                                if not accepted:
                                    st.error('Konfirmasi verifikasi PIC diperlukan.')
                                else:
                                    try:
                                        domain=mod.infer_domain(obj) or 'GENERAL'
                                        record_missing_field_correction(domain,key,field,colname,
                                                'MISSING_OR_NOT_SUGGESTED',reviewer,evidence,cols)
                                        _refresh_discovery_if_available(data,index)
                                        st.success('Koreksi tersimpan dan tersedia pada shared alias registry.')
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))


def page_dashboard(data, fresh, run):
    title_line("Workspace", "Kelola pencarian sumber data dan hasil review dari satu tempat.")
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        with st.container(border=True):
            st.subheader("New Discovery")
            st.caption("Mulai dari dokumen kebutuhan data.")
            st.button("Upload Requirement", key="dashboard_new", type="primary",
                      on_click=go, args=(PAGES[0],), use_container_width=True)
    with col2:
        with st.container(border=True):
            st.subheader("Explore Sources")
            st.caption("Cari metadata dan telusuri lineage langsung.")
            st.button("Open Metadata Explorer", key="dashboard_explore",
                      on_click=go, args=(PAGES[3],), use_container_width=True)
    with st.container(border=True, key="ui_recent_reviews_card"):
        st.subheader("Recent Reviews")
        items = list_reviews()
        if not items:
            st.info("Belum ada mapping yang ditinjau. Mulai pencarian untuk membuat review pertama.")
            return
        rows = []
        for item in items[:8]:
            rows.append({
                "Date": item.get("saved_at", ""),
                "Candidate Source": item.get("candidate_fqn", ""),
                "Reviewer": item.get("actor", ""),
                "Status": item.get("status", ""),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.button("Open Mapping History", key="dashboard_history",
                  on_click=go, args=(PAGES[2],))


def page_settings(data, fresh):
    title_line("Settings", "Atur pencarian dan business vocabulary.")
    with st.container(key="ui_settings_columns"):
        configuration_panel, vocabulary_panel = st.columns([.82, 1.18], gap="medium")
        with configuration_panel:
            with st.container(border=True, key="ui_search_configuration_card"):
                st.markdown("#### Search Configuration")
                st.info("Default search: **ALL_REGISTERED_ALLOWED**. PIC tidak wajib memilih database secara manual.")
                saved=int(get_setting("max_candidates",12))
                count=st.selectbox("Maximum candidates shown",[5,8,12,20],index=[5,8,12,20].index(saved) if saved in [5,8,12,20] else 2)
                if st.button("Save Preferences"):
                    set_setting("max_candidates",count)
                    st.success("Preferences saved to persistent app SQLite.")
        with vocabulary_panel:
            with st.container(border=True, key="ui_vocabulary_card"):
                st.markdown('#### Business Vocabulary')
                st.caption('Kelola istilah dan singkatan yang digunakan untuk menghasilkan saran alias. Perubahan perlu persetujuan PIC/administrator.')
                with st.form('term_rule_form'):
                    d=st.selectbox('Scope istilah', ['*'] + list(DOMAIN_RULES),
                                   format_func=lambda x: 'Global — hati-hati terhadap istilah ambigu' if x=='*' else f'Domain: {x}')
                    left,right=st.columns(2)
                    variant=left.text_input('Singkatan/variasi',placeholder='numb')
                    canonical=right.text_input('Istilah standar',placeholder='number')
                    who=st.text_input('Reviewer / PIC',key='term_reviewer')
                    why=st.text_area('Alasan/definisi bisnis',key='term_notes')
                    saved_rule=st.form_submit_button('Simpan istilah')
                if saved_rule:
                    try:
                        record_term_rule(d,variant,canonical,who,why)
                        st.success('Istilah disimpan di SQLite dan digunakan pada Analyze berikutnya.')
                    except ValueError as exc:
                        st.error(str(exc))
                terms_saved=list_term_rules()
                if terms_saved:
                    with st.expander(f'Vocabulary rules tersimpan ({len(terms_saved)})'):
                        st.dataframe(terms_saved,hide_index=True,use_container_width=True)
                decisions_saved=list_alias_decisions()
                if decisions_saved:
                    with st.expander(f'PIC alias decisions tersimpan ({len(decisions_saved)})'):
                        st.dataframe(decisions_saved,hide_index=True,use_container_width=True)
                if decisions_saved:
                    with st.expander('Revisi keputusan alias sebelumnya'):
                        options_dec=list(range(len(decisions_saved)))
                        ix=st.selectbox('Pilih keputusan untuk diperbarui',options_dec,
                             format_func=lambda k: f"{decisions_saved[k]['domain']} · {decisions_saved[k]['requested_norm']} → {decisions_saved[k]['actual_norm']} [{decisions_saved[k]['decision']}]")
                        row_dec=decisions_saved[ix]
                        with st.form('revise_existing_alias'):
                            new_dec=st.selectbox('Keputusan baru',['APPROVED','REJECTED'])
                            new_reviewer=st.text_input('PIC reviewer', key='override_reviewer')
                            new_notes=st.text_area('Alasan revisi (wajib)', key='override_reason')
                            save_override=st.form_submit_button('Simpan revisi')
                        if save_override:
                            try:
                                record_alias_decision(row_dec['domain'],row_dec['object_key'],
                                  row_dec['requested_norm'],row_dec['actual_norm'],new_dec,new_reviewer,new_notes)
                                st.success('Keputusan diperbarui; audit sebelumnya tetap disimpan.')
                                st.rerun()
                            except ValueError as exc: st.error(str(exc))
                    with st.expander('Audit trail keputusan alias'):
                        st.dataframe(list_alias_audit(), hide_index=True, use_container_width=True)
        with configuration_panel:
            with st.container(border=True, key="ui_diagnostics_card"):
                with st.expander("Advanced Diagnostics", expanded=False):
                    st.caption("Untuk administrator. Status metadata dan versi logic tidak memverifikasi hasil mapping bisnis.")
                    rows = []
                    for d in sorted({o["database_name"] for o in data["objects"]}):
                        objs = [o for o in data["objects"] if o["database_name"] == d]
                        rows.append({"Logical Server":objs[0]["logical_server"],
                                     "Database":d, "Indexed Objects":len(objs)})
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                    st.write("Lineage status:", "Current" if fresh else "Refresh required")
                    st.code(r".\.venv\Scripts\python.exe .\07_build_metadata_catalog.py" "\n" +
                            r".\.venv\Scripts\python.exe .\09_build_lineage_edges.py",
                            language="powershell")
                    st.code(f"Metadata catalog: {modpath()}\nApplication history: {HISTORY_DB}", language="text")
                    st.caption(f"Engine version: {VERSION} · Rule version: {RULE_VERSION}")
                    semantic=semantic_status()
                    st.caption('Semantic retrieval: '+('Local model ready' if semantic['ready'] else f"Not active ({semantic['reason']})"))
                    st.warning("Pastikan autentikasi, hak akses, backup, dan konfigurasi service account disiapkan sebelum deployment production.")


def modpath():
    return Path(os.getenv("OJT2_CATALOG_PATH",str(Path.home()/"OJT2_Discovery_Data"/"metadata_catalog.sqlite"))).expanduser().resolve()


def main():
    st.set_page_config(page_title="Smart Data Source Discovery",page_icon="🔎",
                       layout="wide",initial_sidebar_state="expanded")
    inject_style()
    _nav_start()
    try:
        mod=stage3_helpers()
        catalog=modpath()
        if not catalog.is_file():
            st.error(f"Metadata catalog not found: {catalog}")
            st.code(r".\.venv\Scripts\python.exe .\07_build_metadata_catalog.py" "\n" +
                    r".\.venv\Scripts\python.exe .\09_build_lineage_edges.py")
            st.stop()
        data=load_catalog(str(HERE),str(catalog),catalog.stat().st_mtime_ns)
        index=mod.make_index(data)
    except Exception as exc:
        st.error(f"Gagal membaca Metadata Catalog: {exc}")
        st.stop()
    metadata_fresh=int(data["metadata_run"]["run_id"])==int(data["lineage_run"]["source_run_id"])
    _sidebar(data,metadata_fresh)
    page=st.session_state["nav_page"]
    if page==PAGES[0]: page_upload(data,index)
    elif page==PAGES[1]: page_results(data,index,mod,metadata_fresh,data["metadata_run"]["run_id"])
    elif page==PAGES[2]: page_history()
    elif page==PAGES[3]: page_metadata(data,index,mod,metadata_fresh)
    elif page==PAGES[4]: page_dashboard(data,metadata_fresh,data["metadata_run"])
    elif page==PAGES[5]: page_settings(data,metadata_fresh)


if __name__=="__main__": main()
