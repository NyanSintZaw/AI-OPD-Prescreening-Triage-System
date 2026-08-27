import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X } from '@phosphor-icons/react';
import { api } from '../api';
import type { AdminManagedUser } from '../api/types';
import { useDialogExit } from '../hooks/useDialogExit';

/** Admin → User Settings: create / manage / delete nurse accounts.
 *  Nurses are admin_users rows with role 'nurse' (the /nurse portal role);
 *  super-admin and viewer accounts are deliberately not manageable here. */
export function UserManagementPanel() {
  const { t } = useTranslation();
  const [users, setUsers] = useState<AdminManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  // The form is a task, not part of the page. Six of seven visits here are to
  // read or reset an existing account, and an always-open create form put three
  // empty inputs above that list every time.
  const [createOpen, setCreateOpen] = useState(false);

  const [resetTarget, setResetTarget] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUsers(await api.listAdminUsers());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const closeCreate = useCallback(() => {
    setCreateOpen(false);
    setCreateError(null);
  }, []);

  // The form leaves rather than vanishing. The in-flight guard stays on the
  // outside: a create that is still running should not start an exit at all.
  const { leaving: leavingCreate, close: dismissCreate } = useDialogExit(closeCreate);
  const guardedDismiss = () => {
    if (creating) return;
    dismissCreate();
  };

  // Escape closes — a modal without it traps keyboard users. Not while the
  // create is in flight, so the dialog cannot vanish mid-request.
  useEffect(() => {
    if (!createOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !creating) dismissCreate();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [createOpen, creating, dismissCreate]);

  const create = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      await api.createAdminUser({
        email: email.trim(),
        full_name: fullName.trim(),
        password,
      });
      setFullName('');
      setEmail('');
      setPassword('');
      // Through the exit, not straight to unmounted — a successful create
              // should read the same as a cancel.
      dismissCreate();
      await load();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const patch = async (
    userId: string,
    payload: Parameters<typeof api.updateAdminUser>[1],
  ) => {
    setRowBusy(userId);
    setError(null);
    try {
      await api.updateAdminUser(userId, payload);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRowBusy(null);
    }
  };

  const remove = async (userId: string) => {
    setRowBusy(userId);
    setError(null);
    try {
      await api.deleteAdminUser(userId);
      setConfirmDelete(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRowBusy(null);
    }
  };

  const formValid =
    fullName.trim().length > 0 && email.trim().includes('@') && password.length >= 8;


  return (
    /* No heading of its own: the admin page head already prints "User
       Settings" and this panel's own subtitle, word for word. */
    <div className="users-panel">
      <div className="users-toolbar">
        <button type="button" className="primary-btn" onClick={() => setCreateOpen(true)}>
          <Plus size={16} weight="bold" aria-hidden="true" />
          {t('usersCreate')}
        </button>
      </div>

      {createOpen && (
        <div className="dialog" role="presentation" onClick={guardedDismiss}>
          <div className="dialog-backdrop" data-leaving={leavingCreate || undefined} />
          <form
            className="dialog-card dialog-form"
            data-leaving={leavingCreate || undefined}
            role="dialog"
            aria-modal="true"
            aria-label={t('usersCreateTitle')}
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              if (formValid && !creating) void create();
            }}
          >
            <header className="dialog-form-head">
              <div>
                <h3>{t('usersCreateTitle')}</h3>
                <p className="muted">{t('usersPasswordHint')}</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                onClick={guardedDismiss}
                aria-label={t('close')}
              >
                <X size={20} aria-hidden="true" />
              </button>
            </header>

            <label className="field">
              <span className="field-label">{t('usersFullName')}</span>
              {/* Autofocus is right here and wrong on a page: the dialog opened
                  because someone asked for this form. */}
              <input
                type="text"
                className="field-input"
                autoFocus
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={creating}
                maxLength={150}
              />
            </label>
            <label className="field">
              <span className="field-label">{t('usersEmail')}</span>
              <input
                type="email"
                className="field-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={creating}
                maxLength={255}
              />
            </label>
            <label className="field">
              <span className="field-label">{t('usersPassword')}</span>
              <input
                type="password"
                className="field-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={creating}
                maxLength={128}
              />
            </label>

            {createError && <p className="error-text">{createError}</p>}

            <div className="dialog-form-actions">
              <button type="button" className="text-btn" onClick={guardedDismiss} disabled={creating}>
                {t('usersCancel')}
              </button>
              <button type="submit" className="primary-btn" disabled={creating || !formValid}>
                {creating ? t('loading') : t('usersCreate')}
              </button>
            </div>
          </form>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}
      {loading ? (
        <p className="muted">{t('loading')}</p>
      ) : (
        <div className="table-wrap scroll-slim">
        <table className="staff-table users-table">
          <thead>
            <tr>
              <th scope="col">{t('usersFullName')}</th>
              <th scope="col">{t('usersEmail')}</th>
              <th scope="col">{t('usersStatus')}</th>
              <th scope="col">{t('usersLastLogin')}</th>
              <th scope="col">{t('usersActions')}</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  {t('usersEmpty')}
                </td>
              </tr>
            )}
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.full_name || '—'}</td>
                <td>{u.email}</td>
                <td>
                  {/* Named `enabled`/`disabled` rather than reusing the
                      session log's `active`, which there means "still at the
                      booth" — one chip name, one meaning. */}
                  <span className={`status-chip ${u.is_active ? 'chip-enabled' : 'chip-disabled'}`}>
                    {u.is_active ? t('usersActive') : t('usersInactive')}
                  </span>
                </td>
                <td>
                  {u.last_login_at
                    ? new Date(u.last_login_at).toLocaleString()
                    : t('usersNeverLoggedIn')}
                </td>
                <td className="users-actions">
                  {resetTarget === u.id ? (
                    <span className="users-reset-row">
                      <input
                        type="password"
                        className="field-input"
                        placeholder={t('usersNewPassword')}
                        value={resetPassword}
                        onChange={(e) => setResetPassword(e.target.value)}
                        disabled={rowBusy === u.id}
                      />
                      <button
                        type="button"
                        className="secondary-btn"
                        disabled={rowBusy === u.id || resetPassword.length < 8}
                        onClick={() =>
                          void patch(u.id, { password: resetPassword }).then(() => {
                            setResetTarget(null);
                            setResetPassword('');
                          })
                        }
                      >
                        {t('usersSave')}
                      </button>
                      <button
                        type="button"
                        className="text-btn"
                        onClick={() => {
                          setResetTarget(null);
                          setResetPassword('');
                        }}
                      >
                        {t('usersCancel')}
                      </button>
                    </span>
                  ) : confirmDelete === u.id ? (
                    <span className="users-reset-row">
                      <span className="error-text">{t('usersDeleteConfirm')}</span>
                      <button
                        type="button"
                        className="secondary-btn is-danger"
                        disabled={rowBusy === u.id}
                        onClick={() => void remove(u.id)}
                      >
                        {t('usersDelete')}
                      </button>
                      <button
                        type="button"
                        className="text-btn"
                        onClick={() => setConfirmDelete(null)}
                      >
                        {t('usersCancel')}
                      </button>
                    </span>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="text-btn"
                        disabled={rowBusy === u.id}
                        onClick={() => {
                          setResetTarget(u.id);
                          setResetPassword('');
                        }}
                      >
                        {t('usersResetPassword')}
                      </button>
                      <button
                        type="button"
                        className="text-btn"
                        disabled={rowBusy === u.id}
                        onClick={() => void patch(u.id, { is_active: !u.is_active })}
                      >
                        {u.is_active ? t('usersDeactivate') : t('usersActivate')}
                      </button>
                      <button
                        type="button"
                        className="text-btn is-danger"
                        disabled={rowBusy === u.id}
                        onClick={() => setConfirmDelete(u.id)}
                      >
                        {t('usersDelete')}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
