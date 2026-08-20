import { useState, useCallback, useRef, useEffect } from 'react';
import api from '@/lib/api';
import { API_ROUTES, POLLING_INTERVAL } from '@/lib/constants';
import { useSearchStore } from '@/stores/searchStore';
import { useToast } from './useToast';

export function useSearch() {
  const { activeSearchId, progress, setActiveSearch, setProgress, clearActiveSearch, setHistory, appendResults, results, resultsTotal } = useSearchStore();
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
  }, []);

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
  }, [appendResults, clearPolling]);

  const pollStatus = useCallback(async (id: string) => {
    statusAbortRef.current?.abort();
    const abort = new AbortController();
    statusAbortRef.current = abort;
    try {
      const { data } = await api.get(API_ROUTES.searches.status(id), { signal: abort.signal });
      setProgress(data);

      if (['completed', 'failed', 'cancelled'].includes(data.status)) {
        clearPolling();
        try {
          resultsAbortRef.current?.abort();
          const resultsAbort = new AbortController();
          resultsAbortRef.current = resultsAbort;
          const { data: finalResults } = await api.get(`${API_ROUTES.searches.detail(id)}/results?page=1&per_page=50`, { signal: resultsAbort.signal });
          if (finalResults.items) {
            appendResults(finalResults.items);
          }
        } catch (e) {
          console.warn('Failed to fetch final results:', e);
        }
        if (data.status === 'completed') {
          showToast(`Search completed: ${data.total_results || 0} leads found.`, 'success');
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
  }, [setProgress, showToast, clearActiveSearch, appendResults, clearPolling, setError]);

  useEffect(() => {
    pollStatusRef.current = pollStatus;
    pollResultsRef.current = pollResults;
    return () => {
      clearPolling();
    };
  }, [pollStatus, pollResults, clearPolling]);

  const startSearch = async (niche: string, location: string, options?: { source?: 'google_maps' | 'linkedin'; enrichEmails?: boolean; maxResults?: number }) => {
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
      if (options?.source === 'linkedin') {
        payload.enrich_emails = options.enrichEmails ?? true;
        payload.max_results = options.maxResults ?? 20;
      }

      const { data } = await api.post(API_ROUTES.searches.create, payload);
      setActiveSearch(data.id);
      setProgress({ status: 'queued', elapsed_seconds: 0 });
      showToast('Search started successfully', 'success');
      
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
    if (activeSearchId && progress && !['completed', 'failed', 'cancelled'].includes(progress.status ?? '')) {
      clearPolling();
      resultsPageRef.current = 1;
      statusRetryRef.current = 0;
      resultsRetryRef.current = 0;
      pollStatus(activeSearchId);
      pollResults(activeSearchId);
    }
  }, [activeSearchId, progress, clearPolling, pollStatus, pollResults]);

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
    clearActiveSearch,
    resumePollingIfActive,
  };
}
