"""Conservative, configurable field-term normalization and persistent PIC feedback.

Rules/proposals are metadata-name evidence, never proof of semantic equivalence.
No SQL Server connections. Only reads/writes the isolated application SQLite DB.
"""
from __future__ import annotations
from datetime import datetime, timezone
import unicodedata
from contextlib import contextmanager, closing
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

from ojt2_discovery_core import norm, HISTORY_DB
from ojt2_requirement_semantics import (decompose_requirement, contextual_candidates)
from ojt2_field_language import (BUILTIN_TERMS, identifier_tokens,
                                 concept_alias, attribute_conflicts)

# Safe starter vocabulary, not a complete Indonesian/English business dictionary.
# All canonical matches are still proposals for PIC validation.
BASE_TERMS = {
    # Format/abbreviation normalizer (generic tokens, NOT hard-coded column pairs)
    "nomor":"number", "nomer":"number", "numb":"number", "num":"number",
    "nbr":"number", "no":"number", "number":"number", "nomer":"number",
    "nama":"name", "name":"name", "nm":"name",
    "jumlah":"quantity", "kuantitas":"quantity", "qty":"quantity", "quantity":"quantity",
    "tgl":"date", "tanggal":"date", "date":"date",
    "reg":"region", "regional":"region", "region":"region",
    # Corporate bilingual vocabulary. Editable terms can override these via Settings.
    "project":"project", "projek":"project", "proyek":"project", "projects":"project",
    "provinsi":"province", "propinsi":"province", "province":"province", "provinces":"province",
    "kabupaten":"regency", "regency":"regency", "kab":"regency",
    "kota":"city", "city":"city", "kecamatan":"district", "district":"district",
    "kelurahan":"subdistrict", "subdistrict":"subdistrict", "desa":"village", "village":"village",
    "negara":"country", "country":"country", "wilayah":"region", "daerah":"region",
    "tipe":"type", "type":"type", "jenis":"type",
    "segmen":"segment", "segment":"segment",
    "jarak":"distance", "distance":"distance", "dist":"distance",
    "kategori":"category", "category":"category", "cat":"category",
    "pelanggan":"customer", "customer":"customer", "cust":"customer",
    "lokasi":"location", "location":"location", "loc":"location",
    "kode":"code", "code":"code", "identifier":"id",
    "persetujuan":"approval", "approve":"approval", "approved":"approval", "approval":"approval",
    "status":"status", "state":"status",
    "waktu":"time", "time":"time", "periode":"period", "period":"period",
    "area":"area", "bulan":"month", "month":"month", "tahun":"year", "year":"year",
    "nominal":"amount", "nilai":"amount", "amount":"amount",
    "biaya":"cost", "cost":"cost", "harga":"price", "price":"price",
    "tinggi":"height", "height":"height", "panjang":"length", "length":"length",
    "total":"total", "awal":"initial", "initial":"initial", "akhir":"final", "final":"final",
    "tanggal":"date", "mulai":"start", "start":"start", "selesai":"finish", "finish":"finish",
    "aktif":"active", "active":"active", "nonaktif":"inactive", "inactive":"inactive",
    "sumber":"source", "source":"source", "asal":"origin", "origin":"origin",
    "tujuan":"destination", "destination":"destination", "dest":"destination",
    "supplier":"supplier", "pemasok":"supplier",
    "vendor":"vendor", "mitra":"partner", "partner":"partner",
    "pegawai":"employee", "karyawan":"employee", "employee":"employee", "emp":"employee",
    "departemen":"department", "department":"department", "dept":"department",
    "direktorat":"directorate", "directorate":"directorate", "director":"director",
    "permintaan":"request", "request":"request", "req":"request",
    "pesanan":"order", "order":"order", "invoice":"invoice", "faktur":"invoice",
    "tanggal":"date", "tahun":"year", "jumlah":"quantity",
    # Explicit measurement units (do NOT silently convert between units)
    "kilometer":"km", "kilometre":"km", "kilometers":"km", "kilometres":"km", "km":"km",
    "meter":"m", "metre":"m", "meters":"m", "metres":"m", "m":"m",
    "hari":"day", "days":"day", "day":"day",
    "jam":"hour", "hours":"hour", "hour":"hour",
}
BASE_TERMS = {**BUILTIN_TERMS, **BASE_TERMS}
# 'ID', 'Code', and 'Key' cannot be silently interpreted as a label/value.
IDENTIFIER_TOKENS = {"id", "key", "code"}
MEASUREMENT_UNITS = {"km": "kilometer", "m": "meter"}
MEASUREMENT_CONCEPTS = {"distance", "length", "radius", "height"}
# Time qualifiers may appear in existing SQL output columns, e.g. LeadtimeDays.
# Their presence is a candidate-generation clue, NEVER permission to infer a unit
# or a formula from a requirement that omitted one.
TIME_UNIT_TOKENS = {"day", "hour", "minute", "week", "month", "year"}
TIME_MEASURE_CONCEPTS = {"leadtime", "duration", "elapsed", "turnaround", "age", "cycle"}
# A shortened word followed only by a generic qualifier (Name/Status/etc.)
# is weak evidence: show in Top-N but do not auto-promote to primary mapping.
WEAK_ABBREVIATION_ANCHORS = {'name', 'type', 'status', 'number', 'date', 'value',
                             'code', 'id', 'key', 'category'}

# Generic business qualifiers: a requested concept may refer to an attribute of
# that concept, but the two are NOT interchangeable until explicitly validated.
# Examples are illustrative, not special cases: Resign -> ResignStatus,
# Contract -> ContractDate, Site -> SiteName, Project -> ProjectType.
# ID/Key/Code stay excluded and retain their safer reference-key handling.
BUSINESS_ATTRIBUTE_QUALIFIERS = frozenset({
    'status', 'date', 'time', 'name', 'type', 'category', 'reason',
    'flag', 'indicator', 'description', 'value', 'amount', 'quantity',
    'total', 'rate', 'percentage', 'period', 'initial', 'final',
    'start', 'finish', 'active', 'inactive'
}) - IDENTIFIER_TOKENS


# Generic attribute projection: the user may specify a *short* business
# attribute (City/Category) while the SQL name qualifies its subject
# (WarehouseCity/MaterialCategory). These are hypotheses, NOT aliases.
# Organizational actor attributes use the existing actor-aware pathway to
# preserve requester/creator/reviewer ambiguity.
ACTOR_OWNED_ATTRIBUTES = frozenset({
    'employee','person','requester','requestor','reviewer','approver',
    'department','division','directorate','jobtitle','position',
})
CONTRADICTORY_QUALIFIERS = (
    frozenset({'start','end'}), frozenset({'initial','final'}),
    frozenset({'origin','destination'}),
)


def _qualified_attribute_candidate(req_set: set[str], col_set: set[str],
                                   sql_type: str = '') -> dict | None:
    """Propose a qualified SQL attribute without conflating identifiers/grain.

    Works on token sets in *any* source, without dataset-specific field names.
    Requires all requested tokens in the candidate and at most two additional
    non-actor qualifiers. A unique candidate can become primary PIC-review;
    multiple peers still require an explicit choice.
    """
    if not req_set or req_set >= col_set or not req_set.issubset(col_set):
        return None
    added = col_set-req_set
    if len(added) > 2 or (added & IDENTIFIER_TOKENS):
        return None
    if req_set & ACTOR_OWNED_ATTRIBUTES or added & {
        'createdby','reviewedby','updatedby','approvedby','requestedby',
        'creator','reviewer','approver','requester','requestor','employee',
    }:
        return None
    if any(req_set & pair and added & pair for pair in CONTRADICTORY_QUALIFIERS):
        return None
    if (req_set & IDENTIFIER_TOKENS):
        # GDL ID vs GDL Detail ID is a *different grain* until PIC confirms.
        if not (req_set-IDENTIFIER_TOKENS):
            return None
        return {
            'status':'IDENTIFIER_GRAIN_REVIEW', 'rank_score':.79,
            'factor':0.0,
            'evidence':f'ID/key shares subject {sorted(req_set-IDENTIFIER_TOKENS)} but SQL adds {sorted(added)}; header/detail or grain may differ. Validate identifier semantics and uniqueness with PIC. No auto JOIN or coverage.'}
    if (col_set & IDENTIFIER_TOKENS) or req_set <= {'date','name','number','id','key','code'}:
        return None
    if req_set & {'date','time','period'} and added & {'review','approve','created','updated','end','start'}:
        return None  # workflow event needs independent event semantics
    # No lexical names alone can prove that the qualifier is the user intent.
    return {
        'status':'QUALIFIED_ATTRIBUTE_REVIEW', 'rank_score':.83 if len(added)==1 else .77,
        'factor':0.0,
        'evidence':f'Requested attribute {sorted(req_set)} occurs within more specific SQL attribute; extra context {sorted(added)} requires PIC confirmation. This is not verified field coverage.'}


@lru_cache(maxsize=8192)
def _field_facets(value: str) -> tuple[frozenset[str], frozenset[str]]:
    """Attribute kind and workflow family from the label, preserving notes separately."""
    from ojt2_requirement_semantics import EVENT_FAMILIES, EVENT_CANONICAL
    from ojt2_semantic_rerank import words
    label=decompose_requirement(value).label
    tokens=set(split_tokens(label))
    raw=words(label)
    kinds=set()
    if tokens & {'id','key','code','number'}:
        kinds.add('identifier')
    if 'status' in tokens:
        kinds.add('status')
    if tokens & {'date','datetime','timestamp'}:
        kinds.add('date')
    if 'by' in raw or any(token.endswith('by') for token in raw):
        kinds.add('actor')
    events={EVENT_CANONICAL.get(word,word) for word in raw if word in EVENT_FAMILIES}
    return frozenset(kinds),frozenset(EVENT_FAMILIES.get(event,event) for event in events)


def _candidate_facet_conflict(requested: str, actual: str) -> str | None:
    """Reject incompatible attributes/events, without source- or field-pair rules.

    Related events within a family remain proposals (create/request, review/
    approval), never assertions of equivalence. Unknown events stay unresolved
    by this guard instead of being assigned a fabricated family.
    """
    query,query_events=_field_facets(requested)
    candidate,candidate_events=_field_facets(actual)
    if query and candidate and not query & candidate:
        return 'ATTRIBUTE_KIND_CONFLICT'
    if ('date' in query and 'date' in candidate and query_events and candidate_events
            and not query_events & candidate_events):
        return 'WORKFLOW_EVENT_FAMILY_CONFLICT'
    return None


def _credible_semantic_hypothesis(item: dict, requested: str) -> bool:
    """Quality gate for semantic-only retrieval, not model calibration.

    Prevent unrelated high-ish cosine from appearing just because we requested
    Top-N. Keep compatible actor relationships and start/end direction evidence,
    while excluding clear contradictions. All accepted hits remain unverified.
    """
    from ojt2_semantic_rerank import words, _role, _direction
    if _candidate_facet_conflict(requested,item['actual']):
        return False
    flags=set(item.get('semantic_risk_flags') or ())
    if flags & {'START_END_CONTRADICTION','ACTOR_ROLE_CONFLICT',
                'PERSON_NAME_NOT_ACTOR','TEMPORAL_TYPE_REVIEW',
                'ATTRIBUTE_KIND_CONFLICT','OPPOSITE_QUALIFIER','GEOGRAPHIC_LEVEL_CONFLICT'}:
        return False
    a=words(requested)
    b=words(item['actual'])
    role_a,role_b=_role(a),_role(b)
    direction_a,direction_b=_direction(a),_direction(b)
    if role_a and role_b and (role_a==role_b or
                            {role_a,role_b}=={'initiator','creator'}):
        return True
    if direction_a and direction_b and direction_a==direction_b:
        return True
    # Without role/direction corroboration demand a stronger semantic signal
    # AND a shared meaningful subject token, or a very high adjusted signal.
    shared=(a & b)-{'by','name','id','key','code','date','status','number',
                    'time','type','period'}
    score=float(item.get('rank_score',0))
    # Real model output carries label-only similarity separately from the
    # context-rich score. A shared English token is NOT required for bilingual
    # retrieval. Legacy/stub records without that evidence retain the old gate.
    label_score=item.get('field_similarity')
    if label_score is not None:
        return bool(float(label_score) >= .60 and score >= .60)
    return bool((shared and score>=.72) or score>=.84)



def _consonant_abbreviation(short: str, expanded: str) -> bool:
    """An unverified compressed-word hypothesis (e.g. WH -> Warehouse).

    Character patterns cannot prove business meaning: require an independent
    matching semantic anchor in ``field_suggestions`` and always request PIC
    validation. This is NOT a hard-coded WH/Warehouse alias.
    """
    if not (2 <= len(short) <= 5 and len(expanded) >= 6):
        return False
    if short[0] != expanded[0] or len(short) * 2 > len(expanded):
        return False
    if short in IDENTIFIER_TOKENS or expanded in IDENTIFIER_TOKENS:
        return False
    # Compare ordered consonants: WH is a *possible* contraction of WaReHouse,
    # but also potentially of other words; no equivalence is asserted here.
    skeleton = ''.join(ch for ch in expanded if ch not in 'aeiou')
    if len(skeleton) < len(short):
        return False
    it = iter(skeleton)
    return all(any(c == letter for c in it) for letter in short)


def _inflected_base(token: str) -> str:
    """Conservative *proposal-only* inflection key (Saving vs Savings).

    This does NOT rewrite SQL names or assert business identity. Grammar is
    intentionally simple and only used to surface PIC-review suggestions.
    """
    if len(token) >= 7 and token.endswith("ies") and not token.endswith("eies"):
        return token[:-3] + "y"
    if len(token) >= 6 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _inflected_tokens(value: str, terms: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(_inflected_base(t) for t in split_tokens(value, terms)))
GENERAL_ENDINGS = tuple(sorted({
    "number", "nomor", "numb", "quantity", "regional", "region", "name",
    "nama", "date", "tanggal", "qty", "code", "num", "nbr", "key", "id", "no",
    "segmen", "segment", "tipe", "type", "jarak", "distance", "km", "kilometer",
    "customer", "location", "status", "approval", "amount", "price", "height", "length", "site", "month", "year", "category", "region", "project", "projek", "proyek", "province", "provinsi", "partner", "department", "city", "regency", "selection", "distance", "period", "date"
}, key=len, reverse=True))


@contextmanager
def _connect(path: Path = HISTORY_DB) -> Iterator[sqlite3.Connection]:
    """Yield an app-SQLite connection and ALWAYS close its file handle.

    sqlite3.Connection's built-in context manager commits/rolls back but does
    not close the connection. This matters for temporary SQLite files on Windows.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=15)) as cn:
        cn.row_factory = sqlite3.Row
        cn.executescript('''
        CREATE TABLE IF NOT EXISTS field_alias_decisions (
          domain TEXT NOT NULL,
          object_key TEXT NOT NULL,
          requested_norm TEXT NOT NULL,
          actual_norm TEXT NOT NULL,
          decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
          reviewed_by TEXT NOT NULL,
          notes TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (domain,object_key,requested_norm,actual_norm)
        );
        CREATE TABLE IF NOT EXISTS field_alias_decision_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          domain TEXT NOT NULL, object_key TEXT NOT NULL,
          requested_norm TEXT NOT NULL, actual_norm TEXT NOT NULL,
          decision TEXT NOT NULL, reviewed_by TEXT NOT NULL,
          notes TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS missing_field_corrections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          domain TEXT NOT NULL, object_key TEXT NOT NULL,
          requested TEXT NOT NULL, actual TEXT NOT NULL,
          previous_status TEXT NOT NULL, reviewed_by TEXT NOT NULL,
          evidence TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS business_term_rules (
          domain TEXT NOT NULL,
          variant TEXT NOT NULL,
          canonical TEXT NOT NULL,
          reviewed_by TEXT NOT NULL,
          notes TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (domain,variant)
        );
        ''')
        cn.commit()
        # Preserve commit / rollback behavior of existing call sites.
        with cn:
            yield cn


def get_alias_decisions(domain: str | None, path: Path = HISTORY_DB) -> dict[tuple[str,str,str],str]:
    domain = domain or 'GENERAL'
    with _connect(path) as cn:
        # GENERAL is an object-specific fallback, never a universal synonym.
        # Prefer a decision made in the current domain if both exist.
        items = cn.execute('''SELECT object_key,requested_norm,actual_norm,decision
          FROM field_alias_decisions WHERE domain IN (?, 'GENERAL')
          ORDER BY CASE WHEN domain=? THEN 0 ELSE 1 END''', (domain,domain)).fetchall()
    mapping={}
    for r in items:
        mapping.setdefault((r['object_key'],r['requested_norm'],r['actual_norm']),r['decision'])
    return mapping


def record_alias_decision(domain: str, object_key: str, requested: str, actual: str,
                          decision: str, reviewer: str, notes: str, path: Path = HISTORY_DB) -> None:
    """Explicit, auditable PIC decision. Scoped to domain and physical object."""
    decision=decision.upper()
    if decision not in {'APPROVED','REJECTED'}:
        raise ValueError('Decision must be APPROVED or REJECTED')
    if not (domain and object_key and norm(requested) and norm(actual)):
        raise ValueError('Domain, object, requested and actual fields are mandatory')
    if not reviewer.strip() or not notes.strip():
        raise ValueError('Reviewer and reason are required')
    a,b=norm(requested),norm(actual)
    if a==b:
        raise ValueError('Exact normalized matches do not require alias approval')
    if _identifier_conflict(requested,actual):
        raise ValueError('Identifier-vs-value mismatch needs separate lookup verification, not alias approval')
    with _connect(path) as cn:
        cn.execute('''INSERT INTO field_alias_decisions VALUES (?,?,?,?,?,?,?,?)
          ON CONFLICT(domain,object_key,requested_norm,actual_norm) DO UPDATE SET
          decision=excluded.decision, reviewed_by=excluded.reviewed_by,
          notes=excluded.notes, updated_at=excluded.updated_at''',
          (domain,object_key,a,b,decision,reviewer.strip(),notes.strip(),
           datetime.now(timezone.utc).isoformat(timespec='seconds')))
        cn.execute('''INSERT INTO field_alias_decision_audit
          (domain,object_key,requested_norm,actual_norm,decision,reviewed_by,notes,updated_at)
          SELECT domain,object_key,requested_norm,actual_norm,decision,reviewed_by,notes,updated_at
          FROM field_alias_decisions WHERE domain=? AND object_key=? AND requested_norm=? AND actual_norm=?''',
          (domain,object_key,a,b))


def record_missing_field_correction(domain: str, object_key: str, requested: str,
                                    actual: str, previous_status: str,
                                    reviewer: str, evidence: str,
                                    available_columns: list[dict], path: Path = HISTORY_DB) -> None:
    """PIC can correct a missed mapping even if the matcher made NO proposal.

    The column must exist in this exact metadata object; all decisions are
    scoped to the object and audited. Does not fine-tune a neural model.
    """
    actual_col=next((c['column_name'] for c in available_columns
                     if norm(c['column_name'])==norm(actual)), None)
    if not actual_col:
        raise ValueError('Selected column is not present in this metadata object. Refresh catalog first.')
    if not previous_status or previous_status=='NAME_MATCH':
        raise ValueError('Manual correction requires an unresolved/review field.')
    record_alias_decision(domain or 'GENERAL', object_key, requested, actual_col,
                          'APPROVED', reviewer, evidence, path=path)
    with _connect(path) as cn:
        cn.execute('''INSERT INTO missing_field_corrections
            (domain,object_key,requested,actual,previous_status,reviewed_by,evidence,created_at)
            VALUES (?,?,?,?,?,?,?,?)''',
            (domain or 'GENERAL',object_key,requested,actual_col,previous_status,
             reviewer.strip(),evidence.strip(),datetime.now(timezone.utc).isoformat(timespec='seconds')))


def list_missing_field_corrections(path: Path = HISTORY_DB) -> list[dict]:
    with _connect(path) as cn:
        return [dict(r) for r in cn.execute('''SELECT * FROM missing_field_corrections
              ORDER BY id DESC''').fetchall()]


def list_alias_decisions(path: Path=HISTORY_DB) -> list[dict]:
    with _connect(path) as cn:
        return [dict(r) for r in cn.execute('''SELECT * FROM field_alias_decisions
             ORDER BY updated_at DESC''').fetchall()]


def list_alias_audit(path: Path=HISTORY_DB) -> list[dict]:
    with _connect(path) as cn:
        return [dict(r) for r in cn.execute('''SELECT * FROM field_alias_decision_audit ORDER BY id DESC''').fetchall()]


def record_term_rule(domain: str, variant: str, canonical: str, reviewer: str,
                     notes: str, path: Path=HISTORY_DB) -> None:
    domain=(domain or '*').strip().upper()
    variant,canonical=norm(variant),norm(canonical)
    if not variant or not canonical or variant==canonical:
        raise ValueError('Enter two distinct nonblank terms')
    if not (reviewer.strip() and notes.strip()):
        raise ValueError('Reviewer and reason are required')
    if len(variant)<2 or len(canonical)<2:
        raise ValueError('Abbreviation/term too short (minimum 2 characters)')
    if variant in IDENTIFIER_TOKENS or canonical in IDENTIFIER_TOKENS:
        raise ValueError('ID/Key/Code cannot be rewritten via term dictionary')
    with _connect(path) as cn:
        cn.execute('''INSERT INTO business_term_rules VALUES (?,?,?,?,?,?)
          ON CONFLICT(domain,variant) DO UPDATE SET canonical=excluded.canonical,
          reviewed_by=excluded.reviewed_by,notes=excluded.notes,updated_at=excluded.updated_at''',
          (domain,variant,canonical,reviewer.strip(),notes.strip(),
           datetime.now(timezone.utc).isoformat(timespec='seconds')))


def get_term_rules(domain: str | None=None,path: Path=HISTORY_DB) -> dict[str,str]:
    terms=dict(BASE_TERMS)
    with _connect(path) as cn:
        for r in cn.execute('SELECT variant,canonical FROM business_term_rules WHERE domain=?', ('*',)):
            terms[r['variant']]=r['canonical']
        if domain:
            for r in cn.execute('SELECT variant,canonical FROM business_term_rules WHERE domain=?',(domain.upper(),)):
                terms[r['variant']]=r['canonical']
    return terms


def list_term_rules(path: Path=HISTORY_DB) -> list[dict]:
    with _connect(path) as cn:
        return [dict(r) for r in cn.execute('''SELECT * FROM business_term_rules ORDER BY updated_at DESC''').fetchall()]


def _canonical_token(token: str, terms: dict[str, str]) -> str:
    """Map known bilingual tokens; extend safely to a UNIQUE typo variant.

    A fuzzy correction is only accepted when matching variants agree on a single
    canonical meaning. Never infer arbitrary unseen translations from this.
    """
    if token in terms:
        return terms[token]
    if len(token) < 5 or token in IDENTIFIER_TOKENS or token in MEASUREMENT_UNITS:
        return token
    possible=[]
    for variant, canonical in terms.items():
        if len(variant)<5 or variant[:2]!=token[:2] or abs(len(variant)-len(token))>2:
            continue
        similarity=SequenceMatcher(None, token, variant).ratio()
        if similarity>=0.84:
            possible.append((similarity,canonical))
    if not possible:
        return token
    high=max(p[0] for p in possible)
    choices={canonical for score,canonical in possible if score>=max(0.84,high-0.025)}
    return next(iter(choices)) if len(choices)==1 else token


def split_tokens(value: str, term_rules: dict[str,str] | None = None) -> tuple[str, ...]:
    rules=BASE_TERMS if term_rules is None else term_rules
    return _split_tokens_cached(str(value or ''),tuple(sorted(rules.items())))


@lru_cache(maxsize=16384)
def _split_tokens_cached(value: str, signature: tuple) -> tuple[str, ...]:
    """Conservative CamelCase, acronym and common-suffix segmentation.

    Examples: SONumb -> SO Numb, Sonumber -> SO Number,
              SiteName -> Site Name, Nama Site -> Nama Site.
    """
    rules=dict(signature)
    fragments=identifier_tokens(value, {**BASE_TERMS, **rules}, GENERAL_ENDINGS)
    return tuple(sorted(_canonical_token(p,rules) for p in fragments))


def _identifier_conflict(left: str, right: str) -> bool:
    # Exact ID/Key/Code presence mismatch disqualifies value equivalence.
    a=set(split_tokens(left))&IDENTIFIER_TOKENS
    b=set(split_tokens(right))&IDENTIFIER_TOKENS
    return a!=b


def _legacy_propose_field_match(columns: list[dict], requested: str,
                        domain: str|None=None, object_key: str|None=None,
                        decisions: dict[tuple[str,str,str],str]|None=None,
                        terms: dict[str,str]|None=None) -> dict | None:
    """Returns a proposed candidate, or None. Never asserts validated equivalence.

    Priority: explicit PIC approval > conservative lexical normalization
    > unique high-quality typo suggestion. Rejected pairs are suppressed.
    """
    decisions=decisions or {}
    terms=BASE_TERMS if terms is None else terms
    req_norm=norm(requested)
    blocked={act for (obj,req,act),decision in decisions.items()
             if obj==object_key and req==req_norm and decision=='REJECTED'}
    def possible(c):
        actual=c['column_name']
        return (norm(actual) not in blocked and not _identifier_conflict(requested,actual)
                and not _candidate_facet_conflict(requested,actual))
    valid=[c for c in columns if possible(c) and norm(c['column_name'])!=req_norm]
    approved=[c for c in valid if decisions.get((object_key,req_norm,norm(c['column_name'])))=='APPROVED']
    if len(approved)==1:
        return {'actual':approved[0]['column_name'],'status':'REGISTERED_ALIAS_REVIEW',
                'factor':0.85,'evidence':f'PIC-approved alias registry for domain {domain}, source {object_key}. Business meaning still needs review per request.'}
    wanted=split_tokens(requested,terms)
    if len(wanted)>=2 and any(t not in {'number','name','quantity','date','region'} for t in wanted):
        matches=[c for c in valid if split_tokens(c['column_name'],terms)==wanted]
        if len(matches)==1:
            col=matches[0]
            # Distinguish translations vs abbreviations, always proposed.
            raw_a,raw_b=split_tokens(requested,{}),split_tokens(col['column_name'],{})
            number_variants={'nomor','nomer','numb','num','nbr','no','number'}
            number_change=(any(x in number_variants for x in raw_a+raw_b) and raw_a!=raw_b)
            return {'actual':col['column_name'],
                    'status':'ABBREVIATION_ALIAS_REVIEW' if number_change else 'BUSINESS_ALIAS_REVIEW',
                    'factor':0.60 if number_change else 0.62,
                    'evidence':f'Canonical token normalization: {requested} -> {col["column_name"]} ({wanted}); PIC verification required.'}
    # General inflection matching before fuzzy spelling. e.g. Saving -> Savings.
    # Only suggest when the candidate is unique; several viable plural variants
    # must remain ambiguous rather than silently choosing a winner.
    inflected = _inflected_tokens(requested, terms)
    if inflected:
        matches = [c for c in valid if _inflected_tokens(c['column_name'], terms) == inflected]
        if len(matches) == 1:
            col = matches[0]
            return {
                'actual': col['column_name'], 'status': 'BUSINESS_ALIAS_REVIEW',
                'factor': 0.60,
                'evidence': f'Inflection/plural normalization proposal: {requested} -> {col["column_name"]}; PIC must verify business meaning.'
            }
    # Unit-aware proposal: "Jarak" can point to "DistanceKM", but the requested
    # unit is UNDEFINED. This is NOT semantic equivalence or a conversion.
    # Never guess if there are two competing units (DistanceKM / DistanceM).
    req_units = set(wanted) & MEASUREMENT_UNITS.keys()
    if not req_units and set(wanted) & MEASUREMENT_CONCEPTS:
        options = []
        for c in valid:
            candidate_tokens = set(split_tokens(c['column_name'], terms))
            column_units = candidate_tokens & MEASUREMENT_UNITS.keys()
            if len(column_units) != 1:
                continue
            if candidate_tokens - column_units == set(wanted):
                options.append((c, next(iter(column_units))))
        if len(options) == 1:
            col, unit = options[0]
            return {
                'actual': col['column_name'], 'status': 'UNIT_ALIAS_REVIEW',
                'factor': 0.38,
                'evidence': (
                    f'Business-concept + unit suffix candidate: {requested} -> '
                    f'{col["column_name"]} (unit: {MEASUREMENT_UNITS[unit]}). '
                    'Requirement does not specify a unit; PIC must verify the '
                    'business meaning and expected measurement unit. NOT a validated match.'
                )
            }
        # Two or more units/measurement variants: avoid fuzzy choosing one.
        if len(options) > 1:
            return None
    # Conservative typo candidate only when the best is unique, strong and shares prefix.
    fuzzy=[]
    for c in valid:
        actual=norm(c['column_name'])
        if min(len(req_norm),len(actual)) < 6 or req_norm[:3]!=actual[:3]:
            continue
        ratio=SequenceMatcher(None,req_norm,actual).ratio()
        if ratio>=0.88:
            fuzzy.append((ratio,c))
    fuzzy.sort(key=lambda x:-x[0])
    if fuzzy and (len(fuzzy)==1 or fuzzy[0][0]-fuzzy[1][0]>=0.06):
        col=fuzzy[0][1]
        return {'actual':col['column_name'],'status':'FUZZY_ALIAS_REVIEW','factor':0.35,
                'evidence':f'Typo/name similarity {fuzzy[0][0]:.2f}; NOT semantic proof; PIC review required.'}
    return None


# Stage 4.1.5: GENERIC, EXPLAINABLE CANDIDATE GENERATOR
# These are SEARCH suggestions, never data-equivalence assertions.
# Registry approvals remain scoped to domain + fully-qualified object.
NOISE_TOKENS = {"the", "of", "yang", "untuk", "dari", "dalam", "pada"}


def ordered_field_tokens(value: str, term_rules: dict | None = None) -> tuple[str, ...]:
    """Tokenize like split_tokens while PRESERVING word order for initials.

    Used only to create unverified acronym candidates; lexical word-order
    equivalence is still handled by split_tokens.
    """
    rules=BASE_TERMS if term_rules is None else term_rules
    fragments=identifier_tokens(value, {**BASE_TERMS, **rules}, GENERAL_ENDINGS)
    return tuple(_canonical_token(t,rules) for t in fragments if t not in NOISE_TOKENS)


def field_suggestions(columns: list[dict], requested: str, *,
                      domain: str | None = None, object_key: str | None = None,
                      decisions: dict | None = None, terms: dict | None = None,
                      limit: int = 5, context: str = '',
                      business_context: str = '', source_hint: str = '',
                      include_semantic: bool = True,
                      include_shared_feedback: bool = True,
                      shared_feedback: dict | None = None) -> list[dict]:
    """Rank alternative column hypotheses; status/evidence stays provisional.

    Mechanisms: word reorder, bilingual terms, abbreviation and initials,
    conservative typo correction, unit qualifiers, identifier / value mismatch.
    No query execution, auto-approval, automatic JOIN, or automatic unit conversion.
    """
    terms = dict(BASE_TERMS if terms is None else terms)
    decisions = decisions or {}
    req_norm = norm(requested)
    # Exact metadata name already wins; no need to generate unrelated semantic
    # hypotheses or load the embedding model for this requirement.
    if len([c for c in columns if norm(c.get('column_name','')) == req_norm]) == 1:
        return []
    req_words = tuple(t for t in split_tokens(requested, terms) if t not in NOISE_TOKENS)
    req_raw_words = tuple(t for t in split_tokens(requested, {}) if t not in NOISE_TOKENS)
    req_set = set(req_words)
    req_ids = req_set & IDENTIFIER_TOKENS
    req_units = req_set & MEASUREMENT_UNITS.keys()
    output=[]

    for col in columns:
        actual=col['column_name']
        actual_norm=norm(actual)
        if not actual_norm or (actual_norm==req_norm):
            continue
        decision=decisions.get((object_key,req_norm,actual_norm))
        if decision=='REJECTED':
            continue
        col_words=tuple(t for t in split_tokens(actual,terms) if t not in NOISE_TOKENS)
        col_raw_words=tuple(t for t in split_tokens(actual,{}) if t not in NOISE_TOKENS)
        col_set=set(col_words)
        col_ids=col_set & IDENTIFIER_TOKENS
        col_units=col_set & MEASUREMENT_UNITS.keys()
        common=req_set & col_set
        candidate=None
        score=0.0
        status=None
        rationale=None

        if req_units and col_units and req_units != col_units:
            continue  # explicit incompatible units: not a direct alias
        if decision != 'APPROVED' and attribute_conflicts(req_set, col_set):
            continue
        if decision=='APPROVED' and req_ids==col_ids:
            score=0.99
            status='REGISTERED_ALIAS_REVIEW'
            rationale=f'PIC-approved object-scoped alias; re-check meaning for this requirement.'
        elif req_ids != col_ids:
            # A column key is evidence of a possible lookup, NOT the requested label.
            left=req_set-IDENTIFIER_TOKENS
            right=col_set-IDENTIFIER_TOKENS
            if left and left==right:
                score=0.70
                status='REFERENCE_KEY_REVIEW'
                rationale='Identifier versus business value: candidate lookup key, not a direct alias.'
            elif left and right and left.issubset(right) and (len(left)>=2 or len(left)==1 and len(next(iter(left)))>=4):
                score=0.56
                status='REFERENCE_KEY_REVIEW'
                rationale='Related identifier with extra qualifiers; investigate relationship/lookup, not equivalence.'
            else:
                continue
        elif req_units != col_units:
            # Units in source but unspecified in requirement: possible measure, not verified.
            if not req_units and col_units and req_set==col_set-col_units and req_set & MEASUREMENT_CONCEPTS:
                score=0.74
                status='UNIT_ALIAS_REVIEW'
                rationale=f'Measurement concept matches but SQL unit={", ".join(sorted(col_units))}; PIC must confirm expected unit.'
            else:
                continue
        elif req_set and req_set==col_set:
            variants = {"nomor", "nomer", "numb", "num", "nbr", "no", "number"}
            if set(req_raw_words+col_raw_words)&variants and req_raw_words!=col_raw_words:
                status='ABBREVIATION_ALIAS_REVIEW'; score=0.94
                rationale='Normalized abbreviation variants + word order align.'
            else:
                status='BUSINESS_ALIAS_REVIEW'; score=0.95
                rationale='Canonical bilingual terms + word-order normalization align.'
        elif (concept_evidence := concept_alias(req_set, col_set, col.get('sql_type',''))):
            score=0.89; status='BILINGUAL_CONCEPT_REVIEW'
            rationale=concept_evidence
        elif req_set and {_inflected_base(t) for t in req_set} == {_inflected_base(t) for t in col_set}:
            # English singular/plural inflections (saving -> savings); can only
            # be a proposed alias, and must not swallow different qualifiers.
            score=0.91;status='BUSINESS_ALIAS_REVIEW'
            rationale='Inflection/plural equivalence in normalized tokens; meaning still needs PIC verification.'
        elif (col_set-req_set) and (col_set-req_set).issubset(TIME_UNIT_TOKENS) and (
                req_set and (req_set & TIME_MEASURE_CONCEPTS) and req_set == col_set-(col_set-req_set)):
            # Leadtime Negotiation -> NegotiationLeadtimeDays (already output).
            # No formula is inferred; unit/day must be confirmed.
            score=0.87;status='UNIT_ALIAS_REVIEW'
            rationale=(f'Existing SQL column matches concept/word order but includes temporal unit '
                       f'{", ".join(sorted(col_set-req_set))}; PIC must verify formula and unit, not auto-calculate.')
        elif (req_set and req_set < col_set
              and not req_ids and not col_ids
              and (col_set - req_set).issubset(BUSINESS_ATTRIBUTE_QUALIFIERS)
              and 1 <= len(col_set - req_set) <= 2
              and any(len(token) >= 4 and token not in BUSINESS_ATTRIBUTE_QUALIFIERS
                      for token in req_set)):
            # Business concept -> specific attribute. This is intentionally NOT
            # direct semantic equivalence. Exclude generic-only requests and
            # surface multiple plausible qualifiers rather than choosing one.
            extra = sorted(col_set - req_set)
            score=0.73
            status='ATTRIBUTE_EXTENSION_REVIEW'
            rationale=(f'Business concept tokens match, but the SQL column adds '
                       f'qualifier(s) {extra}. Check whether the requirement '
                       'means status/date/name/type/etc.; not covered until PIC '
                       'confirms the intended business attribute.')
        elif (qualified := _qualified_attribute_candidate(req_set, col_set, col.get('sql_type',''))):
            score=qualified['rank_score']
            status=qualified['status']
            rationale=qualified['evidence']
        elif len(req_words)>=2 and len(col_words)>=2:
            # Example Site Order Number -> SONumb (SO + Numb).
            r=list(req_raw_words)
            c=list(col_raw_words)
            # Compare order-independent canonical terms while allowing ONE acronym/abbrev token.
            raw_r=set(req_words);raw_c=set(col_words)
            if common and len(common)>=1:
                r_rest=sorted(raw_r-common)
                c_rest=sorted(raw_c-common)
                if len(r_rest)==1 and len(c_rest)==1:
                    a,b=r_rest[0],c_rest[0]
                    if (min(len(a),len(b))>=2 and
                         (a.startswith(b) or b.startswith(a)) and
                         max(len(a),len(b))>=4):
                        score=0.84;status='ABBREVIATION_ALIAS_REVIEW'
                        rationale=f'One shared token plus possible shortened token ({a} / {b}); PIC must verify.'
                # Compact consonant contraction with a NON-ID context token.
                # WHOriginID -> WarehouseOriginID: Origin provides business
                # context and ID matches ID. WH alone is never sufficient.
                if (not status and len(r_rest)==1 and len(c_rest)==1
                        and common - IDENTIFIER_TOKENS):
                    a,b=r_rest[0],c_rest[0]
                    short,long=sorted((a,b), key=len)
                    if _consonant_abbreviation(short,long):
                        anchor = common - IDENTIFIER_TOKENS
                        strong = bool(anchor - WEAK_ABBREVIATION_ANCHORS)
                        score=0.82 if strong else 0.70
                        status='ABBREVIATION_ALIAS_REVIEW'
                        rationale=(f'Compressed-word abbreviation hypothesis '
                                   f'({short.upper()} may expand to {long}) '
                                   f'with shared context {sorted(anchor)}; '
                                   + ('independent business anchor present; ' if strong
                                      else 'generic-only context, weak suggestion; ')
                                   + 'PIC must verify source meaning.')
                # Conservative fuzzy typo with shared semantic anchor and no missing business qualifiers.
                if not status and len(r_rest)==1 and len(c_rest)==1:
                    a,b=r_rest[0],c_rest[0]
                    if min(len(a),len(b))>=4 and a[:2]==b[:2] and SequenceMatcher(None,a,b).ratio()>=0.85:
                        score=0.78;status='FUZZY_ALIAS_REVIEW'
                        rationale=f'One shared business token plus typo-like token ({a} / {b}); review required.'
            if not status:
                # Initials of requested multiword phrase may form a compact SQL token.
                # Example 'Site Order Number' -> SO + Numb; requires a common canonical anchor.
                req_unmatched=[t for t in ordered_field_tokens(requested,terms) if t not in col_set]
                col_unmatched=[t for t in ordered_field_tokens(actual,terms) if t not in req_set]
                if len(common)>=1 and len(req_unmatched)>=2 and len(col_unmatched)==1:
                    abbr=''.join(word[0] for word in req_unmatched)
                    if len(abbr)>=2 and col_unmatched[0]==abbr:
                        score=0.76;status='ABBREVIATION_ALIAS_REVIEW'
                        rationale=f'Initialism hypothesis {abbr.upper()} from {req_unmatched}; never asserted as business equivalent.'
        else:
            # Conservative whole-string typo (not a shortcut to equate unrelated words).
            if (len(req_norm)>=7 and len(actual_norm)>=7 and req_norm[:3]==actual_norm[:3] and
                SequenceMatcher(None,req_norm,actual_norm).ratio()>=0.89):
                score=0.72;status='FUZZY_ALIAS_REVIEW'
                rationale='High character similarity only; no semantic proof.'
        if status:
            output.append({'actual':actual, 'status':status,
                           'rank_score':round(score,3),
                           'evidence':rationale + ' PIC validation required.',
                           'factor':0.0 if status in {'REFERENCE_KEY_REVIEW', 'ATTRIBUTE_EXTENSION_REVIEW', 'QUALIFIED_ATTRIBUTE_REVIEW', 'IDENTIFIER_GRAIN_REVIEW'} else round(score*.65,3)})
        # General bilingual vocabulary is shipped with the engine; no prior
        # request/feedback or per-column alias is required. Run after structural
        # ID/unit/attribute gates, and do not overwrite stronger lexical evidence.
        if not status and req_ids==col_ids:
            from ojt2_bilingual_lexicon import translation_evidence
            raw_request=tuple(t for t in identifier_tokens(requested,terms,GENERAL_ENDINGS) if t not in NOISE_TOKENS)
            raw_column=tuple(t for t in identifier_tokens(actual,terms,GENERAL_ENDINGS) if t not in NOISE_TOKENS)
            evidence=translation_evidence(raw_request,raw_column,lambda word:_canonical_token(word,terms))
            if evidence:
                output.append({'actual':actual,'status':'BILINGUAL_LEXICON_REVIEW',
                    'rank_score':.86 if min(len(raw_request),len(raw_column))>=2 else .78,
                    'factor':.50,'evidence':evidence})
    # prevent nondeterministic ties; suggestions display does NOT resolve ties.
    # Contextual hypotheses go through the SAME shared candidate generator used
    # by Discovery, Metadata Explorer and Source Gap. Never treat these as
    # verified business aliases; carry zero coverage factor until PIC review.
    review_only = contextual_candidates(columns, requested, object_name=context,
                                        limit=max(limit, len(columns)))
    for extra in review_only:
        if decisions.get((object_key, req_norm, norm(extra['actual']))) == 'REJECTED':
            continue
        if any(item['actual']==extra['actual'] for item in output):
            continue
        output.append(extra)
    # The optional pretrained model retrieves *new* meaning-based hypotheses.
    # Lexical/registered evidence wins for the same column. Semantic proposals
    # are always review-only (factor=0), never automatic coverage or JOIN proof.
    for hypothesis in output:
        status=hypothesis['status']
        method=('bilingual_dictionary' if status=='BILINGUAL_LEXICON_REVIEW' else
                'pic_local' if status=='REGISTERED_ALIAS_REVIEW' else
                'contextual' if status in {'OBJECT_CONTEXT_REVIEW','ACTOR_ATTRIBUTE_REVIEW',
                    'EVENT_SEMANTIC_REVIEW','FORMULA_DEFINITION_REVIEW','ANNOTATION_CONTEXT_REVIEW'}
                else 'lexical')
        hypothesis['retrieval_methods']=[method]
        hypothesis['evidence_by_method']={method:hypothesis['evidence']}
    if include_semantic and not any(x['status']=='REGISTERED_ALIAS_REVIEW' for x in output):
        from ojt2_semantic_engine import semantic_candidates
        already={x['actual']:x for x in output}
        # Union the retrieval channels BEFORE deciding. A plausible lexical hit
        # cannot hide a different bilingual candidate. Keep ambiguity internally.
        for item in semantic_candidates(columns, requested, object_name=context,
                    purpose=business_context, source_hint=source_hint,
                    limit=max(limit,5)):
            if (norm(item['actual']) == req_norm or
                decisions.get((object_key, req_norm, norm(item['actual'])))=='REJECTED' or
                not _credible_semantic_hypothesis(item, requested)):
                continue
            if item['actual'] in already:
                existing=already[item['actual']]
                existing['retrieval_methods'].append('semantic')
                existing['evidence_by_method']['semantic']=item['evidence']
                for key in ('semantic_similarity','field_similarity','context_similarity',
                            'semantic_rerank_score','semantic_risk_flags'):
                    if key in item:
                        existing[key]=item[key]
                continue
            item=dict(item,retrieval_methods=['semantic'],
                      evidence_by_method={'semantic':item['evidence']})
            output.append(item)
            already[item['actual']]=item
    if include_shared_feedback:
        from ojt2_shared_learning import apply_shared_feedback
        output = apply_shared_feedback(output, columns, requested, domain=domain,
            object_key=object_key, decisions=decisions, shared=shared_feedback)
    # Apply the same constraints after all channels, including context and
    # transferred feedback, so a rejected semantic relation cannot reappear.
    output=[item for item in output if not _candidate_facet_conflict(requested,item['actual'])]
    output.sort(key=lambda x:(-x['rank_score'], x['actual'].casefold()))
    return output[:max(1,limit)]


def propose_field_match(columns: list[dict], requested: str,
                        domain: str | None=None, object_key: str | None=None,
                        decisions: dict | None=None, terms: dict | None=None,
                        context: str = '', business_context: str = '',
                        source_hint: str = '',
                        shared_feedback: dict | None = None,
                        precomputed_alternatives: list[dict] | None = None) -> dict | None:
    """Backward-compatible top suggestion, with candidates for PIC review.

    Preserve conservative legacy matching for existing demo tests; generic
    generator contributes additional ranked alternatives and handles novel variants.
    Ambiguity intentionally returns None (but alternatives can be displayed).
    """
    initial=_legacy_propose_field_match(columns,requested,domain,object_key,decisions,terms)
    alternatives=(precomputed_alternatives if precomputed_alternatives is not None
                  else field_suggestions(columns,requested,domain=domain,
                  object_key=object_key,decisions=decisions,terms=terms,limit=5,
                  context=context,business_context=business_context,source_hint=source_hint,
                  shared_feedback=shared_feedback))
    # Contextual hypotheses may rank highly, but NEVER enter the legacy
    # automatic alias-proposal path. _field_evidence surfaces them separately.
    if initial and initial['status']=='REGISTERED_ALIAS_REVIEW':
        return dict(initial, suggestions=alternatives)
    contextual_statuses = {'OBJECT_CONTEXT_REVIEW','ACTOR_ATTRIBUTE_REVIEW',
      'EVENT_SEMANTIC_REVIEW','FORMULA_DEFINITION_REVIEW','ANNOTATION_CONTEXT_REVIEW',
      'SEMANTIC_REVIEW', 'CROSS_DOMAIN_FEEDBACK_REVIEW',
      'SAME_DOMAIN_FEEDBACK_REVIEW'}
    viable=[x for x in alternatives if x['status'] not in contextual_statuses | {'REFERENCE_KEY_REVIEW'}]
    # Do not let legacy fuzzy matching pick an arbitrary winner when two
    # columns are equally plausible. Keep all options in Top-N for PIC.
    ambiguous=(len(viable)>1 and
               viable[0]['rank_score']-viable[1]['rank_score']<0.09)
    if initial and not ambiguous and any(s['actual']==initial['actual'] for s in alternatives):
        initial=dict(initial)
        initial['suggestions']=alternatives
        return initial
    if ambiguous:
        return None
    if not viable:
        return None
    best=viable[0]
    # Do not arbitrarily select a top match if several columns look interchangeable.
    if len(viable)>1 and best['rank_score']-viable[1]['rank_score']<0.09:
        return None
    if best['rank_score']<0.76:
        return None
    return {k:best[k] for k in ('actual','status','factor','evidence')} | {'suggestions':alternatives}
