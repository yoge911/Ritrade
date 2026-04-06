import { useState, useEffect } from 'react';
import { api } from '../../api/rest';
import { useDashboard } from '../../context/DashboardContext';
import { StatusBadge } from '../ui/StatusBadge';
import { Spinner } from '../ui/Spinner';
import { buildArchivePeriodOptionLabel, formatEventTimeMs } from '../../utils/format';
import type { ArchivePeriod, CalibrationSnapshot } from '../../types/models';

const ARCHIVE_HOURS_OPTIONS = [1, 2, 3, 4, 5, 6];

export function CalibrationPanel() {
  const { calibrationState, refreshCalibrationState, updateCalibrationState } = useDashboard();
  
  const [periods, setPeriods] = useState<ArchivePeriod[]>([]);
  const [selectedPeriodId, setSelectedPeriodId] = useState<string>('');
  const [archiveHours, setArchiveHours] = useState<number>(2);
  
  const [displayedSnapshot, setDisplayedSnapshot] = useState<CalibrationSnapshot | null>(null);
  const [displayedSnapshotStatus, setDisplayedSnapshotStatus] = useState<'preview' | 'active' | null>(null);
  const [displayedPeriodId, setDisplayedPeriodId] = useState<string>('');
  const [displayedArchiveHours, setDisplayedArchiveHours] = useState<number>(2);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [activating, setActivating] = useState(false);
  const [errorNotice, setErrorNotice] = useState('');
  const [successNotice, setSuccessNotice] = useState('');

  useEffect(() => {
    async function init() {
      try {
        const data = await api.getCalibrationPeriods();
        setPeriods(data);
        if (data.length > 0 && !selectedPeriodId) {
          setSelectedPeriodId(calibrationState?.active_archive_period_id || data[data.length - 1].period_id);
        }
      } catch (e) {
        console.error('Failed to load periods', e);
      }
    }
    init();
  }, [calibrationState?.active_archive_period_id]); // eslint-disable-line

  useEffect(() => {
    async function loadActiveSnapshot() {
      if (displayedSnapshot) {
        return;
      }
      try {
        const snapshot = await api.getActiveSnapshot();
        if (!snapshot) {
          return;
        }
        setDisplayedSnapshot(snapshot);
        setDisplayedSnapshotStatus('active');
        setDisplayedPeriodId(calibrationState?.active_archive_period_id || calibrationState?.active_run_id || '');
        setDisplayedArchiveHours(calibrationState?.active_archive_hours || archiveHours);
      } catch (e) {
        console.error('Failed to load active calibration snapshot', e);
      }
    }

    loadActiveSnapshot();
  }, [
    archiveHours,
    calibrationState?.active_archive_hours,
    calibrationState?.active_archive_period_id,
    calibrationState?.active_run_id,
    displayedSnapshot,
  ]);

  const handleModeToggle = async () => {
    try {
      const currentMode = calibrationState?.activation_mode || 'auto';
      const newMode = currentMode === 'auto' ? 'manual' : 'auto';
      const result = await api.setCalibrationMode(newMode, archiveHours);
      updateCalibrationState(result.state);
      if (result.snapshot) {
        setDisplayedSnapshot(result.snapshot);
        setDisplayedSnapshotStatus('active');
        setDisplayedPeriodId(result.state.active_archive_period_id || result.state.active_run_id || '');
        setDisplayedArchiveHours(result.state.active_archive_hours || archiveHours);
      } else if (newMode === 'manual') {
        await refreshCalibrationState();
      }
      setSuccessNotice(`Calibration mode set to ${newMode}`);
      if (result.auto_error) {
        setErrorNotice(result.auto_error);
      }
    } catch (e: any) {
      setErrorNotice(e.message || 'Failed to toggle mode');
    }
  };

  const handlePreview = async () => {
    if (!selectedPeriodId) return;
    setLoadingPreview(true);
    setErrorNotice('');
    setSuccessNotice('');
    try {
      const snap = await api.previewCalibration(selectedPeriodId, archiveHours);
      if ((snap as any).error) throw new Error((snap as any).error);
      setDisplayedSnapshot(snap);
      setDisplayedSnapshotStatus('preview');
      setDisplayedPeriodId(selectedPeriodId);
      setDisplayedArchiveHours(archiveHours);
      setSuccessNotice('Computed preview successfully.');
    } catch (e: any) {
      setErrorNotice(e.message || 'Compute failed');
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleActivate = async () => {
    if (!selectedPeriodId) return;
    setActivating(true);
    setErrorNotice('');
    setSuccessNotice('');
    try {
      const res = await api.activateCalibration(selectedPeriodId, archiveHours);
      if ((res as any).error) throw new Error((res as any).error);
      updateCalibrationState(res.state);
      setDisplayedSnapshot(res.snapshot);
      setDisplayedSnapshotStatus('active');
      setDisplayedPeriodId(selectedPeriodId);
      setDisplayedArchiveHours(archiveHours);
      setSuccessNotice('Activated successfully.');
    } catch (e: any) {
      setErrorNotice(e.message || 'Activation failed');
    } finally {
      setActivating(false);
    }
  };

  const isAuto = calibrationState?.activation_mode === 'auto';
  
  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 600 }}>Calibration Periods</h2>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
        {periods.length > 0 ? (
          <div style={{ display: 'flex', gap: '1rem', flex: 1 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', flex: 2 }}>
              <label className="text-muted text-xs">Archive Period</label>
              <select 
                className="select-input" 
                value={selectedPeriodId} 
                onChange={e => setSelectedPeriodId(e.target.value)}
              >
                {[...periods].reverse().map(p => (
                  <option key={p.period_id} value={p.period_id}>
                    {buildArchivePeriodOptionLabel(p.nominal_end_time, p.effective_end_time)}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', flex: 1 }}>
              <label className="text-muted text-xs">Archive Hours</label>
              <select 
                className="select-input" 
                value={archiveHours} 
                onChange={e => setArchiveHours(Number(e.target.value))}
              >
                {ARCHIVE_HOURS_OPTIONS.map(h => (
                  <option key={h} value={h}>{h} hour{h > 1 ? 's' : ''}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ flex: 1 }}>Waiting for archive periods...</div>
        )}

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button className="btn" onClick={handleModeToggle}>
            Toggle Auto/Manual
          </button>
          <button className="btn" onClick={handlePreview} disabled={loadingPreview || !selectedPeriodId}>
            {loadingPreview ? <Spinner size={16} /> : 'Preview Thresholds'}
          </button>
          <button className="btn btn-primary" onClick={handleActivate} disabled={activating || !selectedPeriodId}>
            {activating ? <Spinner size={16} /> : 'Activate Selected'}
          </button>
        </div>
      </div>

      {errorNotice && <div className="text-sm" style={{ color: 'var(--signal-hot-text)' }}>{errorNotice}</div>}
      {successNotice && <div className="text-sm" style={{ color: '#4ade80' }}>{successNotice}</div>}

      {displayedSnapshot && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
             <StatusBadge
               label={displayedSnapshotStatus === 'active' ? 'ACTIVE RUNTIME' : 'COMPUTED PREVIEW'}
               variant={displayedSnapshotStatus === 'active' ? 'hot' : 'warm'}
             />
            <StatusBadge label={`Archive Window ${displayedArchiveHours}h`} variant="cold" />
            {calibrationState && (
              <StatusBadge
                label={`Mode ${calibrationState.activation_mode.toUpperCase()}`}
                variant={isAuto ? 'hot' : 'warm'}
              />
            )}
          </div>
          {displayedPeriodId && (
            <div className="text-xs text-muted">
              Threshold Id: {displayedPeriodId} ({displayedArchiveHours}h)
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
            {displayedSnapshot.tickers.map((t) => (
               <div key={t.ticker} className="glass-panel" style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h4 style={{ margin: 0 }}>{t.ticker}</h4>
                    <StatusBadge label={t.entry_status === 'reused' ? 'Reused' : 'Fresh'} variant={t.entry_status === 'reused' ? 'warm' : 'hot'} />
                  </div>
                  <div className="text-xs text-muted">
                    {formatEventTimeMs(t.source.first_event_time_ms)} &rarr; {formatEventTimeMs(t.source.last_event_time_ms)}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.75rem' }}>
                    <div className="text-muted">Samples</div><div className="font-mono text-right">{t.sample_count}</div>
                    <div className="text-muted">Vol Bounds</div><div className="font-mono text-right">{t.thresholds.min_volume_threshold.toFixed(2)} - {t.thresholds.max_volume_threshold.toFixed(2)}</div>
                    <div className="text-muted">Trd Bounds</div><div className="font-mono text-right">{t.thresholds.min_trade_count} - {t.thresholds.max_trade_count}</div>
                  </div>
               </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
