"""Phase 2 adapter: baseline serialization, repeated SSH/simulation, explicit fallback."""
from pathlib import Path
from .core import legacy_run, find_new_run, ssh_preflight


def run(dataset: Path, base: Path, config: dict):
    base.mkdir(parents=True, exist_ok=True)
    remote = config.get('remote') or ''
    requested = config.get('transfer_mode', 'auto')
    online = requested != 'simulated' and ssh_preflight(remote, int(config.get('ssh_port', 22)))
    if requested == 'ssh' and not online:
        raise RuntimeError('Strict SSH requested but Phase 2 SSH preflight failed; simulation prohibited.')
    if requested != 'simulated' and not online and not config.get('fallback_simulated', True):
        raise RuntimeError('Phase 2 SSH preflight failed and simulation fallback is disabled.')
    mode = 'ssh' if online else 'simulated'
    reason = 'ssh preflight failed; switched to simulation' if requested != 'simulated' and not online else ''
    print(f'NETWORK: Phase 2 mode={mode}; requested={requested}; reason={reason or "none"}', flush=True)
    argv = [str(dataset), '--transfer-mode', mode, '--packaging-runs', str(config.get('packaging_runs',3)),
            '--transfer-runs', str(config.get('phase2_transfer_trials',10)),
            '--repeat-threshold-seconds', str(config.get('phase2_repeat_threshold_seconds',10)),
            '--bandwidth-mbps', str(config.get('bandwidth_mbps',100)), '--output-dir', str(base)]
    if mode == 'ssh':
        user, host = remote.split('@', 1)
        argv += ['--ssh-transport', config.get('ssh_transport','scp'), '--host', host, '--user', user, '--port', str(config.get('ssh_port',22)),
                 '--remote-dir', config.get('remote_dir','/tmp/thesis_transfer/phase6')]
    try:
        legacy_run('02_transfer_benchmark.py', argv, base/'phase2.log')
    except RuntimeError:
        if requested == 'ssh' or mode != 'ssh' or not config.get('fallback_simulated', True):
            raise
        mode = 'simulated'
        reason = 'actual SSH run failed; re-ran complete phase2 in simulation mode'
        print(f'WARNING: NETWORK FALLBACK Phase 2: {reason}', flush=True)
        sim = [str(dataset), '--transfer-mode', 'simulated',
               '--packaging-runs', str(config.get('packaging_runs',3)),
               '--transfer-runs', str(config.get('phase2_transfer_trials',10)),
               '--repeat-threshold-seconds', str(config.get('phase2_repeat_threshold_seconds',10)),
               '--bandwidth-mbps', str(config.get('bandwidth_mbps',100)), '--output-dir',str(base)]
        legacy_run('02_transfer_benchmark.py', sim, base/'phase2_simulated.log')
    folder = find_new_run(base, 'transfer_benchmark.csv')
    return {'run': str(folder), 'mode': mode, 'fallback_reason': reason,
            'artifacts': [str(folder/'transfer_benchmark.csv'), str(folder/'transfer_trials.csv'),
                          str(folder/'transfer_metadata.json'),
                          *map(str,folder.glob('transport_comparison.csv')),
                          *(str(p) for p in (folder/'artifacts').glob('*') if config.get('paired_transport_studies') and p.is_file())]}
