"""Resumed review registrations must retain real parent and per-packet bindings."""
import copy
import hashlib
import json
from pathlib import Path
from test_production_labels import NativeSourceReviewTests
from czlake.production_labels import digest, reviewed_records


class ResumedRegistryTests(NativeSourceReviewTests):
    def mixed_parent_pair(self):
        classifier, reviewer, review = self._native_pair()
        reviewer.update(task_path='/root/recovery/reviewer', session_id='native:/root/recovery/reviewer', parent_session_id='recovery-session', spawn_receipt={'task_name': '/root/recovery/reviewer'}, session_binding={'source': 'native:collaboration', 'task_path': '/root/recovery/reviewer', 'parent_session_id': 'recovery-session'})
        review['session_id'] = reviewer['session_id']
        Path(reviewer['output_path']).write_text(json.dumps(review))
        parent_registry = self.base/'recovery-registry.json'
        parent_registry.write_text(json.dumps({'native_parent_task_path': '/root/recovery', 'native_parent_session_id': 'recovery-session', 'assignments': [reviewer]}))
        self.registry['native_parent_registries'] = [{'path': str(parent_registry), 'sha256': hashlib.sha256(parent_registry.read_bytes()).hexdigest()}]
        return classifier, reviewer, review, parent_registry

    def test_original_registry_parent_and_rows_survive_resumed_sibling_review(self):
        classifier, reviewer, review, _ = self.mixed_parent_pair()
        original = copy.deepcopy(classifier)
        result = reviewed_records(self.cards,self.labels,review,self.registry)
        self.assertFalse(result['batch_hold'],result['errors'])
        self.assertEqual(result['counts']['verified'],1)
        self.assertEqual(self.registry['native_parent_task_path'],'/root')
        self.assertEqual(classifier,original)

    def test_parent_context_without_exact_original_registration_is_rejected(self):
        _, reviewer, review, path = self.mixed_parent_pair()
        source = json.loads(path.read_text());source['assignments'][0]['cards_sha256']='0'*64;path.write_text(json.dumps(source))
        # Even a correctly pinned file cannot bless a different assignment row.
        self.registry['native_parent_registries'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])

    def test_mutated_parent_registry_or_missing_parent_receipt_fails(self):
        _, reviewer, review, path = self.mixed_parent_pair()
        path.write_text(path.read_text()+' ')
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])
        self.registry.pop('native_parent_registries')
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])

    def test_one_real_reviewer_can_review_explicitly_registered_disjoint_packets(self):
        classifier, reviewer, review = self._native_pair()
        review2=self._review(self.labels);row2=self._native('reviewer2','independent_review',review2)
        for field in ('task_path','session_id','spawn_receipt','session_binding'):row2[field]=copy.deepcopy(reviewer[field])
        review2['session_id']=reviewer['session_id'];Path(row2['output_path']).write_text(json.dumps(review2))
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])
        self.registry['native_repeated_review_tasks']={reviewer['task_path']:[reviewer['assignment_id'],row2['assignment_id']]}
        for candidate in (review,review2):
            result=reviewed_records(self.cards,self.labels,candidate,self.registry)
            self.assertFalse(result['batch_hold'],result['errors'])
            self.assertEqual(result['counts']['verified'],1)
        self.registry['native_repeated_review_tasks'][reviewer['task_path']].append('invented-assignment')
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])

    def test_review_reuse_never_allows_classifier_role_on_the_same_task(self):
        classifier,reviewer,review=self._native_pair()
        classifier['task_path']=reviewer['task_path'];classifier['session_id']=reviewer['session_id']
        classifier['spawn_receipt']=copy.deepcopy(reviewer['spawn_receipt']);classifier['session_binding']=copy.deepcopy(reviewer['session_binding'])
        self.labels['session_id']=classifier['session_id'];Path(classifier['output_path']).write_text(json.dumps(self.labels))
        review['submission_sha256']=digest(self.labels);reviewer['submission_sha256']=review['submission_sha256'];Path(reviewer['output_path']).write_text(json.dumps(review))
        self.registry['native_repeated_review_tasks']={reviewer['task_path']:[reviewer['assignment_id'],classifier['assignment_id']]}
        self.assertTrue(reviewed_records(self.cards,self.labels,review,self.registry)['batch_hold'])
