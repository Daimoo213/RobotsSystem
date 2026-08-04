import { create } from 'zustand';
import { VOXEL_CELL_SIZE_M, VOXEL_CELL_VOLUME_M3, type GridMapConfig } from '@robots/shared-types';

export const DEFAULT_GRID_CONFIG: GridMapConfig = {
  origin_x: -30,
  origin_y: -30,
  origin_z: 0,
  cell_volume_m3: VOXEL_CELL_VOLUME_M3,
  cell_length: VOXEL_CELL_SIZE_M,
  cell_width: VOXEL_CELL_SIZE_M,
  cell_height: VOXEL_CELL_SIZE_M,
  extent_length: 60,
  extent_width: 60,
  vertical_layers: 6,
  display_voxel_multiplier: 1,
  line_color: '#5BB7FF',
  line_thickness: 0.004,
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

/** Keep the project lattice fixed while allowing one editor hit target to cover a cube of base voxels. */
export function getDisplayGridConfig(config: GridMapConfig): GridMapConfig {
  const multiplier = Math.max(1, Math.round(config.display_voxel_multiplier || 1));
  return {
    ...config,
    cell_length: config.cell_length * multiplier,
    cell_width: config.cell_width * multiplier,
    cell_height: config.cell_height * multiplier,
    vertical_layers: Math.max(1, Math.ceil(config.vertical_layers / multiplier)),
  };
}

export interface RegionGridSelection {
  start: GridCell;
  end: GridCell;
  /** Height is captured when the drag begins so later UI changes do not alter prior selections. */
  heightCells: number;
  /** Top boundary of the selection, capped to the real map volume for a partial final display layer. */
  maxZ?: number;
}

export interface MapEntitySelection {
  kind: MapEntityKind;
  id: string;
}

function editingLatticeChanged(previous: GridMapConfig, next: GridMapConfig): boolean {
  return previous.display_voxel_multiplier !== next.display_voxel_multiplier
    || previous.origin_x !== next.origin_x
    || previous.origin_y !== next.origin_y
    || previous.origin_z !== next.origin_z
    || previous.extent_length !== next.extent_length
    || previous.extent_width !== next.extent_width
    || previous.vertical_layers !== next.vertical_layers
    || previous.cell_length !== next.cell_length
    || previous.cell_width !== next.cell_width
    || previous.cell_height !== next.cell_height;
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
  /** Completed two-endpoint road segments waiting for one atomic save. */
  roadSegments: GridCell[][];
  /** The first endpoint of the next road segment, if one has been selected. */
  pendingRoadStart: GridCell | null;
  /** An existing persisted road being replaced; null means a new road network. */
  editingPathId: string | null;
  pathCells: GridCell[];
  pathPreviewWidthM: number;
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
  beginRoadNetwork: () => void;
  beginPathGeometryEdit: (pathId: string) => void;
  appendPathCell: (cell: GridCell) => void;
  undoLastPathInput: () => void;
  clearPathDraft: () => void;
  setPathPreviewWidthM: (width: number) => void;
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
  roadSegments: [],
  pendingRoadStart: null,
  editingPathId: null,
  pathCells: [],
  pathPreviewWidthM: VOXEL_CELL_SIZE_M,
  selectedEntity: null,
  setOpen: (isOpen) => set(isOpen ? { isOpen } : {
    isOpen,
    mode: 'select',
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
    selectedEntity: null,
  }),
  setMode: (mode) => set((state) => ({
    mode,
    gridVisible: mode === 'select' ? state.gridVisible : true,
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
    selectedEntity: null,
  })),
  setGridVisible: (gridVisible) => set({ gridVisible }),
  setGridConfig: (gridConfig) => set((state) => ({
    gridConfig,
    editLayer: Math.min(state.editLayer, getDisplayGridConfig(gridConfig).vertical_layers - 1),
    regionHeightCells: Math.min(state.regionHeightCells, getDisplayGridConfig(gridConfig).vertical_layers),
    ...(editingLatticeChanged(state.gridConfig, gridConfig) ? {
      pointCell: null,
      regionSelections: [],
      roadSegments: [],
      pendingRoadStart: null,
      editingPathId: null,
      pathCells: [],
    } : {}),
  })),
  setEditLayer: (editLayer) => set((state) => ({
    editLayer: Math.max(0, Math.min(Math.round(editLayer), getDisplayGridConfig(state.gridConfig).vertical_layers - 1)),
  })),
  setRegionHeightCells: (regionHeightCells) => set((state) => ({
    regionHeightCells: Math.max(1, Math.min(Math.round(regionHeightCells), getDisplayGridConfig(state.gridConfig).vertical_layers - state.editLayer)),
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
  beginRoadNetwork: () => set({
    mode: 'path',
    gridVisible: true,
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
    selectedEntity: null,
  }),
  beginPathGeometryEdit: (pathId) => set({
    mode: 'path',
    gridVisible: true,
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: pathId,
    pathCells: [],
    selectedEntity: { kind: 'path', id: pathId },
  }),
  appendPathCell: (cell) => set((state) => {
    const sameCell = (other: GridCell) => other.x === cell.x && other.y === cell.y && other.z === cell.z;
    if (state.editingPathId) {
      const lastCell = state.pathCells[state.pathCells.length - 1];
      if (lastCell && sameCell(lastCell)) return state;
      return {
        pathCells: state.pathCells.length === 2 ? [cell] : [...state.pathCells, cell],
        selectedEntity: { kind: 'path', id: state.editingPathId },
      };
    }
    if (state.pendingRoadStart) {
      if (sameCell(state.pendingRoadStart)) return state;
      return {
        roadSegments: [...state.roadSegments, [state.pendingRoadStart, cell]],
        pendingRoadStart: null,
        selectedEntity: null,
      };
    }
    return { pendingRoadStart: cell, selectedEntity: null };
  }),
  undoLastPathInput: () => set((state) => {
    if (state.editingPathId) return { pathCells: state.pathCells.slice(0, -1) };
    if (state.pendingRoadStart) return { pendingRoadStart: null };
    return { roadSegments: state.roadSegments.slice(0, -1) };
  }),
  clearPathDraft: () => set({
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
  }),
  setPathPreviewWidthM: (pathPreviewWidthM) => set({ pathPreviewWidthM: Math.max(VOXEL_CELL_SIZE_M, pathPreviewWidthM) }),
  selectEntity: (selectedEntity) => set({
    selectedEntity,
    mode: 'select',
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
  }),
  clearDraft: () => set({
    pointCell: null,
    regionSelections: [],
    roadSegments: [],
    pendingRoadStart: null,
    editingPathId: null,
    pathCells: [],
    pathPreviewWidthM: VOXEL_CELL_SIZE_M,
  }),
}));
