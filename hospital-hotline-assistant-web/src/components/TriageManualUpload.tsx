import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type TriageManualUploadOut } from '../api';

const POLL_INTERVAL_MS = 3000; // poll every 3 s while status is "processing"
const MAX_FILE_MB = 50;

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

export function TriageManualUpload() {
  const { t } = useTranslation();

  const [current, setCurrent] = useState<TriageManualUploadOut | null | undefined>(undefined);
  const [isDragging, setIsDragging] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial fetch
  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-poll while status is "processing"
  useEffect(() => {
    if (current?.status === 'processing') {
      pollRef.current = setInterval(() => {
        void loadStatus();
      }, POLL_INTERVAL_MS);
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [current?.status]);

  const loadStatus = async () => {
    try {
      const data = await api.getTriageManualStatus();
      setCurrent(data);
    } catch {
      // silently ignore — user may not be logged in yet
    }
  };

  // ── drag-and-drop ──────────────────────────────────────────────────────────
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => setIsDragging(false), []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) validateAndStage(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [current],
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) validateAndStage(file);
    // reset so same file can be chosen again
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const validateAndStage = (file: File) => {
    setUploadError(null);
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadError('Only PDF files are accepted.');
      return;
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      setUploadError(`File too large (max ${MAX_FILE_MB} MB).`);
      return;
    }
    setPendingFile(file);
    // If there's already an existing manual, ask for confirmation before replacing
    if (current) {
      setShowConfirm(true);
    } else {
      void doUpload(file);
    }
  };

  // ── upload ─────────────────────────────────────────────────────────────────
  const doUpload = async (file: File) => {
    setShowConfirm(false);
    setPendingFile(null);
    setUploading(true);
    setUploadError(null);
    try {
      const result = await api.uploadTriageManual(file);
      setCurrent(result);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : t('triageManualErrorDetail'));
    } finally {
      setUploading(false);
    }
  };

  const handleConfirmReplace = () => {
    if (pendingFile) void doUpload(pendingFile);
  };

  const handleCancelReplace = () => {
    setShowConfirm(false);
    setPendingFile(null);
  };

  // ── status badge ───────────────────────────────────────────────────────────
  const statusLabel = (s: string) => {
    if (s === 'ready') return t('triageManualStatusReady');
    if (s === 'processing') return t('triageManualStatusProcessing');
    return t('triageManualStatusFailed');
  };

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <section className="tm-section">
      <header className="tm-header">
        <h2>{t('triageManualTitle')}</h2>
        <p className="muted">{t('triageManualSubtitle')}</p>
      </header>

      {/* Confirm-replace dialog */}
      {showConfirm && (
        <div className="tm-confirm-overlay" role="dialog" aria-modal="true">
          <div className="tm-confirm-box">
            <p className="tm-confirm-warning">⚠ {t('triageManualWarning')}</p>
            {pendingFile && (
              <p className="tm-confirm-filename">
                <strong>{pendingFile.name}</strong> ({formatBytes(pendingFile.size)})
              </p>
            )}
            <div className="tm-confirm-actions">
              <button
                type="button"
                className="primary-btn tm-confirm-yes"
                onClick={handleConfirmReplace}
              >
                {t('triageManualWarningConfirm')}
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={handleCancelReplace}
              >
                {t('triageManualWarningCancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Current manual card */}
      <div className="tm-current-card">
        <h3>{t('triageManualCurrentFile')}</h3>
        {current == null ? (
          <p className="muted tm-no-file">{t('triageManualNoFile')}</p>
        ) : (
          <dl className="tm-meta">
            <div className="tm-meta-row">
              <dt>📄</dt>
              <dd>
                <strong>{current.original_filename}</strong>
                <span
                  className={`tm-status-badge tm-status-${current.status}`}
                  aria-label={statusLabel(current.status)}
                >
                  {statusLabel(current.status)}
                </span>
              </dd>
            </div>
            {current.chunks_count != null && (
              <div className="tm-meta-row">
                <dt>🗂</dt>
                <dd>{t('triageManualChunks', { n: current.chunks_count })}</dd>
              </div>
            )}
            <div className="tm-meta-row">
              <dt>{t('triageManualFileSize')}</dt>
              <dd>{formatBytes(current.file_size_bytes)}</dd>
            </div>
            <div className="tm-meta-row">
              <dt>{t('triageManualUploadedBy')}</dt>
              <dd>{current.uploaded_by ?? '—'}</dd>
            </div>
            <div className="tm-meta-row">
              <dt>{t('triageManualUploadedAt')}</dt>
              <dd>{formatDate(current.uploaded_at)}</dd>
            </div>
            {current.completed_at && (
              <div className="tm-meta-row">
                <dt>{t('triageManualCompletedAt')}</dt>
                <dd>{formatDate(current.completed_at)}</dd>
              </div>
            )}
            {current.error_message && (
              <div className="tm-meta-row tm-meta-error">
                <dt>⚠</dt>
                <dd>{current.error_message}</dd>
              </div>
            )}
          </dl>
        )}

        {current?.status === 'processing' && (
          <p className="tm-poll-hint muted">
            <span className="tm-spinner" aria-hidden="true" />
            {t('triageManualPollHint')}
          </p>
        )}
      </div>

      {/* Upload dropzone */}
      <div
        className={`tm-dropzone ${isDragging ? 'tm-dropzone-active' : ''} ${uploading ? 'tm-dropzone-disabled' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label={t('triageManualDropzone')}
        onKeyDown={(e) => e.key === 'Enter' && !uploading && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="tm-file-input"
          onChange={handleFileChange}
          aria-hidden="true"
          tabIndex={-1}
        />
        {uploading ? (
          <span className="tm-spinner tm-spinner-lg" aria-hidden="true" />
        ) : (
          <span className="tm-dropzone-text">
            {isDragging
              ? t('triageManualDropzoneActive')
              : t('triageManualDropzone')}
          </span>
        )}
      </div>

      {/* Upload error */}
      {uploadError && (
        <p className="tm-upload-error" role="alert">
          ⚠ {uploadError}
        </p>
      )}

      {/* Upload button (alternative to drag-and-drop) */}
      <div className="tm-actions">
        <button
          type="button"
          className="primary-btn"
          disabled={uploading || current?.status === 'processing'}
          onClick={() => fileInputRef.current?.click()}
        >
          {current ? t('triageManualReplaceBtn') : t('triageManualUploadBtn')}
        </button>
      </div>
    </section>
  );
}
