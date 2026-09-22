"""Diagnostics; offline tests use temporary databases and fake providers."""

from common.operation_log import LOGGER, configure_logging, emit
from io import StringIO
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient, brief
from workflow import GeminiDeterminationWorker, GeminiIntakeWorker, WorkflowStore
from workflow.development import prepare_development_database
import json
import logging
import tempfile
import test_gemini_workflow as fixtures
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.db'
        prepare_development_database(self.path)

    def test_logs_correlate_decision_without_payloads_or_exception_bodies(self):
        output = StringIO()
        handler = logging.StreamHandler(output)
        old_level = LOGGER.level
        LOGGER.setLevel(logging.INFO); LOGGER.addHandler(handler)
        self.addCleanup(LOGGER.removeHandler,handler)
        self.addCleanup(LOGGER.setLevel,old_level)
        with WorkflowStore(self.path) as store:
            store.create_human_idea('PRIVATE_HUMAN_SENTINEL',command_id='logged')
            GeminiIntakeWorker(store,FakeGeminiClient(brief())).run_once()
            GeminiDeterminationWorker(store,FakeGeminiClient(fixtures.GeminiWorkflowTests.decision(store.catalog()))).run_once()
        emit('test','safe', status='failed', model_id='access_token=SECRET', prompt='PROMPT_SENTINEL', body='BODY_SENTINEL')
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        for forbidden in ('PRIVATE_HUMAN_SENTINEL','PROMPT_SENTINEL','BODY_SENTINEL','SECRET','break the ice'):
            self.assertNotIn(forbidden,output.getvalue())
        decision = next(r for r in lines if r.get('decision_id'))
        self.assertEqual(decision['selected_count'],1)
        self.assertEqual(decision['skipped_count'],2)
        self.assertTrue(decision['job_ids'])
        self.assertTrue(any(r['event']=='model_result' and r.get('model_id') for r in lines))

    def test_rotating_logs_are_bounded_and_do_not_touch_other_files(self):
        root=Path(self.temp.name)/'logs'
        root.mkdir()
        unrelated=root/'evidence.json'
        unrelated.write_text('keep')
        previous=list(LOGGER.handlers); previous_level=LOGGER.level
        # Isolate global logging from the remaining tests.
        LOGGER.handlers=[]
        try:
            configure_logging('test',root=root,max_bytes=1024,backups=2)
            for handler in list(LOGGER.handlers):
                if not hasattr(handler,'baseFilename'):
                    LOGGER.removeHandler(handler)
            for number in range(100):
                emit('test','rotation',record_id=number,status='completed')
            files=list(root.glob('cf-test-*.jsonl*'))
            self.assertLessEqual(len(files),3)
            self.assertTrue(all(p.stat().st_size<=1024 for p in files))
            self.assertEqual(unrelated.read_text(),'keep')
        finally:
            for handler in LOGGER.handlers:
                handler.close()
            LOGGER.handlers=previous
            LOGGER.setLevel(previous_level)
