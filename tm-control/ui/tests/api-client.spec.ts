// The API client's Content-Type: JSON on every request that changes something, unless the call names its own type
// (an upload sends the file's bytes as application/octet-stream).
import { describe, expect, it } from 'vitest'
import { api } from '../src/api/client'
import { fakeApi, json } from './fake-api'

describe('the API client', () => {
  it('sends JSON as the Content-Type of a request without a body', async () => {
    let type: string | null = null
    fakeApi({
      'POST /api/v1/system/reboot': (request: Request) => {
        type = request.headers.get('Content-Type')
        return json(202, { action: 'reboot' })
      },
    })
    await api.POST('/api/v1/system/reboot')
    expect(type).toBe('application/json')
  })

  it("keeps a request's own Content-Type", async () => {
    let type: string | null = null
    const { sent } = fakeApi({
      'PUT /api/v1/models/upload/mine.tflite': (request: Request) => {
        type = request.headers.get('Content-Type')
        return json(201, {})
      },
    })
    await api.PUT('/api/v1/models/upload/{filename}', {
      params: { path: { filename: 'mine.tflite' } },
      body: new Uint8Array(2048) as never,
      bodySerializer: (body: unknown) => body as BodyInit,
      headers: { 'Content-Type': 'application/octet-stream' },
    })
    expect(type).toBe('application/octet-stream')
    expect(sent[0].body).toBe(2048) // the fake records an upload's length, not its bytes
  })
})
