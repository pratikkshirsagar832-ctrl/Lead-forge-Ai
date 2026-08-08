import { useState, useCallback } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { useLeadStore } from '@/stores/leadStore';
import { useToast } from './useToast';

export function useLeads() {
  const { leads, totalCount, filters, setLeads, setFilters, updateLeadInStore } = useLeadStore();
  const { showToast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState<Record<string, boolean>>({});

  const fetchLeads = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (filters.search) params.append('search', filters.search);
      if (filters.searchId) params.append('search_id', filters.searchId);
      if (filters.status) params.append('user_status', filters.status);
      if (filters.category) params.append('lead_category', filters.category);
      if (filters.isFavorite !== null) params.append('is_favorite', String(filters.isFavorite));
      params.append('page', String(filters.page));
      params.append('per_page', String(filters.limit));

      const { data } = await api.get(`${API_ROUTES.leads.list}?${params.toString()}`);
      setLeads(data.items, data.total);
    } catch (error) {
      const msg = 'Failed to load leads';
      setError(msg);
      showToast(msg, 'error');
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [filters, setLeads, showToast]);

  const updateLeadStatus = async (id: string, status: string) => {
    const prevStatus = leads.find(l => l.id === id)?.user_status;
    try {
      setIsUpdating((prev) => ({ ...prev, [id]: true }));
      updateLeadInStore(id, { user_status: status });
      const { data } = await api.patch(API_ROUTES.leads.status(id), { user_status: status });
      updateLeadInStore(id, { user_status: data.user_status });
      showToast('Status updated', 'success');
    } catch (error) {
      if (prevStatus) updateLeadInStore(id, { user_status: prevStatus });
      showToast('Failed to update status', 'error');
    } finally {
      setIsUpdating((prev) => ({ ...prev, [id]: false }));
    }
  };

  const updateLeadNotes = async (id: string, notes: string) => {
    const prevNotes = leads.find(l => l.id === id)?.user_notes;
    try {
      setIsUpdating((prev) => ({ ...prev, [`${id}_notes`]: true }));
      updateLeadInStore(id, { user_notes: notes });
      await api.patch(API_ROUTES.leads.notes(id), { user_notes: notes });
      showToast('Notes saved', 'success');
    } catch (error) {
      if (prevNotes !== undefined) updateLeadInStore(id, { user_notes: prevNotes });
      showToast('Failed to save notes', 'error');
    } finally {
      setIsUpdating((prev) => ({ ...prev, [`${id}_notes`]: false }));
    }
  };

  const toggleFavorite = async (id: string, currentFav: boolean) => {
    const newFav = !currentFav;
    try {
      setIsUpdating((prev) => ({ ...prev, [`${id}_fav`]: true }));
      updateLeadInStore(id, { is_favorite: newFav });
      await api.patch(API_ROUTES.leads.favorite(id), { is_favorite: newFav });
    } catch (error) {
      updateLeadInStore(id, { is_favorite: currentFav });
      showToast('Failed to update favorite', 'error');
    } finally {
      setIsUpdating((prev) => ({ ...prev, [`${id}_fav`]: false }));
    }
  };

  const exportCsv = async () => {
    try {
      setIsExporting(true);
      setError(null);
      const params = new URLSearchParams();
      if (filters.search) params.append('search', filters.search);
      if (filters.searchId) params.append('search_id', filters.searchId);
      if (filters.status) params.append('user_status', filters.status);
      if (filters.category) params.append('lead_category', filters.category);
      if (filters.isFavorite !== null) params.append('is_favorite', String(filters.isFavorite));

      const response = await api.get(`${API_ROUTES.leads.export}?${params.toString()}`, {
        responseType: 'blob',
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `leads_export_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      showToast('Export successful', 'success');
    } catch (error) {
      const msg = 'Failed to export CSV';
      setError(msg);
      showToast(msg, 'error');
    } finally {
      setIsExporting(false);
    }
  };

  return {
    leads,
    totalCount,
    filters,
    isLoading,
    isExporting,
    isUpdating,
    error,
    setFilters,
    fetchLeads,
    updateLeadStatus,
    updateLeadNotes,
    toggleFavorite,
    exportCsv,
  };
}
