import { useState, useCallback, useRef } from 'react';
import api from '@/lib/api';
import { API_ROUTES, POLLING_INTERVAL } from '@/lib/constants';
import { useSearchStore } from '@/stores/searchStore';
import { useToast } from './useToast';

export function useSearch() {
  const { activeSearchId, progress, setActiveSearch, setProgress, clearActiveSearch, setHistory } = useSearchStore();
  const { showToast } = useToast();
  const [isStarting, setIsStarting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isFetchingHistory, setIsFetchingHistory] = useState(false);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  const clearPolling = () => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  const pollStatus = useCallback(async (id: string) => {
    try {
      const { data } = await api.get(API_ROUTES.searches.status(id));
      setProgress(data);

      if (['completed', 'failed', 'cancelled'].includes(data.status)) {
        clearPolling();
        if (data.status === 'completed') {
          showToast(`Search completed: ${data.total_results || 0} leads found.`, 'success');
        } else if (data.status === 'failed') {
          showToast(`Search failed: ${data.message || 'Unknown error'}`, 'error');
        } else {
          showToast('Search cancelled', 'info');
        }
      } else {
        // Continue polling
        pollTimerRef.current = setTimeout(() => pollStatus(id), POLLING_INTERVAL);
      }
    } catch (error: any) {
      console.error('Failed to poll status', error);
      if (error.response?.status === 404) {
        showToast("Search not found or expired", "error");
        clearActiveSearch();
        clearPolling();
        return;
      }
      if (error.response?.status === 401 || error.response?.status === 403) {
        clearPolling();
        return; // interception redirect handles the rest
      }
      // Keep polling despite network blips unless we get a 404/401
      pollTimerRef.current = setTimeout(() => pollStatus(id), POLLING_INTERVAL);
    }
  }, [setProgress, showToast, clearActiveSearch]);

  const startSearch = async (niche: string, location: string) => {
    try {
      setIsStarting(true);
      clearPolling();
      const { data } = await api.post(API_ROUTES.searches.create, { niche, location });
      setActiveSearch(data.id);
      setProgress({ status: 'queued', stage: 0, elapsed_seconds: 0 });
      showToast('Search started successfully', 'success');
      
      // Start polling immediately
      pollStatus(data.id);
      return data;
    } catch (error: any) {
      showToast(error.response?.data?.detail || 'Failed to start search', 'error');
      throw error;
    } finally {
      setIsStarting(false);
    }
  };

  const cancelSearch = async () => {
    if (!activeSearchId) return;
    try {
      setIsCancelling(true);
      await api.post(API_ROUTES.searches.cancel(activeSearchId));
      clearPolling();
      showToast('Search cancellation requested', 'info');
      // Final poll to get the cancelled status
      pollStatus(activeSearchId);
    } catch (error: any) {
      showToast(error.response?.data?.detail || 'Failed to cancel search', 'error');
    } finally {
      setIsCancelling(false);
    }
  };

  const fetchHistory = async () => {
    try {
      setIsFetchingHistory(true);
      const { data } = await api.get(API_ROUTES.searches.list);
      setHistory(data.items || []);
    } catch (error) {
      console.error('Failed to fetch search history', error);
      showToast('Failed to load search history', 'error');
    } finally {
      setIsFetchingHistory(false);
    }
  };

  const resumePollingIfActive = useCallback(() => {
    if (activeSearchId && progress && !['completed', 'failed', 'cancelled'].includes(progress.status)) {
      clearPolling();
      pollStatus(activeSearchId);
    }
  }, [activeSearchId, progress, pollStatus]);

  return {
    activeSearchId,
    progress,
    isStarting,
    isCancelling,
    isFetchingHistory,
    startSearch,
    cancelSearch,
    fetchHistory,
    clearActiveSearch,
    resumePollingIfActive,
  };
}
