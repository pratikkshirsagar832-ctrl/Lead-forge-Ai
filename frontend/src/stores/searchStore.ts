import { create } from 'zustand';
import type { SearchStatus, SearchHistoryItem, LeadListItem } from '@/lib/types';

export type SearchResult = LeadListItem;

export interface SearchState {
  activeSearchId: string | null;
  progress: Partial<SearchStatus> | null;
  results: SearchResult[];
  resultsTotal: number;
  history: SearchHistoryItem[];
  /** LinkedIn only: how many leads the user requested — extras stay locked. */
  requestedCount: number | null;
  /** Whether the user clicked "Get More" to reveal over-delivered leads. */
  unlocked: boolean;
  /** Set when a search finished but the plan's daily lead cap truncated it. */
  limitHit: boolean;
  setActiveSearch: (id: string | null) => void;
  setProgress: (progress: Partial<SearchStatus> | null) => void;
  setResults: (results: SearchResult[], total: number) => void;
  appendResults: (results: SearchResult[]) => void;
  setHistory: (history: SearchHistoryItem[]) => void;
  setRequestedCount: (n: number | null) => void;
  unlockResults: () => void;
  setLimitHit: (v: boolean) => void;
  clearActiveSearch: () => void;
}

export const useSearchStore = create<SearchState>((set) => ({
  activeSearchId: null,
  progress: null,
  results: [],
  resultsTotal: 0,
  history: [],
  requestedCount: null,
  unlocked: false,
  limitHit: false,
  setActiveSearch: (id) => set({ activeSearchId: id }),
  setProgress: (progress) => set({ progress }),
  setResults: (results, resultsTotal) => set({ results, resultsTotal }),
  appendResults: (newResults) =>
    set((state) => {
      const existingIds = new Set(state.results.map((r) => r.id));
      const unique = newResults.filter((r) => !existingIds.has(r.id));
      return {
        results: [...state.results, ...unique],
      };
    }),
  setHistory: (history) => set({ history }),
  setRequestedCount: (n) => set({ requestedCount: n, unlocked: false }),
  unlockResults: () => set({ unlocked: true }),
  setLimitHit: (v) => set({ limitHit: v }),
  clearActiveSearch: () =>
    set({ activeSearchId: null, progress: null, results: [], resultsTotal: 0, requestedCount: null, unlocked: false, limitHit: false }),
}));
