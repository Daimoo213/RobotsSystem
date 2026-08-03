import { create } from 'zustand';
import type { GridMapConfig } from '@robots/shared-types';

export const DEFAULT_GRID_CONFIG: GridMapConfig = {
  origin_x: -30,
  origin_y: -30,
  origin_z: 0,
  cell_length: 1,
  cell_width: 1,
  cell_height: 0.5,
  extent_length: 60,
  extent_width: 60,
  vertical_layers: 6,
  line_color: '#5BB7FF',
  line_thickness: 0.04,
  opacity: 0.38,
};

export type MapEditorMode = 'select' | 'point' | 'region' | 'path';
export type MapEntityKind = 'point' | 'region' | 'path';

export interface GridCell {
  x: number;
  y: number;
  z: number;
  sizeX: number;
  sizeY: number;
  sizeZ: number;
}

export interface RegionGridSelection {
  start: GridCell;
  end: GridCell;
  /** Height is captured when the drag begins so later UI changes do not alter prior selections. */
  heightCells: number;
}

export interface MapEntitySelection {
  kind: MapEntityKind;
  id: string;
}

interface MapEditorState {
  isOpen: boolean;
  mode: MapEditorMode;
  gridVisible: boolean;
  gridConfig: GridMapConfig;
  editLayer: number;
  regionHeightCells: number;
  pointCell: GridCell | null;
  regionSelections: RegionGridSelection[];
  pathCells: GridCell[];
  selectedEntity: MapEntitySelection | null;
  setOpen: (isOpen: boolean) => void;
  setMode: (mode: MapEditorMode) => void;
  setGridVisible: (visible: boolean) => void;
  setGridConfig: (config: GridMapConfig) => void;
  setEditLayer: (layer: number) => void;
  setRegionHeightCells: (height: number) => void;
  setPointCell: (cell: GridCell | null) => void;
  appendRegionSelection: (selection: RegionGridSelection) => void;
  updateLastRegionSelection: (selection: RegionGridSelection) => void;
  undoLastRegionSelection: () => void;
  clearRegionSelections: () => void;
  appendPathCell: (cell: GridCell) => void;
  setPathCells: (cells: GridCell[]) => void;
  undoLastPathPoint: () => void;
  clearPathCells: () => void;
  selectEntity: (selection: MapEntitySelection | null) => void;
  clearDraft: () => void;
}

export const useMapEditorStore = create<MapEditorState>((set) => ({
  isOpen: false,
  mode: 'select',
  gridVisible: false,
  gridConfig: DEFAULT_GRID_CONFIG,
  editLayer: 0,
  regionHeightCells: 1,
  pointCell: null,
  regionSelections: [],
  pathCells: [],
  selectedEntity: null,
  setOpen: (isOpen) => set(isOpen ? { isOpen } : {
    isOpen,
    mode: 'select',
    pointCell: null,
    regionSelections: [],
    pathCells: [],
    selectedEntity: null,
  }),
  setMode: (mode) => set((state) => ({
    mode,
    gridVisible: mode === 'select' ? state.gridVisible : true,
    pointCell: null,
    regionSelections: [],
    pathCells: [],
    selectedEntity: null,
  })),
  setGridVisible: (gridVisible) => set({ gridVisible }),
  setGridConfig: (gridConfig) => set((state) => ({
    gridConfig,
    editLayer: Math.min(state.editLayer, gridConfig.vertical_layers - 1),
    regionHeightCells: Math.min(state.regionHeightCells, gridConfig.vertical_layers),
  })),
  setEditLayer: (editLayer) => set((state) => ({
    editLayer: Math.max(0, Math.min(Math.round(editLayer), state.gridConfig.vertical_layers - 1)),
  })),
  setRegionHeightCells: (regionHeightCells) => set((state) => ({
    regionHeightCells: Math.max(1, Math.min(Math.round(regionHeightCells), state.gridConfig.vertical_layers - state.editLayer)),
  })),
  setPointCell: (pointCell) => set({ pointCell, selectedEntity: null }),
  appendRegionSelection: (selection) => set((state) => ({
    regionSelections: [...state.regionSelections, selection],
    selectedEntity: null,
  })),
  updateLastRegionSelection: (selection) => set((state) => ({
    regionSelections: state.regionSelections.length
      ? [...state.regionSelections.slice(0, -1), selection]
      : [selection],
    selectedEntity: null,
  })),
  undoLastRegionSelection: () => set((state) => ({
    regionSelections: state.regionSelections.slice(0, -1),
  })),
  clearRegionSelections: () => set({ regionSelections: [] }),
  appendPathCell: (cell) => set((state) => {
    const previous = state.pathCells[state.pathCells.length - 1];
    if (previous && previous.x === cell.x && previous.y === cell.y && previous.z === cell.z) return state;
    return { pathCells: [...state.pathCells, cell], selectedEntity: null };
  }),
  setPathCells: (pathCells) => set({ pathCells, selectedEntity: null }),
  undoLastPathPoint: () => set((state) => ({ pathCells: state.pathCells.slice(0, -1) })),
  clearPathCells: () => set({ pathCells: [] }),
  selectEntity: (selectedEntity) => set({
    selectedEntity,
    mode: 'select',
    pointCell: null,
    regionSelections: [],
    pathCells: [],
  }),
  clearDraft: () => set({ pointCell: null, regionSelections: [], pathCells: [] }),
}));
