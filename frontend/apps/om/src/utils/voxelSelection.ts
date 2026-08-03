import type { MapRegionVolume } from '@robots/shared-types';
import type { RegionGridSelection } from '../stores/mapEditorStore';

const GRID_INDEX_SCALE = 1_000_000;
const COORDINATE_SCALE = 1_000_000_000;

interface VoxelCell {
  x: number;
  y: number;
  z: number;
  sizeX: number;
  sizeY: number;
  sizeZ: number;
  xIndex: number;
  yIndex: number;
  zIndex: number;
}

interface Rectangle {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  z: number;
  minXIndex: number;
  maxXIndex: number;
  minYIndex: number;
  maxYIndex: number;
  zIndex: number;
  sizeX: number;
  sizeY: number;
  sizeZ: number;
}

interface Cuboid extends Rectangle {
  maxZ: number;
  maxZIndex: number;
}

export interface RegionSelectionUnion {
  voxelCount: number;
  volumes: MapRegionVolume[];
}

function coordinateKey(value: number): number {
  return Math.round(value * COORDINATE_SCALE);
}

function gridIndex(value: number, size: number): number {
  return Math.round((value / size) * GRID_INDEX_SCALE);
}

function normalize(value: number): number {
  return Math.round(value * COORDINATE_SCALE) / COORDINATE_SCALE;
}

function dimensionKey(cell: VoxelCell): string {
  return `${coordinateKey(cell.sizeX)}:${coordinateKey(cell.sizeY)}:${coordinateKey(cell.sizeZ)}`;
}

function voxelKey(cell: VoxelCell): string {
  return [
    coordinateKey(cell.x), coordinateKey(cell.y), coordinateKey(cell.z),
    coordinateKey(cell.x + cell.sizeX), coordinateKey(cell.y + cell.sizeY), coordinateKey(cell.z + cell.sizeZ),
  ].join(':');
}

function addSelectionVoxels(selection: RegionGridSelection, voxels: Map<string, VoxelCell>): void {
  const { start, end } = selection;
  const minX = Math.min(start.x, end.x);
  const maxX = Math.max(start.x, end.x);
  const minY = Math.min(start.y, end.y);
  const maxY = Math.max(start.y, end.y);
  const minXIndex = gridIndex(minX, start.sizeX);
  const maxXIndex = gridIndex(maxX, start.sizeX);
  const minYIndex = gridIndex(minY, start.sizeY);
  const maxYIndex = gridIndex(maxY, start.sizeY);
  const minZIndex = gridIndex(start.z, start.sizeZ);

  for (let zIndex = minZIndex; zIndex < minZIndex + selection.heightCells * GRID_INDEX_SCALE; zIndex += GRID_INDEX_SCALE) {
    const z = normalize(start.z + ((zIndex - minZIndex) / GRID_INDEX_SCALE) * start.sizeZ);
    for (let yIndex = minYIndex; yIndex <= maxYIndex; yIndex += GRID_INDEX_SCALE) {
      const y = normalize(minY + ((yIndex - minYIndex) / GRID_INDEX_SCALE) * start.sizeY);
      for (let xIndex = minXIndex; xIndex <= maxXIndex; xIndex += GRID_INDEX_SCALE) {
        const x = normalize(minX + ((xIndex - minXIndex) / GRID_INDEX_SCALE) * start.sizeX);
        const voxel = { x, y, z, sizeX: start.sizeX, sizeY: start.sizeY, sizeZ: start.sizeZ, xIndex, yIndex, zIndex };
        voxels.set(voxelKey(voxel), voxel);
      }
    }
  }
}

function rectanglesForVoxels(voxels: VoxelCell[]): Rectangle[] {
  const layers = new Map<number, Map<number, VoxelCell[]>>();
  for (const voxel of voxels) {
    const rows = layers.get(voxel.zIndex) ?? new Map<number, VoxelCell[]>();
    const row = rows.get(voxel.yIndex) ?? [];
    row.push(voxel);
    rows.set(voxel.yIndex, row);
    layers.set(voxel.zIndex, rows);
  }

  const rectangles: Rectangle[] = [];
  for (const [zIndex, rows] of [...layers.entries()].sort(([left], [right]) => left - right)) {
    const active = new Map<string, Rectangle>();
    for (const [yIndex, row] of [...rows.entries()].sort(([left], [right]) => left - right)) {
      const current = new Map<string, Rectangle>();
      const sortedRow = [...row].sort((left, right) => left.xIndex - right.xIndex);
      let start = sortedRow[0];
      let previous = sortedRow[0];

      const addRun = () => {
        const key = `${start.xIndex}:${previous.xIndex}`;
        const existing = active.get(key);
        if (existing && existing.maxYIndex + GRID_INDEX_SCALE === yIndex) {
          existing.maxYIndex = yIndex;
          existing.maxY = normalize(previous.y + previous.sizeY);
          current.set(key, existing);
          return;
        }
        const rectangle: Rectangle = {
          minX: start.x,
          maxX: normalize(previous.x + previous.sizeX),
          minY: previous.y,
          maxY: normalize(previous.y + previous.sizeY),
          z: previous.z,
          minXIndex: start.xIndex,
          maxXIndex: previous.xIndex,
          minYIndex: yIndex,
          maxYIndex: yIndex,
          zIndex,
          sizeX: previous.sizeX,
          sizeY: previous.sizeY,
          sizeZ: previous.sizeZ,
        };
        rectangles.push(rectangle);
        current.set(key, rectangle);
      };

      for (const voxel of sortedRow.slice(1)) {
        if (voxel.xIndex === previous.xIndex + GRID_INDEX_SCALE) {
          previous = voxel;
          continue;
        }
        addRun();
        start = voxel;
        previous = voxel;
      }
      addRun();
      active.clear();
      for (const [key, rectangle] of current) active.set(key, rectangle);
    }
  }
  return rectangles;
}

function cuboidsForRectangles(rectangles: Rectangle[]): Cuboid[] {
  const byLayer = new Map<number, Rectangle[]>();
  for (const rectangle of rectangles) {
    const layer = byLayer.get(rectangle.zIndex) ?? [];
    layer.push(rectangle);
    byLayer.set(rectangle.zIndex, layer);
  }

  const cuboids: Cuboid[] = [];
  let active = new Map<string, Cuboid>();
  for (const [zIndex, layer] of [...byLayer.entries()].sort(([left], [right]) => left - right)) {
    const current = new Map<string, Cuboid>();
    for (const rectangle of layer) {
      const key = `${rectangle.minXIndex}:${rectangle.maxXIndex}:${rectangle.minYIndex}:${rectangle.maxYIndex}`;
      const existing = active.get(key);
      if (existing && existing.maxZIndex + GRID_INDEX_SCALE === zIndex) {
        existing.maxZIndex = zIndex;
        existing.maxZ = normalize(rectangle.z + rectangle.sizeZ);
        current.set(key, existing);
        continue;
      }
      const cuboid: Cuboid = {
        ...rectangle,
        maxZ: normalize(rectangle.z + rectangle.sizeZ),
        maxZIndex: zIndex,
      };
      cuboids.push(cuboid);
      current.set(key, cuboid);
    }
    active = current;
  }
  return cuboids;
}

/**
 * Converts all drag records into one non-overlapping voxel union. Drag records remain
 * separate in the editor store so the user can undo the most recent drag.
 */
export function createRegionSelectionUnion(selections: RegionGridSelection[]): RegionSelectionUnion {
  const voxels = new Map<string, VoxelCell>();
  for (const selection of selections) addSelectionVoxels(selection, voxels);

  const grouped = new Map<string, VoxelCell[]>();
  for (const voxel of voxels.values()) {
    const cells = grouped.get(dimensionKey(voxel)) ?? [];
    cells.push(voxel);
    grouped.set(dimensionKey(voxel), cells);
  }

  const volumes = [...grouped.values()]
    .flatMap((cells) => cuboidsForRectangles(rectanglesForVoxels(cells)))
    .sort((left, right) => left.z - right.z || left.minY - right.minY || left.minX - right.minX)
    .map((cuboid) => ({
      polygon: [
        [cuboid.minX, cuboid.minY],
        [cuboid.maxX, cuboid.minY],
        [cuboid.maxX, cuboid.maxY],
        [cuboid.minX, cuboid.maxY],
      ],
      min_z: cuboid.z,
      max_z: cuboid.maxZ,
    }));

  return { voxelCount: voxels.size, volumes };
}
