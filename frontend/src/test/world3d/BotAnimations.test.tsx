/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useBotAnimation, SleepingZs } from '@/components/world3d/BotAnimations'
import { render } from '@testing-library/react'

const frameCallbacks: Array<(state: any) => void> = []
vi.mock('@react-three/fiber', () => ({
  useFrame: (cb: any) => frameCallbacks.push(cb),
}))

describe('BotAnimations', () => {
  beforeEach(() => {
    frameCallbacks.length = 0
  })

  it('initializes active state with typing pause timers', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const { result } = renderHook(({ status }) => useBotAnimation(status as any, undefined), {
      initialProps: { status: 'active' },
    })
    const s = result.current.current
    expect(s.phase).toBe('idle-wandering')
    expect(s.isActiveWalking).toBe(true)
    expect(s.nextTypingPauseTimer).toBe(5)
  })

  it('transitions idle to idle-wandering (no more coffee targeting)', () => {
    const { result, rerender } = renderHook(
      ({ status }) => useBotAnimation(status as any, undefined),
      {
        initialProps: { status: 'offline' },
      }
    )
    rerender({ status: 'idle' })
    expect(result.current.current.phase).toBe('idle-wandering')
    expect(result.current.current.freezeWhenArrived).toBe(false)
  })

  it('renders SleepingZs and executes frame callback safely', () => {
    const animRef = { current: { showZzz: false } } as any
    render(<SleepingZs animRef={animRef} />)
    expect(frameCallbacks.length).toBeGreaterThan(0)
    frameCallbacks[0]({ clock: { getElapsedTime: () => 1 } })
  })
})
