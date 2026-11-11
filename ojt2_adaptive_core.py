"""OJT2 Stage 4.1 adaptive, evidence-aware discovery for synthetic SQL Server catalog.

Does NOT use LLM, execute queries, or prove business meaning. Curated synthetic
synonyms and URL source registry require explicit PIC approval before production.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit
import re

from ojt2_field_matching import (get_alias_decisions, get_term_rules, propose_field_match, field_suggestions, split_tokens)
from ojt2_shared_learning import load_shared_feedback
from ojt2_requirement_semantics import decompose_requirement, object_context_tokens
from ojt2_discovery_core import (norm, tokens, unique_fields,
    parse_excel_requirement as _parse_stage4, DEMO_GDL, GDL_FIELDS,
    save_review, list_reviews, get_setting, set_setting, HISTORY_DB)

VERSION = "0.6.1-field-facet-guards"
RULE_VERSION = "shared-matcher-evidence-v9"

# Each keyword is a traceable rule, NOT an ML understanding of arbitrary text.
DOMAIN_RULES: dict[str, dict[str, Any]] = {
 "GDL": {
   "patterns": [r"barang.{0,18}keluar",r"keluar.{0,18}gudang",r"pengeluaran material",r"distribusi material",r"alokasi material",r"pengiriman barang",r"rekonsiliasi pengeluaran",r"\bgdl\b",r"warehouse origin"],
   "object_tokens": ["gdl", "warehouse"],
   "aliases": {"nomorsuratkeluar":"gdlno", "nomordokumenkeluar":"gdlno", "situstower":"sitename", "lokasimenara":"sitename", "kuantitasbarangkeluar":"qtygdl", "jumlahmaterialkeluar":"qtygdl", "tanggalpengeluaran":"gdldate", "hargasatuan":"priceperunit", "totalnilaikeluar":"amountgdl", "nilaipengeluaran":"amountgdl", "asalgudang":"whorigin", "gudangasal":"whorigin", "nomororder":"ponumber", "jenismaterial":"typematerial"}
 },
 "STIP": {
   "patterns": [r"\bstip\b",r"antarsite",r"antar.site",r"intersite",r"jalur fiber",r"segmen",r"ring segment",r"persetujuan permohonan"],
   "object_tokens": ["stip", "segment"],
   "aliases": {"kategorisegmen":"segmenttype", "tiperasegmen":"segmenttype", "ringsegment":"ringsegment", "statuspersetujuan":"approvalstatus", "statusapproval":"approvalstatus"}
 },
 "DEVIATION": {
   "patterns": [r"deviasi",r"deviation",r"pengecualian",r"outstanding",r"tindak lanjut",r"masih nyangkut",r"belum action"],
   "object_tokens": ["deviation"],
   "aliases": {"nomordeviasi":"deviationno", "jenisdeviasi":"deviationtype", "nilairupiah":"amount", "picyangbelumaction":"picoutstanding", "penanggungjawaboutstanding":"picoutstanding", "statusterkini":"status", "umuroutstandinghari":"__unresolved_derived__", "lamaprosesoutstanding":"__unresolved_derived__"}
 },
 "PROCUREMENT": {
   "patterns": [r"negosiasi",r"pengadaan",r"\bsph\b",r"\bspk\b",r"\bprocurement\b",r"selisih harga"],
   "object_tokens": ["procurement", "negotiation", "prc", "sph", "spk"],
   "aliases": {"penghematan":"savings", "nilaiefisiensi":"savings", "lamanegosiasi":"negotiationleadtimedays", "leadtime negosiasi":"negotiationleadtimedays"}
 },
 "PROJECT": {
   "patterns": [r"project information",r"informasi proyek",r"proyek",r"\bproject\b",r"target rfi"],
   "object_tokens": ["project"], "aliases": {"areaproyek":"area", "statusproyek":"projectstatus"}
 },
 "XLSMART": {
   "patterns": [r"xlsmart",r"xl smart",r"drm",r"household coverage"],
   "object_tokens": ["xlsmart", "drm"], "aliases": {"rumahtercakup":"household"}
 }
}

# Curated app-page -> source registry; path cannot be inferred from SQL metadata alone.
SOURCE_REGISTRY = {
    "/businesssupport/deviation/report": {"database":"DEMO_HR_Reference", "schema":"dbo", "object":"vwDeviationOutstanding", "domain":"DEVIATION", "review_status":"DEMO_CURATED"}
}
EXACT_OBJECT_PATTERN = re.compile(r"\b(?:vw|rpt|usp|sp|temp)[A-Za-z0-9_]{5,}\b", re.I)
DERIVED_PATTERN = re.compile(r"\b(umur|berapa hari|leadtime|lama proses|durasi|selisih|persentase|%|saving)\b", re.I)



# Conservative non-LLM matching helpers. A matching label is always a PROPOSAL.
# Do not equate identifiers (SelectionID) with business values (Selection).
BUSINESS_TOKEN_TRANSLATIONS = {"nama": "name"}
ALIAS_REVIEW_STATUSES = frozenset({"CURATED_ALIAS_REVIEW", "BUSINESS_ALIAS_REVIEW", "ABBREVIATION_ALIAS_REVIEW", "FUZZY_ALIAS_REVIEW", "REGISTERED_ALIAS_REVIEW", "UNIT_ALIAS_REVIEW", "BILINGUAL_CONCEPT_REVIEW", "BILINGUAL_LEXICON_REVIEW"})
OUTSTANDING_STATUSES = frozenset({"MISSING", "UNRESOLVED_DERIVED", "REFERENCE_KEY_REVIEW", "ATTRIBUTE_EXTENSION_REVIEW", "MULTIPLE_ATTRIBUTE_OPTIONS_REVIEW",
    "OBJECT_CONTEXT_REVIEW", "ACTOR_ATTRIBUTE_REVIEW", "EVENT_SEMANTIC_REVIEW",
    "FORMULA_DEFINITION_REVIEW", "ANNOTATION_CONTEXT_REVIEW",
    "MULTIPLE_CONTEXT_OPTIONS_REVIEW", "SEMANTIC_REVIEW",
    "CROSS_DOMAIN_FEEDBACK_REVIEW", "SAME_DOMAIN_FEEDBACK_REVIEW",
    "QUALIFIED_ATTRIBUTE_REVIEW", "IDENTIFIER_GRAIN_REVIEW",
    "AMBIGUOUS_MATCH_REVIEW", "POTENTIAL_MATCH_REVIEW"})

def _business_tokens(text: str) -> tuple[str, ...]:
    # Split CamelCase/PascalCase and underscores, then translate conservative equivalents.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text or ""))
    parts = re.findall(r"[a-z0-9]+", separated.casefold())
    return tuple(sorted(BUSINESS_TOKEN_TRANSLATIONS.get(t, t) for t in parts))

def _hits(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, text, flags=re.I)]


def parse_excel_requirement(contents: bytes, filename: str = 'document.xlsx', sheet: str | None = None) -> dict:
    """Preserves user's DataMart_DeptName two-column template, never guesses missing values."""
    info = _parse_stage4(contents, filename, sheet)
    labels = [r[0].strip().casefold() for r in info.get('preview_rows', []) if r and r[0]]
    expected = {'requestor name', 'division name', 'department name', 'purpose', 'data source', 'filtering', 'columns required'}
    is_original = expected.issubset(set(labels)) and info.get('sheet')=='DataMart_DeptName'
    info['template_detected'] = 'TBIGData_2_COLUMN' if is_original else 'GENERIC_BEST_EFFORT'
    # The purpose/source/filtering/columns fields remain as supplied, not AI rewritten.
    info['parse_confidence_label'] = 'REVIEW_REQUIRED'
    # Preserve originals for audit. Interpret annotations separately so the
    # matching engine never mistakes a long calculation for a column name.
    info['field_interpretations'] = [asdict(decompose_requirement(field))
                                     for field in info.get('required_fields', [])]
    if not is_original:
        info.setdefault('parse_notes', []).append('Struktur berbeda dari template contoh; cek hasil parsing satu per satu.')
    return info


def plan_search(req: dict) -> dict:
    hint = str(req.get('source_hint','')).strip()
    combined = ' '.join(str(req.get(k,'')) for k in ('purpose','source_hint','filtering'))
    fields = ' '.join(req.get('required_fields',[]) or [])
    domain_evidence = {name:_hits(combined+' '+fields, item['patterns']) for name,item in DOMAIN_RULES.items()}
    ordered = sorted(domain_evidence, key=lambda d:(-len(domain_evidence[d]),d))
    chosen = ordered[0] if ordered and domain_evidence[ordered[0]] else None
    if chosen and len(domain_evidence[chosen])==1 and not hint:
        # Weak generic signal (e.g. just "proyek") should not auto establish domain.
        if chosen in {'PROJECT','DEVIATION'}: chosen=None
    if re.search(r'https?://',hint,re.I):
        try: path=urlsplit(hint).path.lower().rstrip('/')
        except ValueError: path=''
    else:
        path = ('/'+hint.lower().strip('/').split('?')[0]) if hint.lower().startswith('businesssupport/') else ''
    registry = SOURCE_REGISTRY.get(path)
    if registry: chosen=registry['domain']
    explicit = EXACT_OBJECT_PATTERN.findall(hint)
    exact=explicit[0] if explicit else None
    req_fields=unique_fields(req.get('required_fields', []))
    if registry: primary='APP_MENU_REGISTRY'
    elif exact: primary='EXACT_OBJECT_LOOKUP'
    elif chosen and len(domain_evidence.get(chosen,[]))>=2: primary='BUSINESS_CONTEXT'
    elif req_fields: primary='FIELD_FIRST'
    elif chosen: primary='BUSINESS_CONTEXT_LOW_EVIDENCE'
    else: primary='INSUFFICIENT_EVIDENCE'
    strategies = [primary]
    if req_fields and primary!='FIELD_FIRST': strategies.append('FIELD_COVERAGE')
    if any(DERIVED_PATTERN.search(x) for x in req_fields):strategies.append('DERIVED_FIELD_REVIEW')
    if req_fields: strategies.append('SOURCE_GAP_CHECK')
    warnings=[]
    if primary=='INSUFFICIENT_EVIDENCE': warnings.append('Petunjuk bisnis belum cukup untuk rekomendasi sumber. PIC perlu menambah informasi.')
    if not req_fields: warnings.append('Columns Required kosong: coverage tidak dapat dihitung.')
    if chosen and len(domain_evidence.get(chosen,[])) < 2 and not registry and not exact:
        warnings.append('Domain konteks lemah; keputusan wajib manual.')
    if re.search(r'direktorat|pic.*aktif|latest|terakhir|per.site|per site',req.get('filtering',''),re.I):
        warnings.append('Filtering memerlukan verifikasi business rule dan kolom/join; bukan bukti source valid.')
    return {'primary':primary,'strategies':strategies,'domain':chosen,
            'domain_patterns':domain_evidence.get(chosen,[]) if chosen else [],
            'exact_object':exact,'app_path':path,'registry':registry,
            'warnings':warnings,'rule_version':RULE_VERSION}


def _field_evidence(cols: list[dict], request_field: str, domain: str | None,
                    object_key: str | None = None, decisions: dict | None = None,
                    term_rules: dict | None = None,
                    object_name: str = '', business_context: str = '',
                    source_hint: str = '', shared_feedback: dict | None = None) -> dict:
    req_name=norm(request_field)
    suggestions = field_suggestions(cols, request_field, domain=domain, object_key=object_key,
                                   decisions=decisions, terms=term_rules, limit=12,
                                   context=object_name, business_context=business_context,
                                   source_hint=source_hint, shared_feedback=shared_feedback)
    exact=[c for c in cols if norm(c['column_name'])==req_name]
    literal=[c for c in exact if c['column_name']==request_field]
    if len(literal)==1 or len(exact)==1:
        c=(literal or exact)[0]
        return {'requested':request_field,'actual':c['column_name'],'status':'NAME_MATCH',
                'evidence':'Exact normalized column name (metadata)','factor':1.0}
    if len(exact)>1:
        return {'requested':request_field,'actual':None,'status':'AMBIGUOUS_MATCH_REVIEW',
                'evidence':'Several physical columns have the same normalized name; select the intended column.',
                'factor':0.0,'suggestions':[{'actual':c['column_name'],
                    'status':'BUSINESS_ALIAS_REVIEW','rank_score':.95,'factor':0.0,
                    'evidence':'Normalized name collision; not an automatic mapping.'} for c in exact]}
    # A prior explicit PIC decision has precedence over heuristic alias suggestions.
    proposal=propose_field_match(cols, request_field, domain, object_key, decisions, term_rules,
                                 context=object_name, business_context=business_context,
                                 source_hint=source_hint, shared_feedback=shared_feedback,
                                 precomputed_alternatives=suggestions)
    if proposal and proposal['status']=='REGISTERED_ALIAS_REVIEW':
        return {'requested':request_field, **proposal, 'suggestions':suggestions}
    aliases=DOMAIN_RULES.get(domain or '',{}).get('aliases',{})
    alias=aliases.get(req_name)
    if alias=='__unresolved_derived__':
        # An explicit unresolved rule is authoritative until validated/updated.
        return {'requested':request_field,'actual':None,'status':'UNRESOLVED_DERIVED',
                'evidence':'Explicit derived/unresolved business rule; verify required calculation',
                'factor':0.0,'suggestions':suggestions}
    if alias:
        for c in cols:
            if norm(c['column_name'])==norm(alias):
                rejected=(decisions or {}).get((object_key,req_name,norm(c['column_name'])))=='REJECTED'
                if not rejected:
                    return {'requested':request_field,'actual':c['column_name'],'status':'CURATED_ALIAS_REVIEW',
                            'evidence':f'Demo rule {domain}: {request_field} -> {c["column_name"]}; requires PIC approval', 'factor':0.65, 'suggestions':suggestions}
    # IMPORTANT: detect candidate materialized/derived output *before* treating
    # words like 'saving' or 'leadtime' as missing calculations. If the SQL
    # output contains Savings/NegotiationLeadtimeDays, propose it for PIC review.
    if proposal:
        return {'requested':request_field, **proposal, 'suggestions':suggestions}
    # Contextual proposal is NOT a direct alias or covered field: object name,
    # actor, event, and metric formula are separate semantic assertions.
    contextual_statuses={'OBJECT_CONTEXT_REVIEW','ACTOR_ATTRIBUTE_REVIEW',
                          'EVENT_SEMANTIC_REVIEW','FORMULA_DEFINITION_REVIEW',
                          'ANNOTATION_CONTEXT_REVIEW','SEMANTIC_REVIEW',
                          'CROSS_DOMAIN_FEEDBACK_REVIEW','SAME_DOMAIN_FEEDBACK_REVIEW',
                          'QUALIFIED_ATTRIBUTE_REVIEW','IDENTIFIER_GRAIN_REVIEW'}
    contextual=[s for s in suggestions if s['status'] in contextual_statuses]
    if contextual:
        # Avoid arbitrary actor/event selection when scores are close; show Top-N.
        # A generic DepartmentName and a CreatedbyDepartmentName are both
        # meaningful possibilities; don't pick an actor-specific column just
        # because its contextual proposal has a slightly higher rank.
        competing=[s for s in suggestions if s['status'] in contextual_statuses | {'ATTRIBUTE_EXTENSION_REVIEW'}]
        close=[s for s in competing if contextual[0]['rank_score']-s['rank_score'] < .13]
        if len(close)==1:
            chosen=contextual[0]
            return {'requested':request_field, 'actual':chosen['actual'],
                    'status':chosen['status'], 'factor':0.0,
                    'evidence':chosen['evidence'], 'suggestions':suggestions}
        return {'requested':request_field,'actual':None,
                'status':'MULTIPLE_CONTEXT_OPTIONS_REVIEW','factor':0.0,
                'evidence':'Several actor/event/attribute candidates; inspect Top-N and confirm the business role and data grain.',
                'suggestions':suggestions}
    if DERIVED_PATTERN.search(request_field):
        return {'requested':request_field,'actual':None,'status':'UNRESOLVED_DERIVED',
                'evidence':'No justified existing output column found; calculation/temporal definition requires SQL expression and PIC review',
                'factor':0.0, 'suggestions':suggestions}
    # Identifier hint only, NOT a business-value alias. Selection != SelectionID.
    # A likely FK/key can point to another source containing the requested label/status.
    if req_name and not req_name.endswith(('id', 'key', 'code')):
        key_matches = [c for c in cols if norm(c['column_name']) in {req_name+'id', req_name+'key', req_name+'code'}]
        if len(key_matches) == 1:
            col=key_matches[0]
            return {'requested':request_field,'actual':col['column_name'],
                    'status':'REFERENCE_KEY_REVIEW',
                    'evidence':f'{col["column_name"]} may be an identifier, not the requested business value. Check FK/lookup, label/status meaning and grain. NOT counted as covered.',
                    'factor':0.0, 'suggestions':suggestions}
    # One business concept can have multiple attribute variants (Status, Date,
    # Type, Name). Show candidates to PIC, but do not count them as covered.
    qualifier_options=[x for x in suggestions if x['status']=='ATTRIBUTE_EXTENSION_REVIEW']
    if qualifier_options:
        if len(qualifier_options)==1:
            q=qualifier_options[0]
            return {'requested':request_field,'actual':q['actual'],
                    'status':'ATTRIBUTE_EXTENSION_REVIEW',
                    'factor':0.0,'evidence':q['evidence'],
                    'suggestions':suggestions}
        return {'requested':request_field,'actual':None,
                'status':'MULTIPLE_ATTRIBUTE_OPTIONS_REVIEW',
                'factor':0.0,
                'evidence':'Multiple attribute-specific candidates; PIC must select intent.',
                'suggestions':suggestions}
    # A retrieved candidate is not an absent column. Keep uncertainty separate
    # from missing, including duplicate canonical aliases and weak abbreviations.
    alternatives=[s for s in suggestions if s['status']!='REFERENCE_KEY_REVIEW']
    if alternatives:
        ambiguous=len(alternatives)>1 and alternatives[0]['rank_score']-alternatives[1]['rank_score']<.09
        return {'requested':request_field,
                'actual':None if ambiguous else alternatives[0]['actual'],
                'status':'AMBIGUOUS_MATCH_REVIEW' if ambiguous else 'POTENTIAL_MATCH_REVIEW',
                'factor':0.0,'suggestions':suggestions,
                'evidence':'Multiple plausible columns; PIC must choose.' if ambiguous else
                           'A possible column was retrieved; evidence is not sufficient for a primary alias mapping.'}
    return {'requested':request_field,'actual':None,'status':'MISSING',
            'evidence':'No compatible field candidate identified in this catalog scope. Check metadata completeness and semantic-model availability.',
            'factor':0.0, 'suggestions':suggestions}


def discover(data: dict, index: dict, requirement: dict, allowed_databases: list[str] | None=None, limit: int=20) -> list[dict]:
    plan=plan_search(requirement)
    if plan['primary']=='INSUFFICIENT_EVIDENCE': return []
    fields=unique_fields(requirement.get('required_fields',[]))
    allowed=set(allowed_databases or [o['database_name'] for o in data['objects']])
    registry=plan['registry']
    exact=norm(plan['exact_object'] or '')
    decisions=get_alias_decisions(plan['domain'])
    term_rules=get_term_rules(plan['domain'])
    shared_feedback=load_shared_feedback()  # read once for a full discovery pass
    from ojt2_semantic_engine import warm_semantic_cache
    warm_semantic_cache([(o['object_name'],index['columns'].get(o['object_key'],[]))
        for o in data['objects'] if o['database_name'] in allowed and o['object_type'].strip() in {'U','V'}],
        fields,requirement.get('purpose',''),requirement.get('source_hint',''))
    result=[]
    for obj in data['objects']:
        if obj['database_name'] not in allowed:continue
        typ=obj['object_type'].strip()
        if typ not in {'U','V'}:continue  # SP is lineage evidence, not standalone output without documented result schema.
        objname=norm(obj['object_name'])
        cols=index['columns'].get(obj['object_key'],[])
        field_map=[_field_evidence(cols,f,plan['domain'],obj['object_key'],decisions,term_rules,
                                   object_name=obj['object_name'],
                                   business_context=requirement.get('purpose',''),
                                   source_hint=requirement.get('source_hint',''),
                                   shared_feedback=shared_feedback) for f in fields]
        contextual_hits=sum(bool(m['status'] in OUTSTANDING_STATUSES and m.get('actual')
                            and m['status'].endswith('_REVIEW')) for m in field_map)
        # Only overlap with concrete source-object tokens, not generic portal words.
        hint_tokens=set(re.findall(r'[a-z]{4,}', str(requirement.get('source_hint','')).casefold()))
        source_hint_match=bool(object_context_tokens(obj['object_name']) & hint_tokens)
        # Fully qualified / object name as an explicit user source hint can
        # corroborate a *single* learned feedback candidate. Never infer source
        # confidence from generic CREATE/STATUS fields alone.
        hint_compact=norm(requirement.get('source_hint',''))
        object_compact=norm(obj['object_name'])
        source_hint_match = source_hint_match or bool(
            len(object_compact) >= 8 and object_compact in hint_compact)
        review_signal=sum(max((float(v.get('rank_score',0)) for v in m.get('suggestions',[]) if
                    v['status'] in {'OBJECT_CONTEXT_REVIEW','ACTOR_ATTRIBUTE_REVIEW','EVENT_SEMANTIC_REVIEW',
                      'FORMULA_DEFINITION_REVIEW','ANNOTATION_CONTEXT_REVIEW','SEMANTIC_REVIEW',
                      'CROSS_DOMAIN_FEEDBACK_REVIEW','SAME_DOMAIN_FEEDBACK_REVIEW',
                          'QUALIFIED_ATTRIBUTE_REVIEW','IDENTIFIER_GRAIN_REVIEW'}),default=0)
                    for m in field_map)/len(fields) if fields else 0.0
        # Pure semantic results never create verified/direct coverage.
        semantic_hits=sum(m['status']=='SEMANTIC_REVIEW' or
            any(s['status']=='SEMANTIC_REVIEW' and s.get('rank_score',0)>=.57
                for s in m.get('suggestions',[])) for m in field_map)
        semantic_signal=sum(max((s['rank_score'] for s in m.get('suggestions',[])
                        if s['status']=='SEMANTIC_REVIEW'),default=0)
                        for m in field_map)/len(fields) if fields else 0.0
        # Historical PIC knowledge is global SUGGESTION evidence only.
        # One transferred pair is not enough to retrieve every table that has
        # a ubiquitous column like CreatedBy. Require source corroboration or
        # multiple independently learned field suggestions.
        feedback_statuses={'CROSS_DOMAIN_FEEDBACK_REVIEW','SAME_DOMAIN_FEEDBACK_REVIEW'}
        feedback_hits=sum(any(x['status'] in feedback_statuses for x in
                    ([m] if m.get('actual') else []) + m.get('suggestions',[]))
                    for m in field_map)
        feedback_signal=sum(max((s['rank_score'] for s in m.get('suggestions',[])
                        if s['status'] in feedback_statuses),default=0)
                        for m in field_map)/len(fields) if fields else 0.0
        direct=sum(m['status']=='NAME_MATCH' for m in field_map)
        alias=sum(m['status'] in ALIAS_REVIEW_STATUSES for m in field_map)
        proposed=(direct+alias)/len(fields) if fields else 0
        weighted=sum(m['factor'] for m in field_map)/len(fields) if fields else 0
        explicit_match=1.0 if exact and objname==exact else 0
        registry_match=1.0 if registry and obj['database_name']==registry['database'] and obj['schema_name'].casefold()==registry['schema'] and obj['object_name'].casefold()==registry['object'].casefold() else 0
        domain_rule=DOMAIN_RULES.get(plan['domain'] or '',{})
        obj_tokens=domain_rule.get('object_tokens',[])
        domain_match=1.0 if any(t in objname for t in obj_tokens) else 0
        # Dataset names can add domain context but cannot override contradictory field evidence.
        if plan['primary']=='EXACT_OBJECT_LOOKUP':
            score=55*explicit_match + 29*weighted + 11*domain_match + (5 if typ=='V' else 2)
        elif plan['primary']=='APP_MENU_REGISTRY':
            score=51*registry_match + 30*weighted + 13*domain_match + (6 if typ=='V' else 3)
        elif plan['primary'] in {'BUSINESS_CONTEXT','BUSINESS_CONTEXT_LOW_EVIDENCE'}:
            score=44*domain_match + 44*weighted + (12 if typ=='V' else 9)
        else:
            score=69*weighted + 22*domain_match + (9 if typ=='V' else 6)
        # Contextual candidates are additional ranking evidence, NOT coverage.
        # Require several independent field signals and a source name consistent
        # with the hinted application before including non-direct candidates.
        context_route=bool(source_hint_match and contextual_hits>=2 and review_signal>=0.3)
        if context_route:
            score += 15 + min(17, 22*review_signal)
        # General semantic-only source discovery (no fixed object/domain names).
        # Multiple independent fields are required to avoid surfacing every
        # unrelated source with only one generic column, e.g. 'Status'.
        semantic_route=bool(semantic_hits>=2 and semantic_signal>=.39
                            and semantic_hits/max(1,len(fields))>=.25)
        # A single specific bilingual field may be the entire requirement.
        # Require strong label-only evidence; one generic Status/Name/ID is not
        # sufficient to retrieve unrelated tables through the semantic channel.
        if len(fields)==1 and len(set(split_tokens(fields[0]))-{'name','id','code','key','number','status','date','type'})>=1:
            semantic_route=semantic_route or any(
                s['status']=='SEMANTIC_REVIEW' and float(s.get('field_similarity') or 0)>=.75
                and s['rank_score']>=.65 for s in field_map[0].get('suggestions',[]))
        if semantic_route:
            score += min(31, 34*semantic_signal)
        feedback_route = bool(feedback_hits >= 2 or (feedback_hits >= 1 and source_hint_match))
        if feedback_route:
            score += min(23, 10 + 17*feedback_signal)
        # Ambiguity must not erase a source that contains the requested concept.
        # Retrieval evidence contributes to source ranking, NEVER to coverage.
        ambiguity_signal=sum(max((s['rank_score'] for s in m.get('suggestions',[])
                if s['status'] in ALIAS_REVIEW_STATUSES),default=0)
                for m in field_map if m['status']=='AMBIGUOUS_MATCH_REVIEW')/len(fields) if fields else 0
        ambiguity_route=ambiguity_signal>=.5
        if ambiguity_route:
            score += min(24,24*ambiguity_signal)
        specific_matches=sum(bool(m.get('actual') and m['factor']>0 and
            set(split_tokens(m['requested']))-{'name','date','time','status','type','number','id','key','code'})
            for m in field_map)
        lexical_route=specific_matches>=2
        # Require object-level evidence; never rank just because of table/view type.
        if not (explicit_match or registry_match or domain_match or weighted>=0.4
                or context_route or semantic_route or feedback_route or ambiguity_route or lexical_route): continue
        if fields and not (direct or alias or explicit_match or registry_match
                           or context_route or semantic_route or feedback_route or ambiguity_route): continue
        ranking_evidence={}
        if fields:
            from ojt2_candidate_ranking import rank_field_evidence
            ranking_evidence=rank_field_evidence(field_map,domain_match=domain_match,
                explicit_match=explicit_match,registry_match=registry_match,hint_match=source_hint_match)
            score=ranking_evidence['score']
        score=round(min(100,max(0,score)),1)
        flags=[]
        if fields and not (direct or alias):
            flags.append('CONTEXTUAL_ONLY_NEEDS_REVIEW' if contextual_hits else 'OUTPUT_FIELD_CONFLICT_REVIEW')
        if alias: flags.append('ALIAS_BUSINESS_VALIDATION_REQUIRED')
        if contextual_hits: flags.append('CONTEXTUAL_FIELD_MAPPING_REQUIRES_PIC_REVIEW')
        if semantic_hits: flags.append('SEMANTIC_HYPOTHESES_NOT_VERIFIED')
        if feedback_hits: flags.append('SHARED_PIC_FEEDBACK_REQUIRES_LOCAL_VALIDATION')
        if any(m['status']=='REFERENCE_KEY_REVIEW' for m in field_map): flags.append('REFERENCE_KEY_NEEDS_LOOKUP')
        if any(m['status']=='UNRESOLVED_DERIVED' for m in field_map):flags.append('DERIVED_FIELDS_UNRESOLVED')
        if re.search(r'direktorat|directorate', requirement.get('filtering',''),re.I) and not any(norm(x['column_name'])=='directorate' for x in cols):
            flags.append('FILTER_DIRECTORATE_NOT_EXPOSED_ON_OUTPUT')
        if re.search(r'pic.*aktif|latest|terakhir',requirement.get('filtering',''),re.I):
            flags.append('FILTER_BUSINESS_RULE_NEEDS_PROCEDURE_REVIEW')
        result.append({'object_key':obj['object_key'],'object':obj, 'score':score,
                       'engine_version':VERSION,'rule_version':RULE_VERSION,
                       'ranking_evidence':ranking_evidence,
                       'field_map':field_map,'matched':direct,'alias_proposed':alias,
                       'context_proposed':contextual_hits,'semantic_proposed':semantic_hits,
                       'semantic_ranking_signal':round(semantic_signal,3),
                       'mapped_proposed':direct+alias,'total':len(fields),
                       'coverage':(direct/len(fields) if fields else None),
                       'proposed_coverage':proposed,'hint_score':round(explicit_match*100),
                       'context_score':round(domain_match*100),'type': 'View' if typ=='V' else 'Table',
                       'confidence_label':'ADAPTIVE_HEURISTIC_NOT_CONFIDENCE',
                       'availability':obj['logical_server'],'warnings':flags,
                       'routing':plan})
    return sorted(result,key=lambda x:(-x['score'],-x['mapped_proposed'],0 if x['type']=='View' else 1,
                                      x['object']['object_name']))[:limit]


def find_supporting(data:dict,index:dict,candidate:dict,requirement:dict,
                    allowed_databases:list[str]|None=None,limit_per_field:int=12)->list[dict]:
    """Backward-compatible entry point; universal engine owns every domain."""
    from ojt2_gap_engine import generalized_supporting
    return generalized_supporting(data,index,candidate,requirement,
                                 allowed_databases=allowed_databases,
                                 limit_per_field=limit_per_field)


def evidence_summary(candidate:dict,support:list[dict])->dict:
    from ojt2_gap_engine import summarize
    return summarize(candidate,support)
