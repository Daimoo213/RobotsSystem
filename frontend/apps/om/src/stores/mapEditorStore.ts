import { create } from 'zustand';

export const MAP_GRID_SIZE = 1;

export type MapEditorMode = 'select' | 'point' | 'region';
export type MapEntityKind = 'point' | 'region';

export interface GridCell {
  x: number;
  y: number;
  size: number;
}

export interface RegionGridSelection {
  start: GridCell;
  end: GridCell;
}

export interface MapEntitySelection {
  kind: MapEntityKind;
  id: string;
}

interface MapEditorState {
  isOpen: boolean;
  mode: MapEditorMode;
  pointCell: GridCell | null;
  regionSelection: RegionGridSelection | null;
  selectedEntity: MapEntitySelection | null;
  setOpen: (isOpen: boolean) => void;
  setMode: (mode: MapEditorMode) => void;
  setPointCell: (cell: GridCell | null) => void;
  setRegionSelection: (selection: RegionGridSelection | null) => void;
  selectEntity: (selection: MapEntitySelection | null) => void;
  clearDraft: () => void;
}

export const useMapEditorStore = create<MapEditorState>((set) => ({
  isOpen: false,
  mode: 'select',
  pointCell: null,
  regionSelection: null,
  selectedEntity: null,
  setOpen: (isOpen) => set(isOpen ? { isOpen } : {
    isOpen,
    mode: 'select',
    pointCell: null,
    regionSelection: null,
    selectedEntity: null,
  }),
  setMode: (mode) => set({
    mode,
    pointCell: null,
    regionSelection: null,
    selectedEntity: null,
  }),
  setPointCell: (pointCell) => set({ pointCell, selectedEntity: null }),
  setRegionSelection: (regionSelection) => set({ regionSelection, selectedEntity: null }),
  selectEntity: (selectedEntity) => set({
    selectedEntity,
    mode: 'select',
    pointCell: null,
    regionSelection: null,
  }),
  clearDraft: () => set({ pointCell: null, regionSelection: null }),
}));
