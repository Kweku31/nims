import json
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Dashboard, Handler, REPORTS, ThreadingHTTPServer, phase_summary, read_table, preview_csv, MAX_UPLOAD_BYTES


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = self.root/'pipeline'; self.pipeline.mkdir()
        self.output = self.root/'output'; self.output.mkdir()
        self.app = Dashboard(self.pipeline, [self.output], self.root/'data')

    def snapshot(self, name='20261115_120000_UTC_one'):
        folder = self.output/'results'/name; folder.mkdir(parents=True)
        meta = {'run_id': 'a'*20, 'input': '/example/synthetic.csv', 'network_modes': ['simulated_ideal']}
        (folder/'run_manifest.json').write_text(json.dumps(meta))
        for file in REPORTS[:-1]:
            (folder/file).write_text('method,value\npca,1\n' if file.endswith('.csv') else '# Report')
        return folder

    def test_discovers_distinct_timestamp_snapshots_and_safe_report_paths(self):
        first = self.snapshot(); second = self.snapshot('20261115_120500_UTC_two')
        runs = self.app.run_list()
        self.assertEqual(len(runs), 2)
        self.assertNotEqual(runs[0]['id'], runs[1]['id'])
        detail = self.app.detail(runs[0]['id'])
        self.assertEqual(len(detail['files']), 6)
        self.assertEqual(len(detail['phases']), 6)
        self.assertEqual(detail['rankings'][0]['value'], 1)
        with self.assertRaises(FileNotFoundError):
            self.app.detail('../../etc/passwd')

    def test_csv_nonfinite_values_are_json_safe(self):
        path = self.root/'table.csv'
        path.write_text('score,verified,missing\ninf,False,\n-1.2,True,NaN\n')
        rows = read_table(path)
        self.assertIsNone(rows[0]['score'])
        self.assertIs(rows[0]['verified'], False)
        self.assertEqual(rows[1]['score'], -1.2)
        json.dumps(rows, allow_nan=False)

    def test_dataset_preview_preserves_values_and_paginates(self):
        file = self.root/'records.csv'
        file.write_text('patient_id,note,empty\n001,"line one\nline two",\n002,"a,b",NA\n003,last,0\n')
        first = preview_csv(file,0,2)
        self.assertEqual(first['rows'][0], ['001','line one\nline two',''])
        self.assertEqual(first['rows'][1], ['002','a,b','NA'])
        self.assertTrue(first['has_more'])
        second = preview_csv(file,2,2)
        self.assertEqual(second['rows'], [['003','last','0']])
        self.assertFalse(second['has_more'])
        for offset,limit in [(-1,25),(0,101),(0,0)]:
            with self.assertRaises(ValueError): preview_csv(file,offset,limit)

    def test_upload_is_local_unique_and_preserves_exact_bytes(self):
        data=b'patient_id,HR\r\n001,80\r\n'
        first=self.app.upload(io.BytesIO(data),'../../records.csv',len(data))
        second=self.app.upload(io.BytesIO(data),'../../records.csv',len(data))
        self.assertNotEqual(first['path'],second['path'])
        self.assertTrue(Path(first['path']).is_relative_to(self.app.data/'uploads'))
        self.assertEqual(Path(first['path']).read_bytes(),data)
        self.assertEqual(first['rows'][0][0],'001')

    def test_invalid_uploads_clean_up_partial_files(self):
        for data,name,length in [(b'x','bad.txt',1),(b'x','bad.csv',MAX_UPLOAD_BYTES+1),
                                 (b'', 'empty.csv',0),(b'a\n\xff\n','bad.csv',4),(b'x','short.csv',10)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.app.upload(io.BytesIO(data),name,length)
        self.assertEqual(list((self.app.data/'uploads').glob('*/*.csv')),[])

    def test_run_dataset_preview_detects_changed_source(self):
        folder=self.snapshot()
        source=self.root/'input.csv'; source.write_text('id,x\n001,5\n')
        meta=json.loads((folder/'run_manifest.json').read_text())
        meta.update(input=str(source),input_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        (folder/'run_manifest.json').write_text(json.dumps(meta))
        key=self.app.run_list()[0]['id']
        self.assertTrue(self.app.dataset_preview(key)['matches_run_input'])
        source.write_text('id,x\n001,7\n')
        self.assertFalse(self.app.dataset_preview(key)['matches_run_input'])

    def test_phase_one_redundancy_lists_saved_pairs_and_handles_missing_files(self):
        folder=self.snapshot(); phase=self.root/'phase1';phase.mkdir()
        pairs=[('Unit1','Unit2'),('time','ICULOS'),('Bilirubin_direct','Bilirubin_total'),('Hct','Hgb')]
        (phase/'redundant_pairs.csv').write_text('column_a,column_b,pearson_r,pairwise_n\n'+
            ''.join(f'{a},{b},0.96,40\n' for a,b in pairs))
        meta=json.loads((folder/'run_manifest.json').read_text());meta['phase_directories']={'phase1':str(phase)}
        (folder/'run_manifest.json').write_text(json.dumps(meta))
        key=self.app.run_list()[0]['id']
        detail=self.app.phase_details(key,'phase1')
        group=next(g for g in detail['groups'] if g['id']=='redundant')
        self.assertEqual([(r['column_a'],r['column_b']) for r in group['rows']],pairs)
        self.assertIn('not a list of removed',group['description'])
        self.assertFalse(next(g for g in detail['groups'] if g['id']=='columns')['available'])
        (phase/'redundant_pairs.csv').unlink()
        self.assertFalse(next(g for g in self.app.phase_details(key,'phase1')['groups'] if g['id']=='redundant')['available'])
        with self.assertRaises(ValueError):self.app.phase_details(key,'../../private')

    def test_phase_three_lists_decisions_for_the_selected_variant(self):
        folder=self.snapshot(); phase=self.root/'phase3';variant=phase/'FS_95_clinical_review';variant.mkdir(parents=True)
        (variant/'feature_selection_report.csv').write_text('column,status,reason\nSparseLab,removed,missingness\nLactate,retained,clinical review\n')
        meta=json.loads((folder/'run_manifest.json').read_text());meta['phase_directories']={'phase3':str(phase)}
        (folder/'run_manifest.json').write_text(json.dumps(meta))
        detail=self.app.phase_details(self.app.run_list()[0]['id'],'phase3')
        group=next(g for g in detail['groups'] if g['id']=='selection-FS_95_clinical_review')
        self.assertEqual(group['rows'][0]['status'],'removed')
        self.assertEqual(group['rows'][1]['column'],'Lactate')

    def test_phase_status_aggregates_configurations(self):
        phases = phase_summary({'stages': {'phase4_original': {'status':'complete','seconds':2},
                                            'phase4_selected': {'status':'running'},
                                            'phase6_bad': {'status':'failed','error':'hash mismatch'}}})
        self.assertEqual(phases[3]['status'], 'running')
        self.assertEqual(phases[3]['completed'], 1)
        self.assertEqual(phases[3]['seconds'], 2)
        self.assertEqual(phases[5]['status'], 'failed')

    def test_launch_validation_never_invokes_shell(self):
        dataset = self.root/'input.csv'; dataset.write_text('x\n1\n')
        for bad in ({'dataset':'not-real.csv'}, {'dataset':str(dataset),'transfer_mode':'auto'},
                    {'dataset':str(dataset),'transfer_mode':'ssh','remote':'host; echo unsafe'},
                    {'dataset':str(dataset),'k':[True]}, {'dataset':str(dataset),'ae_max_iter':0},
                    *[{'dataset':str(dataset),'patient_coverage_min':v} for v in [True,0.65,'NaN',-1,101]]):
            with self.subTest(bad=bad), patch('server.subprocess.Popen') as process:
                with self.assertRaises(ValueError): self.app.launch(bad)
                process.assert_not_called()

    def test_patient_coverage_choices_are_written_to_the_pipeline_config(self):
        self.fake_pipeline()
        data=self.root/'data.csv';data.write_text('patient_id,HR\n001,80\n')
        for supplied,expected in [(0.75,0.75),(80,0.80),('90%',0.90)]:
            with self.subTest(coverage=supplied), patch.object(self.app,'settings',return_value={'missing_dependencies':[]}):
                job=self.app.launch({'dataset':str(data),'k':[2],'patient_coverage_min':supplied})
                self.app.processes[job['id']].wait(timeout=10)
                config=json.loads((self.app.jobs/job['id']/'config.json').read_text())
                self.assertEqual(config['patient_coverage_min'],expected)
                self.assertEqual(config['phase2_transfer_trials'],10)
                self.assertEqual(config['phase2_repeat_threshold_seconds'],10.0)
                self.assertEqual(config['transfer_trials'],10)
                self.assertEqual(config['phase6_repeat_threshold_seconds'],10.0)
                self.assertEqual(config['topsis_weights'],[1/7]*7)

    def test_custom_weights_are_validated_before_launch_and_saved(self):
        self.fake_pipeline()
        data=self.root/'weights.csv'; data.write_text('patient_id,HR\n001,80\n')
        for weights in [[1]*6, [0]*7, [10]*7, [True,0,0,0,0,0,0],
                        [float('nan'),1,0,0,0,0,0], [-1,101,0,0,0,0,0]]:
            with self.subTest(weights=weights), patch('server.subprocess.Popen') as process:
                with self.assertRaises(ValueError):
                    self.app.launch({'dataset':str(data),'topsis_weights':weights})
                process.assert_not_called()
        with patch.object(self.app,'settings',return_value={'missing_dependencies':[]}):
            job=self.app.launch({'dataset':str(data),'topsis_weights':[1,19,20,20,20,20,0]})
            self.app.processes[job['id']].wait(timeout=10)
            config=json.loads((self.app.jobs/job['id']/'config.json').read_text())
            self.assertEqual(config['topsis_weights'],[.01,.19,.2,.2,.2,.2,0])

    def test_missing_source_and_missing_api_are_distinct(self):
        self.snapshot()
        with self.assertRaisesRegex(ValueError,'source CSV is missing at its saved location'):
            self.app.dataset_preview(self.app.run_list()[0]['id'])
        self.assertEqual(self.app.settings()['api_version'],4)

    def test_optional_settings_saved_with_explicit_percentage_units(self):
        self.fake_pipeline()
        data=self.root/'options.csv'; data.write_text('patient_id,HR\n001,80\n')
        body={'dataset':str(data), 'ssh_transport':'both','transfer_mode':'ssh','remote':'u@fake','feature_sets':'clinical', 'missingness_thresholds':'70, 85',
              'packaging_runs':'1', 'phase2_transfer_trials':'4', 'transfer_trials':6,
              'phase2_repeat_threshold_seconds':12, 'phase6_repeat_threshold_seconds':15,
              'ae_backend':'gpu', 'ae_batch_size':'4096', 'ae_cpu_threads':2, 'ae_progress_interval':1,
              'ae_tol':.001, 'ae_patience':8, 'seed':17, 'correlation_action':'drop',
              'correlation_threshold':90, 'clinically_protected':'HR',
              'minimum_feature_retention_pct':80, 'maximum_new_violation_pct':.5,
              'delivery_scenarios':['fresh_data'], 'model_reuse_count':2,
              'violation_sensitivity':'0, 0.5, 1', 'continue_independent_errors':False}
        with patch.object(self.app,'settings',return_value={'missing_dependencies':[]}):
            job=self.app.launch(body)
            self.app.processes[job['id']].wait(timeout=10)
        config=json.loads((self.app.jobs/job['id']/'config.json').read_text())
        self.assertEqual(config['ssh_transport'],'both')
        self.assertEqual(config['feature_sets'],['FS_85_clinical_review'])
        self.assertEqual(config['packaging_runs'],1)
        self.assertEqual(config['phase2_transfer_trials'],4)
        self.assertEqual(config['transfer_trials'],6)
        self.assertEqual(config['ae_tol'],.001)
        self.assertEqual(config['ae_patience'],8)
        self.assertEqual(config['ae_backend'],'gpu')
        self.assertEqual(config['ae_batch_size'],4096)
        self.assertEqual(config['ae_cpu_threads'],2)
        self.assertEqual(config['ae_progress_interval'],1)
        self.assertEqual(config['maximum_new_violation_pct'],'0.5%')
        self.assertEqual(config['minimum_feature_retention_pct'],'80%')
        self.assertEqual(config['clinically_protected'],['HR'])
        self.assertEqual(config['delivery_scenarios'],['fresh_data'])
        self.assertEqual(config['violation_sensitivity'],['0%','0.5%','1%'])
        self.assertFalse(config['continue_independent_errors'])

    def test_invalid_optional_settings_never_start_a_process(self):
        data=self.root/'options.csv'; data.write_text('x\n1\n')
        invalid=[{'ae_backend':'auto'}, {'ae_batch_size':0}, {'ae_cpu_threads':-1},
                 {'ae_progress_interval':float('nan')}, {'ae_batch_size':True}, {'packaging_runs':0},{'transfer_trials':True},{'ae_tol':float('nan')},
                 {'correlation_threshold':101},{'missingness_thresholds':'80,80.1'},
                 {'delivery_scenarios':[]},{'neighbor_k':'10'}, {'distance_samples':5},
                 {'maximum_new_violation_pct':-1},{'continue_independent_errors':'yes'},
                 {'clinically_protected':'HR,,Resp'},{'correlation_action':'delete'}]
        for options in invalid:
            with self.subTest(options=options), patch('server.subprocess.Popen') as process:
                with self.assertRaises(ValueError):self.app.launch({'dataset':str(data),**options})
                process.assert_not_called()

    def fake_pipeline(self, wait=False):
        # A real subprocess exercising the launcher; it never imports the research engine or SSH.
        script = '''import json,sys,time
from pathlib import Path
config=json.loads(Path(sys.argv[2]).read_text())
out=Path(config['output_dir']);out.mkdir(parents=True,exist_ok=True)
(out/'pipeline.log').write_text('Synthetic launcher test\\n')
'''
        if wait:
            script += 'time.sleep(30)\n'
        else:
            script += "(out/'run_status.json').write_text(json.dumps({'status':'complete'}))\n"
        (self.pipeline/'run_thesis.py').write_text(script)
        (self.pipeline/'receiver_reconstruct.py').write_text('# Test receiver fixture\n')

    def test_launch_process_and_completion(self):
        self.fake_pipeline()
        data = self.root/'data.csv'; data.write_text('x\n1\n')
        with patch.object(self.app, 'settings', return_value={'missing_dependencies':[]}):
            job = self.app.launch({'dataset':str(data),'k':[2]})
        self.app.processes[job['id']].wait(timeout=10)
        for _ in range(30):
            if self.app.run_list()[0]['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(self.app.run_list()[0]['status'],'complete')
        config = json.loads((self.app.jobs/job['id']/'config.json').read_text())
        self.assertFalse(config['fallback_simulated'])
        self.assertEqual(config['transfer_mode'],'simulated')
        self.assertIn('Synthetic launcher', self.app.logs(job['id'])['text'])

    def test_resume_reuses_job_config_output_and_keeps_audit_history(self):
        self.fake_pipeline()
        data = self.root/'data.csv'; data.write_text('x\n1\n')
        with patch.object(self.app, 'settings', return_value={'missing_dependencies':[]}):
            job = self.app.launch({'dataset':str(data),'k':[2], 'transfer_mode':'ssh',
                                   'remote':'user@fake', 'ssh_port':2222, 'ssh_max_attempts':4,
                                   'ssh_transfer_timeout':600})
            self.app.processes[job['id']].wait(timeout=10)
            for _ in range(100):
                if json.loads((self.app.jobs/job['id']/'job.json').read_text())['status'] != 'running': break
                time.sleep(.01)
            folder = self.app.jobs/job['id']
            original_config = (folder/'config.json').read_bytes()
            config = json.loads(original_config)
            self.assertEqual(config['ssh_port'],2222)
            self.assertEqual(config['ssh_max_attempts'],4)
            self.assertEqual(config['ssh_transfer_timeout'],600)
            self.assertFalse(config['fallback_simulated'])
            marker = folder/'output/completed-checkpoint.txt'; marker.write_text('retained')
            failed = json.loads((folder/'job.json').read_text())
            failed.update(status='failed', error='Connection lost', exit_code=1)
            (folder/'job.json').write_text(json.dumps(failed))
            (folder/'output/network_status.json').write_text(json.dumps({'status':'needs_attention'}))
            self.assertEqual(self.app.detail(job['id'])['network']['status'],'needs_attention')
            resumed = self.app.resume(job['id'])
            self.assertEqual(resumed['id'],job['id'])
            self.assertEqual(resumed['resume_count'],1)
            self.assertEqual(resumed['previous_invocations'][0]['error'],'Connection lost')
            self.assertEqual((folder/'config.json').read_bytes(),original_config)
            self.assertEqual(marker.read_text(),'retained')
            self.assertIn('RESUME', (folder/'launcher.log').read_text())
            self.app.processes[job['id']].wait(timeout=10)
            for _ in range(100):
                if json.loads((folder/'job.json').read_text())['status'] != 'running': break
                time.sleep(.01)
            with self.assertRaisesRegex(ValueError,'Only a failed'):
                self.app.resume(job['id'])

    def test_restart_does_not_launch_over_a_surviving_worker(self):
        self.fake_pipeline(wait=True)
        data=self.root/'data.csv'; data.write_text('x\n1\n')
        with patch.object(self.app,'settings',return_value={'missing_dependencies':[]}):
            job=self.app.launch({'dataset':str(data),'k':[2]})
        try:
            restarted=Dashboard(self.pipeline,[self.output],self.app.data)
            self.assertTrue(restarted.has_active_worker())
            with self.assertRaisesRegex(ValueError,'already running'):
                restarted.resume(job['id'])
        finally:
            self.app.cancel(job['id'])
            self.app.processes[job['id']].wait(timeout=10)

    def test_invalid_ssh_recovery_inputs_are_rejected(self):
        data = self.root/'data.csv'; data.write_text('x\n1\n')
        for invalid in [{'ssh_max_attempts':0}, {'ssh_max_attempts':True}, {'ssh_transfer_timeout':float('inf')},
                        {'ssh_port':65536}, {'remote_dir':'/tmp/../etc'}, {'remote_dir':'/tmp/x;echo'}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.app.launch({'dataset':str(data), **invalid})

    def test_cancel_and_single_active_job(self):
        self.fake_pipeline(wait=True)
        data = self.root/'data.csv'; data.write_text('x\n1\n')
        with patch.object(self.app, 'settings', return_value={'missing_dependencies':[]}):
            job = self.app.launch({'dataset':str(data),'k':[2]})
            with self.assertRaisesRegex(ValueError,'already running'):
                self.app.launch({'dataset':str(data),'k':[2]})
        self.app.cancel(job['id'])
        self.app.processes[job['id']].wait(timeout=10)
        self.assertEqual(self.app.detail(job['id'])['status'],'cancelled')

    def test_http_downloads_and_cross_origin_protection(self):
        self.snapshot()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.app = self.app
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with urlopen(base+'/api/runs') as response:
            key = json.load(response)[0]['id']
        with urlopen(base+f'/api/runs/{key}/files/FINAL_REPORT.md') as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.read(), b'# Report')
        with urlopen(base+'/demo.json') as response:
            self.assertTrue(json.load(response)['demo'])
        csv_data=b'id,value\n001,5\n'
        with urlopen(Request(base+'/api/datasets/upload',data=csv_data,headers={'Content-Type':'text/csv','X-Filename':'records.csv'})) as response:
            uploaded=json.load(response)
            self.assertEqual(response.status,201)
        with urlopen(Request(base+'/api/datasets/preview',data=json.dumps({'path':uploaded['path']}).encode(),headers={'Content-Type':'application/json'})) as response:
            self.assertEqual(json.load(response)['rows'][0][0],'001')
        with self.assertRaises(HTTPError) as err:
            urlopen(Request(base+'/api/datasets/upload',data=csv_data,headers={'Content-Type':'text/csv','Origin':'https://elsewhere.example'}))
        self.assertEqual(err.exception.code,403)
        with self.assertRaises(HTTPError) as err:
            urlopen(Request(base+'/api/runs', data=b'{}', headers={'Content-Type':'application/json','Origin':'https://elsewhere.example'}))
        self.assertEqual(err.exception.code, 403)
        with self.assertRaises(HTTPError) as err:
            urlopen(Request(base+'/api/settings', headers={'Host':'outside.example'}))
        self.assertEqual(err.exception.code, 403)
        with self.assertRaises(HTTPError) as err:
            urlopen(base+f'/api/runs/{key}/files/config.json')
        self.assertEqual(err.exception.code, 404)


if __name__ == '__main__': unittest.main()
