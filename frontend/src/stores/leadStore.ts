import { create } from 'zustand';
import type { LeadListItem } from '@/lib/types';

interface LeadsState {
  leads: LeadListItem[];
  totalCount: number;
  filters: {
    status: string;
    category: string;
    isFavorite: boolean | null;
    search: string;
    searchId: string;
    page: number;
    limit: number;
  };
  setLeads: (leads: LeadListItem[], totalCount: number) => void;
  setFilters: (filters: Partial<LeadsState['filters']>) => void;
  updateLeadInStore: (id: string, updates: Partial<LeadListItem>) => void;
}

export const useLeadStore = create<LeadsState>((set) => ({
  leads: [],
  totalCount: 0,
  filters: {
    status: '',
    category: '',
    isFavorite: null,
    search: '',
    searchId: '',
    page: 1,
    limit: 50,
  },
  setLeads: (leads, totalCount) => set({ leads, totalCount }),
  setFilters: (newFilters) => 
    set((state) => ({ 
      filters: { ...state.filters, ...newFilters, page: newFilters.page ?? 1 } 
    })),
  updateLeadInStore: (id, updates) =>
    set((state) => ({
      leads: state.leads.map((lead) =>
        lead.id === id ? { ...lead, ...updates } : lead
      ),
    })),
}));
