"""General attribute/event guard regression, optionally using the real local model.

python 38_validate_field_facet_guards.py
python 38_validate_field_facet_guards.py --real-model
No SQL Server connection, application repository writes or model downloads.
"""
from pathlib import Path
import argparse
import importlib.util
import unittest
from unittest.mock import patch

from ojt2_adaptive_core import _field_evidence
from ojt2_field_matching import _candidate_facet_conflict, field_suggestions
from ojt2_semantic_engine import semantic_status

REAL_MODEL=False


def resolve(requested,names,object_name='vwAnyWorkflow'):
    columns=[{'column_name':n,'sql_type':'datetime' if n.endswith('Date') else
              'int' if n=='LeadTime' else 'nvarchar'} for n in names]
    return _field_evidence(columns,requested,None,'SIMULATED|DB|dbo|Object|V',
        object_name=object_name,business_context='Histori log feedback dan approval pengajuan',
        source_hint='',shared_feedback={})


class FacetGuardTests(unittest.TestCase):
    def setUp(self):
        if not REAL_MODEL:
            model=patch('ojt2_semantic_engine.semantic_candidates',return_value=[])
            model.start();self.addCleanup(model.stop)

    def test_memorandum_thirteen_fields(self):
        spec=importlib.util.spec_from_file_location('context_fixture',Path(__file__).with_name('27_validate_context_aware_requirements.py'))
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        actual=[]
        for query,(expected_column,expected_status) in zip(fixture.FIELDS,fixture.EXPECTED):
            with self.subTest(query=query):
                row=resolve(query,fixture.NAMES,'vwMemorandumHistory')
                self.assertEqual((row['actual'],row['status']),(expected_column,expected_status),row)
                actual.append(row)
        self.assertEqual(sum(r['status']=='NAME_MATCH' for r in actual),2)
        self.assertEqual(sum(r['status']=='MISSING' for r in actual),2)
        self.assertEqual(sum(r.get('actual') is not None and r['status']!='NAME_MATCH' for r in actual),9)
        self.assertTrue(all(r['factor']==0 for r in actual if r['status']!='NAME_MATCH'))

    def test_attribute_and_event_controls_across_domains(self):
        for query,names,expected,obj in [
            ('Contract Status',['Status','ContractNumber'],'Status','vwContractHistory'),
            ('Invoice Status',['InvoiceNumber'],None,'vwInvoiceHistory'),
            ('Feedback Date',['ReviewedDate'],None,'vwAnyWorkflow'),
            ('Resubmit Date',['CreatedDate'],None,'vwAnyWorkflow'),
            ('Review By',['ReviewedDate'],None,'vwAnyWorkflow'),
            ('Request Date',['CreatedDate'],'CreatedDate','vwAnyWorkflow'),
            ('Approve Date',['ReviewedDate'],'ReviewedDate','vwAnyWorkflow'),
            ('Review By',['ReviewedbyName'],'ReviewedbyName','vwAnyWorkflow'),
            ('Feedback Date (from Team)',['FeedbackDate'],'FeedbackDate','vwAnyWorkflow'),
            ('Resubmit Date (from User)',['ResubmitDate'],'ResubmitDate','vwAnyWorkflow')]:
            with self.subTest(query=query):
                self.assertEqual(resolve(query,names,obj)['actual'],expected)

    def test_high_model_similarity_cannot_override_conflicts(self):
        for query,col in [('Invoice Status','InvoiceNumber'),('Feedback Date','ReviewedDate'),
                          ('Review By','ReviewedDate')]:
            with self.subTest(query=query), patch('ojt2_semantic_engine.semantic_candidates',return_value=[
                {'actual':col,'status':'SEMANTIC_REVIEW','rank_score':.95,'field_similarity':.99,
                 'factor':0,'evidence':'synthetic high similarity','semantic_risk_flags':[]} ]):
                self.assertEqual(resolve(query,[col])['status'],'MISSING')

    def test_transferred_feedback_cannot_restore_rejected_attribute(self):
        shared={('feedbackdate','revieweddate'):[{'domain':'OTHER','object_key':'other','decision':'APPROVED'}]}
        result=field_suggestions([{'column_name':'ReviewedDate'}],'Feedback Date',
                                 include_semantic=False,shared_feedback=shared)
        self.assertEqual(result,[])

    def test_notes_do_not_override_label_event_and_formula_remains_review(self):
        self.assertEqual(_candidate_facet_conflict('Resubmit Date (Feedback Date logs)','ReviewedDate'),
                         'WORKFLOW_EVENT_FAMILY_CONFLICT')
        self.assertIsNone(_candidate_facet_conflict('Lead Time (Feedback Date - Request Date)','LeadTime'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real-model',action='store_true')
    args,remaining=parser.parse_known_args();REAL_MODEL=args.real_model
    if REAL_MODEL and not semantic_status()['ready']:
        raise SystemExit('Local model unavailable: '+semantic_status()['reason'])
    unittest.main(argv=[__file__,*remaining],verbosity=2)
