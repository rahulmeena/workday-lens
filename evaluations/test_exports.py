"""Checks for public-data boundaries and benchmark counting semantics."""
import csv
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from evaluations.export_results import aggregate_judge, base_model, export, public_name
from evaluations.export_prompt_experiment import export as export_prompt
from evaluations.judge_prompts import build_prompt, output_schema


class ExportTests(unittest.TestCase):
    def test_aliases_and_variants_do_not_inflate_base_model_count(self):
        self.assertEqual(public_name('/private/cache/HRM-Text-1B-Q5_K_M.gguf'), 'sinimiini/HRM-Text-1B-GGUF:Q5_K_M')
        self.assertEqual(base_model('unsloth/Qwen3.5-4B-GGUF:Q4_K_M'), base_model('Qwen3.5-4B-Q4_K_M+generic_v8'))
        self.assertEqual(base_model('mlx-community/Qwen3-VL-8B-Instruct-5bit'), base_model('mlx-community/Qwen3-VL-8B-Instruct-8bit'))
        self.assertNotEqual(base_model('Qwen3-VL-8B-Instruct'), base_model('Qwen3-VL-8B-Thinking'))
        with self.assertRaises(ValueError):
            public_name('/private/unreviewed/model.gguf')

    def test_missing_judge_scores_are_not_zero_scores(self):
        result = aggregate_judge([
            {'status': 'succeeded', 'scores': {'final_score': 0}},
            {'status': 'succeeded', 'scores': {}},
            {'status': 'failed', 'scores': {'final_score': 100}},
        ], ['final_score', 'faithfulness_score'])
        self.assertEqual(result['final_score'], 0)
        self.assertEqual(result['final_score_n'], 1)
        self.assertIsNone(result['faithfulness_score'])
        self.assertEqual(result['failed'], 1)

    def test_export_excludes_activity_text_paths_and_judge_explanations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'private.db'
            con = sqlite3.connect(database)
            con.executescript('''
                CREATE TABLE llm_benchmark_generations (id,session_id,generation_role,provider,model_name,modality,level,source_id,status,prompt_tokens,completion_tokens,total_tokens,latency_ms,estimated_cost,json_parse_success,schema_validation_success,hyperparameters_json,created_at,updated_at,summary_text,input_snapshot_json);
                CREATE TABLE llm_benchmark_metrics (generation_id,metric_type,metric_name,value_float,value_text,details_json);
                CREATE TABLE llm_benchmark_judge_runs (id,config_json);
                CREATE TABLE llm_benchmark_judge_results (id,run_id,candidate_generation_id,level,source_id,judge_model,status,parsed_output_json);
            ''')
            sentinel = 'PRIVATE_ACTIVITY_DO_NOT_PUBLISH'
            con.execute('INSERT INTO llm_benchmark_generations VALUES (' + ','.join('?' * 21) + ')', (
                'g1', 's1', 'candidate', 'llama_cpp', 'Qwen3.5-4B-Q4_K_M+generic_v8', 'text', '1m', sentinel,
                'succeeded', 10, 20, 30, 100, None, 1, 1,
                json.dumps({'cache_root': sentinel, 'chip': 'Test chip'}), '2026-01-01', '2026-01-02', sentinel, sentinel))
            con.execute('INSERT INTO llm_benchmark_metrics VALUES (?,?,?,?,?,?)', ('g1', 'runtime', 'latency_ms', 100, sentinel, sentinel))
            con.execute('INSERT INTO llm_benchmark_judge_runs VALUES (?,?)', ('r1', json.dumps({'judge_schema': 'workday_lens_llm_judge_eval_v1', 'secret': sentinel})))
            con.execute('INSERT INTO llm_benchmark_judge_results VALUES (?,?,?,?,?,?,?,?)', ('j1', 'r1', 'g1', '1m', sentinel, 'gpt-5.4-mini', 'succeeded', json.dumps({'final_score': 75, 'rationale': sentinel, 'mood_evidence': sentinel})))
            con.commit()
            con.close()
            with redirect_stdout(io.StringIO()):
                export(database, root / 'public')
            for path in (root / 'public').iterdir():
                self.assertNotIn(sentinel, path.read_text())
            data = json.loads((root / 'public/summary.json').read_text())
            self.assertEqual(data['generation_records'], 1)
            self.assertEqual(data['judge_statuses']['succeeded'], 1)

    def test_prompt_export_checks_cohorts_and_omits_raw_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'private.jsonl'
            source.write_text('\n'.join(json.dumps({'variant': v, 'source_id': s, 'combined': .4, 'parse_ok': True, 'prompt_compacted': False, 'summary': 'PRIVATE_SENTINEL'}) for v, s in [('default', 'a'), ('new', 'b')]))
            export_prompt(source, root / 'out.csv', 'synthetic-test')
            text = (root / 'out.csv').read_text()
            self.assertNotIn('PRIVATE_SENTINEL', text)
            rows = list(csv.DictReader(text.splitlines()))
            self.assertEqual(rows[0]['same_source_set'], 'False')
            self.assertEqual(rows[0]['predicted_per_second'], '')

    def test_rubrics_keep_reference_and_source_evidence_separate(self):
        reference = build_prompt('reference', {'candidate': {'summary': 'Synthetic example'}})
        source = build_prompt('source-grounded', {'source': {'transcript': 'Synthetic example'}})
        self.assertIn('silver reference', reference)
        self.assertIn('Do not use the GPT-5.4 silver label', source)
        self.assertEqual(output_schema('source-grounded')['properties']['final_score']['maximum'], 100)
        with self.assertRaises(ValueError):
            build_prompt('../private', {})

    def test_public_totals_and_checksums_reconcile(self):
        root = Path(__file__).parent / 'results'
        summary = json.loads((root / 'summary.json').read_text())
        for name, digest in summary['csv_sha256'].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, name)
        with (root / 'configurations.csv').open() as handle:
            configs = list(csv.DictReader(handle))
        with (root / 'judge-runs.csv').open() as handle:
            runs = list(csv.DictReader(handle))
        self.assertEqual(len(configs), summary['configurations'])
        self.assertEqual(sum(int(r['records']) for r in configs), summary['generation_records'])
        for status in ['succeeded', 'failed']:
            self.assertEqual(sum(int(r[status]) for r in configs), summary['generation_statuses'][status])
            self.assertEqual(sum(int(r[status]) for r in runs), summary['judge_statuses'][status])
        self.assertEqual(len({r['base_model'] for r in configs if r['kind']=='local_weights'}), summary['local_model_identities'])


if __name__ == '__main__':
    unittest.main()
