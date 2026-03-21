import { create } from 'zustand';

export interface SearchState {
  activeSearchId: string | null;
  progress: {
    status: string;
    stage: number;
    total_results?: number;
    processed_count?: number;
    hot_leads?: number;
    warm_leads?: number;
    skipped?: number;
    message?: string;
    elapsed_seconds: number;
    started_at?: string;
  } | null;
  history: any[];
  setActiveSearch: (id: string | null) => void;
  setProgress: (progress: any) => void;
  setHistory: (history: any[]) => void;
  clearActiveSearch: () => void;
}

export const useSearchStore = create<SearchState>((set) => ({
  activeSearchId: null,
  progress: null,
  history: [],
  setActiveSearch: (id) => set({ activeSearchId: id }),
  setProgress: (progress) => set({ progress }),
  setHistory: (history) => set({ history }),
  clearActiveSearch: () => set({ activeSearchId: null, progress: null }),
}));
