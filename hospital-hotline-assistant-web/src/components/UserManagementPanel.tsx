import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { AdminManagedUser } from '../api/types';

/** Admin → User Settings: create / manage / delete nurse accounts.
 *  Nurses are admin_users rows with role 'admin' (the /nurse portal role);
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
    <div className="users-panel">
      <div className="hdb-header">
        <div>
          <h2>{t('usersTitle')}</h2>
          <p className="muted">{t('usersSubtitle')}</p>
        </div>
      </div>

      <div className="users-create-card">
        <h3>{t('usersCreateTitle')}</h3>
        <div className="users-create-grid">
          <label className="vitals-extra-field">
            <span>{t('usersFullName')}</span>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              disabled={creating}
              maxLength={150}
            />
          </label>
          <label className="vitals-extra-field">
            <span>{t('usersEmail')}</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={creating}
              maxLength={255}
            />
          </label>
          <label className="vitals-extra-field">
            <span>{t('usersPassword')}</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={creating}
              maxLength={128}
            />
          </label>
          <button
            type="button"
            className="primary-btn"
            onClick={() => void create()}
            disabled={creating || !formValid}
          >
            {creating ? t('loading') : t('usersCreate')}
          </button>
        </div>
        <p className="muted users-hint">{t('usersPasswordHint')}</p>
        {createError && <p className="error-text">{createError}</p>}
      </div>

      {error && <p className="error-text">{error}</p>}
      {loading ? (
        <p className="muted">{t('loading')}</p>
      ) : (
        <table className="hdb-table users-table">
          <thead>
            <tr>
              <th>{t('usersFullName')}</th>
              <th>{t('usersEmail')}</th>
              <th>{t('usersStatus')}</th>
              <th>{t('usersLastLogin')}</th>
              <th>{t('usersActions')}</th>
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
                  <span className={`users-badge ${u.is_active ? 'active' : 'inactive'}`}>
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
                        className="secondary-btn users-danger"
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
                        className="text-btn users-danger"
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
      )}
    </div>
  );
}
