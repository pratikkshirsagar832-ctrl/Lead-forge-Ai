import { useState, useCallback, useRef, useEffect } from 'react';
import api from '@/lib/api';
import { API_ROUTES, POLLING_INTERVAL } from '@/lib/constants';
import { useSearchStore } from '@/stores/searchStore';
import { useToast } from './useToast';

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

export function useSearch() {
  const activeSearchId = useSearchStore((s) => s.activeSearchId);
  const progress = useSearchStore((s) => s.progress);
  const results = useSearchStore((s) => s.results);
  const resultsTotal = useSearchStore((s) => s.resultsTotal);
  const setActiveSearch = useSearchStore((s) => s.setActiveSearch);
  const setProgress = useSearchStore((s) => s.setProgress);
  const clearActiveSearch = useSearchStore((s) => s.clearActiveSearch);
  const setHistory = useSearchStore((s) => s.setHistory);
  const appendResults = useSearchStore((s) => s.appendResults);
  const setResults = useSearchStore((s) => s.setResults);
  const setRequestedCount = useSearchStore((s) => s.setRequestedCount);
  const setLimitHit = useSearchStore((s) => s.setLimitHit);
  const { showToast } = useToast();
  const [isStarting, setIsStarting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isFetchingHistory, setIsFetchingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const resultsPollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const resultsPageRef = useRef(1);
  const statusRetryRef = useRef(0);
  const resultsRetryRef = useRef(0);
  const pollStatusRef = useRef<((id: string) => Promise<void>) | null>(null);
  const pollResultsRef = useRef<((id: string) => Promise<void>) | null>(null);
  const statusAbortRef = useRef<AbortController | null>(null);
  const resultsAbortRef = useRef<AbortController | null>(null);
  const isStartingRef = useRef(false);
  // Guards against the effect-cascade bug where a new `progress` object every
  // status tick re-created resumePollingIfActive, killing in-flight polls,
  // resetting the results page counter, and re-firing /auth/me every 2s.
  const pollingStartedForRef = useRef<string | null>(null);

  const clearPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (resultsPollTimerRef.current) {
      clearTimeout(resultsPollTimerRef.current);
      resultsPollTimerRef.current = null;
    }
    if (statusAbortRef.current) {
      statusAbortRef.current.abort();
      statusAbortRef.current = null;
    }
    if (resultsAbortRef.current) {
      resultsAbortRef.current.abort();
      resultsAbortRef.current = null;
    }
    statusRetryRef.current = 0;
    resultsRetryRef.current = 0;
    pollingStartedForRef.current = null;
  }, []);

  const fetchAllResults = useCallback(async (id: string) => {
    // The /results endpoint caps per_page at 50; page through it until we have
    // everything so searches with >50 leads (e.g. after load-more) stay visible.
    const collected: any[] = [];
    let total = 0;
    let page = 1;
    for (let guard = 0; guard < 20; guard++) {
      const abort = new AbortController();
      resultsAbortRef.current = abort;
      const { data } = await api.get(
        `${API_ROUTES.searches.detail(id)}/results?page=${page}&per_page=50`,
        { signal: abort.signal }
      );
      if (data.items?.length) collected.push(...data.items);
      total = data.total ?? 0;
      if (page * 50 >= total || !data.items?.length) break;
      page += 1;
    }
    if (collected.length) {
      appendResults(collected);
      if (total > 0) setResults(useSearchStore.getState().results, total);
    }
    return total;
  }, [appendResults, setResults]);

  const pollResults = useCallback(async (id: string) => {
    resultsAbortRef.current?.abort();
    const abort = new AbortController();
    resultsAbortRef.current = abort;
    try {
      const page = resultsPageRef.current;
      const { data } = await api.get(`${API_ROUTES.searches.detail(id)}/results?page=${page}&per_page=4`, { signal: abort.signal });
      if (data.items?.length > 0) {
        appendResults(data.items);
      }
      if (data.total && data.total > 0) {
        setResults(useSearchStore.getState().results, data.total);
      }
      if (data.total > resultsPageRef.current * 4) {
        resultsPageRef.current += 1;
      }
      resultsRetryRef.current = 0;
      resultsPollTimerRef.current = setTimeout(() => pollResultsRef.current?.(id), 4000);
    } catch (e: any) {
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED') return;
      console.warn('Poll results failed, retrying:', e);
      resultsRetryRef.current += 1;
      if (resultsRetryRef.current > 50) {
        clearPolling();
        return;
      }
      resultsPollTimerRef.current = setTimeout(() => pollResultsRef.current?.(id), 4000);
    }
  }, [appendResults, clearPolling, setResults]);

  const pollStatus = useCallback(async (id: string) => {
    statusAbortRef.current?.abort();
    const abort = new AbortController();
    statusAbortRef.current = abort;
    try {
      const { data } = await api.get(API_ROUTES.searches.status(id), { signal: abort.signal });
      setProgress(data);

      if (['completed', 'failed', 'cancelled'].includes(data.status)) {
        clearPolling();
        // HARD LIMIT: backend marks truncation in the message → upgrade popup
        if (/lead limit/i.test(data.message || '')) {
          setLimitHit(true);
        }
        try {
          const total = await fetchAllResults(id);
          // If the server says a final total but pagination found nothing (edge
          // case: results landed between polls), force one more paged pass.
          if (data.total_results > 0 && total === 0) {
            await fetchAllResults(id);
          }
        } catch (e) {
          console.warn('Failed to fetch final results:', e);
        }
        if (data.status === 'completed') {
          const delivered = data.source === 'linkedin' ? (data.hot_leads ?? data.returned_count ?? 0) : (data.total_results || 0);
          showToast(`Search completed: ${delivered} qualified leads found.`, 'success');
        } else if (data.status === 'failed') {
          showToast(`Search failed: ${data.message || 'Unknown error'}`, 'error');
        } else {
          showToast('Search cancelled', 'info');
        }
      } else {
        statusRetryRef.current = 0;
        pollTimerRef.current = setTimeout(() => pollStatusRef.current?.(id), POLLING_INTERVAL);
      }
    } catch (error: any) {
      if (error.name === 'CanceledError' || error.code === 'ERR_CANCELED') return;
      if (error.response?.status === 404) {
        showToast("Search not found or expired", "error");
        clearActiveSearch();
        clearPolling();
        return;
      }
      if (error.response?.status === 401 || error.response?.status === 403) {
        clearPolling();
        return;
      }
      statusRetryRef.current += 1;
      if (statusRetryRef.current > 50) {
        clearPolling();
        setError('Search polling stopped after too many retries');
        showToast('Search status polling stopped after too many retries', 'error');
        return;
      }
      pollTimerRef.current = setTimeout(() => pollStatusRef.current?.(id), POLLING_INTERVAL);
    }
  }, [setProgress, showToast, clearActiveSearch, appendResults, clearPolling, setError, setLimitHit, fetchAllResults]);

  useEffect(() => {
    pollStatusRef.current = pollStatus;
    pollResultsRef.current = pollResults;
    return () => {
      clearPolling();
    };
  }, [pollStatus, pollResults, clearPolling]);

  const startSearch = async (niche: string, location: string, options?: { source?: 'google_maps' | 'linkedin'; enrichEmails?: boolean; maxResults?: number; leadTypes?: ('buyer' | 'agency_wanted')[] }) => {
    if (isStartingRef.current) return;
    try {
      isStartingRef.current = true;
      setIsStarting(true);
      setError(null);
      clearPolling();
      resultsPageRef.current = 1;
      statusRetryRef.current = 0;
      resultsRetryRef.current = 0;

      const payload: Record<string, unknown> = {
        niche,
        location,
        source: options?.source ?? 'google_maps',
      };
      if (options?.maxResults != null) {
        payload.max_results = options.maxResults;
      }
      if (options?.source === 'linkedin') {
        payload.enrich_emails = options.enrichEmails ?? true;
        if (options.leadTypes) {
          payload.lead_types = options.leadTypes;
        }
      }
      // Extras beyond the requested count stay locked until user clicks
      // "Get More" — only applies to LinkedIn searches.
      setRequestedCount(options?.source === 'linkedin' ? (options.maxResults ?? 10) : null);
      setLimitHit(false);

      const { data } = await api.post(API_ROUTES.searches.create, payload);
      setActiveSearch(data.id);
      setProgress({ status: 'queued', elapsed_seconds: 0 });
      showToast('Search started successfully', 'success');

      pollingStartedForRef.current = data.id;
      pollStatus(data.id);
      pollResults(data.id);
      return data;
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Failed to start search';
      setError(msg);
      showToast(msg, 'error');
      throw error;
    } finally {
      setIsStarting(false);
      isStartingRef.current = false;
    }
  };

  const cancelSearch = async () => {
    if (!activeSearchId) return;
    try {
      setIsCancelling(true);
      clearPolling();
      await api.post(API_ROUTES.searches.cancel(activeSearchId));
      showToast('Search cancellation requested', 'info');
      pollStatus(activeSearchId);
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      showToast(typeof detail === 'string' ? detail : detail?.message || 'Failed to cancel search', 'error');
    } finally {
      setIsCancelling(false);
    }
  };

  const fetchHistory = async () => {
    try {
      setIsFetchingHistory(true);
      setError(null);
      const { data } = await api.get(API_ROUTES.searches.list);
      setHistory(data.items || []);
    } catch (error) {
      const msg = 'Failed to load search history';
      setError(msg);
      showToast(msg, 'error');
    } finally {
      setIsFetchingHistory(false);
    }
  };

  const resumePollingIfActive = useCallback(() => {
    const state = useSearchStore.getState();
    const id = state.activeSearchId;
    const status = state.progress?.status;
    if (!id || !status || TERMINAL.has(status)) {
      pollingStartedForRef.current = null;
      return;
    }
    // Already polling this search — do not restart (a fresh `progress` object
    // per tick must not cascade into abort/restart cycles).
    if (pollingStartedForRef.current === id) return;
    clearPolling();
    resultsPageRef.current = 1;
    statusRetryRef.current = 0;
    resultsRetryRef.current = 0;
    pollingStartedForRef.current = id;
    pollStatus(id);
    pollResults(id);
  }, [clearPolling, pollStatus, pollResults]);

  return {
    activeSearchId,
    progress,
    results,
    resultsTotal,
    isStarting,
    isCancelling,
    isFetchingHistory,
    error,
    startSearch,
    cancelSearch,
    fetchHistory,
    fetchAllResults,
    clearActiveSearch,
    resumePollingIfActive,
  };
}
