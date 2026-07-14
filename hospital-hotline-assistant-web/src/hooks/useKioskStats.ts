import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { KioskStats } from '../api/types';

/**
 * Polls the public `GET /kiosk/stats` counters for the attract screen.
 * Silent on failure — the home screen must never break because a number
 * couldn't load. Defaults to zeros until the first successful fetch.
 */
export function useKioskStats(pollMs = 45000): KioskStats {
  const [stats, setStats] = useState<KioskStats>({
    date: '',
    visitors_today: 0,
    navigated_today: 0,
    sessions_today: 0,
  });
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const next = await api.getKioskStats();
        if (mounted.current) setStats(next);
      } catch {
        /* keep last-known values */
      } finally {
        if (mounted.current) timer = setTimeout(tick, pollMs);
      }
    };

    void tick();
    return () => {
      mounted.current = false;
      clearTimeout(timer);
    };
  }, [pollMs]);

  return stats;
}
