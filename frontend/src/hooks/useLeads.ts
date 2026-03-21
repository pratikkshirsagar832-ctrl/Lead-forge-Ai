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
  const [isUpdating, setIsUpdating] = useState<Record<string, boolean>>({});

  const fetchLeads = useCallback(async () => {
    try {
      setIsLoading(true);
      const params = new URLSearchParams();
      if (filters.search) params.append('search', filters.search);
      if (filters.status) params.append('status', filters.status);
      if (filters.category) params.append('category', filters.category);
      if (filters.isFavorite !== null) params.append('is_favorite', String(filters.isFavorite));
      params.append('skip', String((filters.page - 1) * filters.limit));
      params.append('limit', String(filters.limit));

      const { data } = await api.get(`${API_ROUTES.leads.list}?${params.toString()}`);
      setLeads(data.items, data.total);
    } catch (error) {
      showToast('Failed to load leads', 'error');
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [filters, setLeads, showToast]);

  const updateLeadStatus = async (id: string, status: string) => {
    try {
      setIsUpdating((prev) => ({ ...prev, [id]: true }));
      // Optimistic update
      updateLeadInStore(id, { status });
      const { data } = await api.patch(API_ROUTES.leads.status(id), { status });
      updateLeadInStore(id, { status: data.status });
      showToast('Status updated', 'success');
    } catch (error) {
      // Revert optimism if needed (complex, but simple fetch works too)
      fetchLeads();
      showToast('Failed to update status', 'error');
    } finally {
      setIsUpdating((prev) => ({ ...prev, [id]: false }));
    }
  };

  const updateLeadNotes = async (id: string, notes: string) => {
    try {
      setIsUpdating((prev) => ({ ...prev, [`${id}_notes`]: true }));
      updateLeadInStore(id, { notes });
      await api.patch(API_ROUTES.leads.notes(id), { notes });
      showToast('Notes saved', 'success', 2000);
    } catch (error) {
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
      const params = new URLSearchParams();
      if (filters.search) params.append('search', filters.search);
      if (filters.status) params.append('status', filters.status);
      if (filters.category) params.append('category', filters.category);
      if (filters.isFavorite !== null) params.append('is_favorite', String(filters.isFavorite));

      const response = await api.get(`${API_ROUTES.leads.export}?${params.toString()}`, {
        responseType: 'blob',
      });

      // Create download link
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
      showToast('Failed to export CSV', 'error');
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
    setFilters,
    fetchLeads,
    updateLeadStatus,
    updateLeadNotes,
    toggleFavorite,
    exportCsv,
  };
}
