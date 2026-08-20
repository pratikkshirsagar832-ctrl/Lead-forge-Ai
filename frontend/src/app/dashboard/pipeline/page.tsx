'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import Link from 'next/link';
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { motion } from 'framer-motion';
import { useToast } from '@/hooks/useToast';
import { PostTypeBadge } from '@/components/dashboard/PostTypeBadge';
import { API_ROUTES, USER_STATUSES } from '@/lib/constants';
import type { LeadListItem } from '@/lib/types';
import api from '@/lib/api';
import { cn } from '@/lib/utils';
import {
  Building2,
  Star,
  Phone,
  Globe,
  MapPin,
  GripVertical,
  Plus,
  Loader2,
  ArrowRight,
  Linkedin,
} from 'lucide-react';

const PIPELINE_STAGES = [
  { key: 'new', label: 'New', color: USER_STATUSES.new.color },
  { key: 'contacted', label: 'Contacted', color: USER_STATUSES.contacted.color },
  { key: 'replied', label: 'Replied', color: USER_STATUSES.replied.color },
  { key: 'converted', label: 'Converted', color: USER_STATUSES.converted.color },
  { key: 'lost', label: 'Lost', color: USER_STATUSES.lost.color },
] as const;

type StageKey = typeof PIPELINE_STAGES[number]['key'];

function PipelineCard({ lead, isDragOverlay }: { lead: LeadListItem; isDragOverlay?: boolean }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: lead.id,
    data: { lead },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const ratingStars = lead.rating
    ? Array.from({ length: 5 }, (_, i) => i < Math.round(lead.rating!))
    : null;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        'group rounded-xl border border-steel/15 bg-gradient-to-br from-sapphire/40 to-navy/70 p-3.5 shadow-sm transition-all duration-200',
        isDragging && 'opacity-50 shadow-lg',
        isDragOverlay && 'shadow-xl border-steel/30 scale-105 rotate-[1deg]'
      )}
    >
      <div className="flex items-start gap-2">
        <button
          {...attributes}
          {...listeners}
          className="mt-0.5 text-ice/30 hover:text-ice/60 transition-colors cursor-grab active:cursor-grabbing shrink-0"
          aria-label="Drag to reorder"
        >
          <GripVertical className="w-4 h-4" />
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-offwhite truncate">
              {lead.business_name}
            </span>
            {lead.lead_category && (
              <span
                className={cn(
                  'text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0',
                  lead.lead_category === 'hot'
                    ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                    : 'bg-amber-500/15 text-amber-400 border border-amber-500/25'
                )}
              >
                {lead.lead_category.toUpperCase()}
              </span>
            )}
            {lead.source === 'linkedin' ? (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0 bg-sky-500/15 text-sky-400 border border-sky-500/25 flex items-center gap-0.5">
                <Linkedin className="w-2.5 h-2.5" />
                LI
              </span>
            ) : (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0 bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 flex items-center gap-0.5">
                <MapPin className="w-2.5 h-2.5" />
                Maps
              </span>
            )}
            {lead.source === 'linkedin' && <PostTypeBadge postType={lead.post_type} />}
          </div>

          {lead.category && (
            <p className="text-[11px] text-ice/50 mb-2 truncate">{lead.category}</p>
          )}

          <div className="flex items-center gap-3 flex-wrap">
            {ratingStars && (
              <span className="flex items-center gap-0.5">
                {ratingStars.map((filled, i) => (
                  <Star
                    key={i}
                    className={cn('w-3 h-3', filled ? 'text-amber-400 fill-amber-400' : 'text-ice/20')}
                  />
                ))}
                <span className="text-[10px] text-ice/40 ml-0.5">({lead.total_reviews})</span>
              </span>
            )}

            {lead.website_health_score !== null && lead.website_health_score !== undefined && (
              <span
                className={cn(
                  'text-[10px] font-bold px-1.5 py-0.5 rounded',
                  lead.website_health_score >= 70
                    ? 'bg-emerald-500/15 text-emerald-400'
                    : lead.website_health_score >= 40
                    ? 'bg-amber-500/15 text-amber-400'
                    : 'bg-rose-500/15 text-rose-400'
                )}
              >
                {lead.website_health_score}
              </span>
            )}
          </div>

          <div className="mt-2 space-y-1">
            {lead.phone && (
              <a
                href={`tel:${lead.phone}`}
                className="flex items-center gap-1.5 text-[11px] text-ice/40 hover:text-ice/70 transition-colors"
              >
                <Phone className="w-3 h-3" />
                <span className="truncate">{lead.phone}</span>
              </a>
            )}
            {lead.website_url && (
              <a
                href={lead.website_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-[11px] text-ice/40 hover:text-steel transition-colors"
              >
                <Globe className="w-3 h-3" />
                <span className="truncate">{lead.website_url.replace(/^https?:\/\//, '')}</span>
              </a>
            )}
            {lead.full_address && (
              <div className="flex items-center gap-1.5 text-[11px] text-ice/40">
                <MapPin className="w-3 h-3 shrink-0" />
                <span className="truncate">{lead.full_address}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ColumnSkeleton() {
  return (
    <div className="flex flex-col gap-3 animate-pulse">
      <div className="h-6 w-24 rounded bg-steel/10" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-28 rounded-xl bg-sapphire/20 border border-steel/10" />
      ))}
    </div>
  );
}

function EmptyColumn({ stageLabel }: { stageLabel: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-10 h-10 rounded-full bg-ocean/30 flex items-center justify-center mb-3">
        <Plus className="w-5 h-5 text-ice/30" />
      </div>
      <p className="text-sm font-medium text-ice/40">No leads in {stageLabel}</p>
      <p className="text-xs text-ice/30 mt-1">Drop leads here or add from search</p>
    </div>
  );
}

function KanbanColumn({
  stage,
  leads,
  activeId,
}: {
  stage: typeof PIPELINE_STAGES[number];
  leads: LeadListItem[];
  activeId: string | null;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: stage.key,
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex flex-col rounded-2xl border border-steel/15 bg-gradient-to-b from-sapphire/20 to-navy/50 min-h-[400px] transition-all duration-200',
        isOver && 'border-steel/40 shadow-lg'
      )}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-steel/10">
        <div className="flex items-center gap-2.5">
          <div
            className="w-2.5 h-2.5 rounded-full shadow-sm"
            style={{ backgroundColor: stage.color }}
          />
          <h3 className="text-sm font-bold text-offwhite">{stage.label}</h3>
          <span className="text-[11px] font-semibold text-ice/40 bg-ocean/30 px-1.5 py-0.5 rounded-full">
            {leads.length}
          </span>
        </div>
      </div>

      <div className="flex-1 p-3 space-y-3 overflow-y-auto max-h-[calc(100vh-280px)]">
        <SortableContext items={leads.map((l) => l.id)} strategy={verticalListSortingStrategy}>
          {leads.length === 0 ? (
            <EmptyColumn stageLabel={stage.label} />
          ) : (
            leads.map((lead) => (
              <PipelineCard key={lead.id} lead={lead} />
            ))
          )}
        </SortableContext>

        {/* Drop zone indicator when dragging over empty column */}
        {leads.length === 0 && activeId && (
          <div className="h-20 rounded-xl border-2 border-dashed border-steel/30 bg-steel/5 flex items-center justify-center">
            <p className="text-xs text-ice/30">Drop here</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function PipelinePage() {
  const { showToast } = useToast();
  const [leadsByStage, setLeadsByStage] = useState<Record<StageKey, LeadListItem[]>>({
    new: [],
    contacted: [],
    replied: [],
    converted: [],
    lost: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeLead, setActiveLead] = useState<LeadListItem | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const dragSourceStageRef = useRef<StageKey | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
    useSensor(KeyboardSensor)
  );

  const fetchAllLeads = useCallback(async () => {
    try {
      setIsLoading(true);
      const grouped: Record<StageKey, LeadListItem[]> = {
        new: [],
        contacted: [],
        replied: [],
        converted: [],
        lost: [],
      };
      let total = 0;

      const statuses = ['new', 'contacted', 'replied', 'converted', 'lost'];
      const results = await Promise.all(
        statuses.map(async (status) => {
          const params = new URLSearchParams({ user_status: status, per_page: '100' });
          const { data } = await api.get(`${API_ROUTES.leads.list}?${params.toString()}`);
          return { status, items: data.items || [] };
        })
      );

      for (const { status, items } of results) {
        grouped[status as StageKey] = items;
        total += items.length;
      }

      setLeadsByStage(grouped);
      setTotalCount(total);
    } catch {
      showToast('Failed to load pipeline leads', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchAllLeads();
  }, [fetchAllLeads]);

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const { active } = event;
    setActiveId(active.id as string);

    for (const stageKey of PIPELINE_STAGES.map((s) => s.key)) {
      const found = leadsByStage[stageKey].find((l) => l.id === active.id);
      if (found) {
        setActiveLead(found);
        dragSourceStageRef.current = stageKey;
        break;
      }
    }
  }, [leadsByStage]);

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const { active, over } = event;
    if (!over || !active) return;

    const activeLeadId = active.id as string;
    const overId = over.id as string;

    let sourceStage: StageKey | null = null;
    let targetStage: StageKey | null = null;

    for (const stageKey of PIPELINE_STAGES.map((s) => s.key)) {
      if (leadsByStage[stageKey].some((l) => l.id === activeLeadId)) {
        sourceStage = stageKey;
        break;
      }
    }
    for (const stageKey of PIPELINE_STAGES.map((s) => s.key)) {
      if (leadsByStage[stageKey].some((l) => l.id === overId)) {
        targetStage = stageKey;
        break;
      }
    }
    if (!targetStage) {
      const overInColumns = PIPELINE_STAGES.find((s) => s.key === overId);
      if (overInColumns) targetStage = overInColumns.key;
    }

    if (!sourceStage || !targetStage || sourceStage === targetStage) return;

    setLeadsByStage((prev) => {
      const lead = prev[sourceStage!].find((l) => l.id === activeLeadId);
      if (!lead) return prev;
      return {
        ...prev,
        [sourceStage!]: prev[sourceStage!].filter((l) => l.id !== activeLeadId),
        [targetStage!]: [...prev[targetStage!], { ...lead, user_status: targetStage! }],
      };
    });
  }, [leadsByStage]);

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    const { active } = event;
    setActiveId(null);
    setActiveLead(null);

    if (!active) return;

    const activeLeadId = active.id as string;

    let currentStage: StageKey | null = null;
    for (const stageKey of PIPELINE_STAGES.map((s) => s.key)) {
      if (leadsByStage[stageKey].some((l) => l.id === activeLeadId)) {
        currentStage = stageKey;
        break;
      }
    }

    if (!currentStage || currentStage === dragSourceStageRef.current) return;

    setIsUpdating(true);
    try {
      await api.patch(API_ROUTES.leads.status(activeLeadId), { user_status: currentStage });
      showToast(`Moved to ${USER_STATUSES[currentStage].label}`, 'success');
    } catch {
      fetchAllLeads();
      showToast('Failed to update status', 'error');
    } finally {
      setIsUpdating(false);
    }
  }, [leadsByStage, showToast, fetchAllLeads]);

  const statCards = useMemo(() => {
    return PIPELINE_STAGES.map((stage) => ({
      ...stage,
      count: leadsByStage[stage.key].length,
    }));
  }, [leadsByStage]);

  if (isLoading) {
    return (
      <div className="space-y-6 animate-in fade-in duration-500 max-w-7xl mx-auto">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6">
          <div>
            <h1 className="text-3xl font-extrabold text-offwhite tracking-tight">Lead Manager</h1>
            <p className="text-ice/60 mt-2 text-sm font-medium">Drag leads between stages to track your sales pipeline.</p>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 rounded-xl bg-sapphire/20 border border-steel/10 animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="rounded-2xl border border-steel/15 bg-gradient-to-b from-sapphire/20 to-navy/50 p-4 space-y-3">
              <ColumnSkeleton />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500 max-w-7xl mx-auto">
      <div className="absolute -inset-10 bg-gradient-to-r from-steel/10 via-ocean/5 to-transparent blur-3xl rounded-full pointer-events-none -z-10" />

      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 relative">
        <div>
          <h1 className="text-3xl font-extrabold text-offwhite tracking-tight flex items-center gap-3">
            Lead Manager
          </h1>
          <p className="text-ice/60 mt-2 text-sm font-medium">
            Drag leads between stages to track your sales pipeline.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm font-medium text-ice/40">
            <span className="text-steel font-bold">{totalCount}</span> total leads
          </div>
          {isUpdating && (
            <div className="flex items-center gap-2 text-sm text-ice/60">
              <Loader2 className="w-4 h-4 animate-spin" />
              Saving...
            </div>
          )}
          <Link
            href="/dashboard/leads"
            className="flex items-center gap-2 text-sm font-semibold text-offwhite bg-gradient-to-r from-steel to-violet/80 px-4 py-2 rounded-xl hover:opacity-90 transition-opacity shadow-lg shadow-steel/20"
          >
            <ArrowRight className="w-4 h-4" />
            Leads View
          </Link>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {statCards.map((stage) => (
          <div
            key={stage.key}
            className="flex items-center gap-3 px-4 py-3 rounded-xl bg-gradient-to-br from-sapphire/30 to-navy/70 border border-steel/15 shadow-sm"
          >
            <div
              className="w-3 h-3 rounded-full shrink-0 shadow-sm"
              style={{ backgroundColor: stage.color }}
            />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-ice/50">{stage.label}</p>
              <p className="text-lg font-extrabold text-offwhite">{stage.count}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Kanban board */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {PIPELINE_STAGES.map((stage) => (
            <KanbanColumn
              key={stage.key}
              stage={stage}
              leads={leadsByStage[stage.key]}
              activeId={activeId}
            />
          ))}
        </div>

        <DragOverlay>
          {activeLead ? (
            <PipelineCard lead={activeLead} isDragOverlay />
          ) : null}
        </DragOverlay>
      </DndContext>

      {totalCount === 0 && !isLoading && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 rounded-2xl bg-ocean/30 flex items-center justify-center mb-6">
            <Building2 className="w-8 h-8 text-ice/40" />
          </div>
          <h3 className="text-xl font-bold text-offwhite mb-2">No leads yet</h3>
          <p className="text-ice/50 text-sm max-w-md mb-6">
            Start by running a search to find leads, then manage them through your sales pipeline.
          </p>
          <Link
            href="/dashboard/search"
            className="flex items-center gap-2 text-sm font-semibold text-offwhite bg-gradient-to-r from-steel to-violet/80 px-5 py-2.5 rounded-xl hover:opacity-90 transition-opacity"
          >
            Run a Search
          </Link>
        </div>
      )}
    </div>
  );
}
