// ─── Room walkable zone helpers ───────────────────────────────────
// Extracted from BotAnimations.tsx to avoid mixed exports (React + non-React)
// which breaks Vite HMR Fast Refresh.

import { getBlueprintForRoom, gridToWorld } from '@/lib/grid'

// ─── Walkable Zone (Grid-Based) ─────────────────────────────────

export interface WalkableCenter {
  x: number
  z: number
  radius: number
}

/**
 * Returns a safe circular walkable area in the center of each room.
 * Uses the grid blueprint's walkableCenter + computed radius from walkable cells.
 */
export function getWalkableCenter(
  roomName: string,
  roomSize: number,
  roomPosition: [number, number, number]
): WalkableCenter {
  const rx = roomPosition[0]
  const rz = roomPosition[2]
  const blueprint = getBlueprintForRoom(roomName)
  const { cellSize, gridWidth, gridDepth } = blueprint

  // Convert blueprint walkable center from grid to world coords
  const [relX, , relZ] = gridToWorld(
    blueprint.walkableCenter.x,
    blueprint.walkableCenter.z,
    cellSize,
    gridWidth,
    gridDepth
  )

  // Default radius: ~35% of half-room-size (same as before)
  const defaultRadius = roomSize * 0.17

  return {
    x: rx + relX,
    z: rz + relZ,
    radius: defaultRadius,
  }
}
