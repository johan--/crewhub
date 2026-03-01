// ─── Per-frame animation state transitions ──────────────────────
// Extracted from BotAnimations.tsx for Vite HMR compatibility.
// Called from Bot3D's single useFrame to avoid extra callbacks.

import type { AnimState } from './BotAnimations'

function tickTypingPause(s: AnimState, delta: number): void {
  if (!s.isActiveWalking || s.phase !== 'idle-wandering') return

  if (s.typingPause) {
    s.typingPauseTimer -= delta
    if (s.typingPauseTimer > 0) return

    s.typingPause = false
    s.bodyTilt = 0
    s.nextTypingPauseTimer = 5 + Math.random() * 10 // next pause in 5-15s
    return
  }

  s.nextTypingPauseTimer -= delta
  if (s.nextTypingPauseTimer > 0) return

  s.typingPause = true
  s.typingPauseTimer = 1 + Math.random() * 1 // pause for 1-2s
  s.bodyTilt = 0.04 // slight forward lean (looking at laptop)
}

export function tickAnimState(s: AnimState, delta: number): void {
  tickTypingPause(s, delta)
}
