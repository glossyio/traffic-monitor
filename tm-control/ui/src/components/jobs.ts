// Waiting for a root job (GET /jobs/{id}): the system password at setup, an entered secret on the Device page.
import { api } from '../api/client'
import type { Job } from '../api/types'

export const JOB_POLL_MS = 1000
export const JOB_DEADLINE_MS = 120_000 // after this, stop waiting: the device may never say more
export const JOB_POLL_TIMEOUT_MS = 8000 // one poll that gets no answer in this long fails like a network error

// Asks every JOB_POLL_MS until the job has succeeded or failed (`done` resolves with it), the deadline passes, or
// cancel() is called (both resolve null). A failed request rejects `done`, and so does a poll that gets no answer in
// JOB_POLL_TIMEOUT_MS: a phone that has left the device's network may wait minutes for the browser to give up.
export function followJob(id: string, deadlineMs = JOB_DEADLINE_MS): { done: Promise<Job | null>; cancel(): void } {
  let cancelled = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let wake = () => {}

  const pause = () =>
    new Promise<void>((resolve) => {
      wake = resolve
      timer = setTimeout(resolve, JOB_POLL_MS)
    })

  async function poll() {
    const controller = new AbortController()
    const limit = setTimeout(() => controller.abort(), JOB_POLL_TIMEOUT_MS)
    try {
      return await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id } }, signal: controller.signal })
    } finally {
      clearTimeout(limit)
    }
  }

  async function follow(): Promise<Job | null> {
    const deadline = Date.now() + deadlineMs
    for (;;) {
      const { data } = await poll()
      if (cancelled) return null
      const job = data as Job
      if (job.status === 'succeeded' || job.status === 'failed') return job
      // queued or running: the device may never say more, for example when tm-control can't read the journal
      if (Date.now() >= deadline) return null
      await pause()
      if (cancelled) return null
    }
  }

  return {
    done: follow(),
    cancel() {
      cancelled = true
      clearTimeout(timer)
      wake()
    },
  }
}
