import { expect, test, type Page } from '@playwright/test'

type CameraFixture = { streams: MediaStream[]; release: () => void }

async function useSyntheticCamera(page: Page, waitForPermission = false) {
  await page.addInitScript(({ waitForPermission }) => {
    let release = () => {}
    const permission = new Promise<void>(resolve => { release = resolve })
    const fixture = { streams: [] as MediaStream[], release }
    Object.assign(window, { faceCameraFixture: fixture })
    navigator.mediaDevices.getUserMedia = async () => {
      const canvas = document.createElement('canvas')
      canvas.width = 640
      canvas.height = 480
      const ctx = canvas.getContext('2d')!
      const stream = canvas.captureStream(20)
      fixture.streams.push(stream)
      function draw() {
        if (!stream.active) return
        ctx.fillStyle = '#606060'
        ctx.fillRect(0, 0, 640, 480)
        ctx.fillStyle = '#b0b0b0'
        for (let y = 0; y < 480; y += 8) {
          for (let x = y % 16; x < 640; x += 16) ctx.fillRect(x, y, 8, 8)
        }
        requestAnimationFrame(draw)
      }
      draw()
      if (waitForPermission) await permission
      return stream
    }
    // The synthetic texture exercises the production frame-quality and capture logic.
    Object.assign(window, { FaceDetector: class {
      async detect() { return [{ boundingBox: { x: 190, y: 70, width: 260, height: 340 } }] }
    } })
  }, { waitForPermission })
}

function streamStates(page: Page) {
  return page.evaluate(() => (window as unknown as { faceCameraFixture: CameraFixture })
    .faceCameraFixture.streams.map(stream => stream.getVideoTracks()[0].readyState))
}

test('automatic capture uses the existing request and redirect after retry and cooldown', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  await page.clock.install()
  await useSyntheticCamera(page)
  await page.goto('/auth/login?role=staff')
  const csrf = await page.locator('[data-auth-form=staff] [name=csrf_token]').inputValue()
  const trigger = page.getByRole('button', { name: 'Sign in with Face Recognition' })
  const scanner = page.locator('[data-face-login-camera]')
  const retry = scanner.getByRole('button', { name: 'Scan again' })
  let attempts = 0
  let releaseSuccess: () => void = () => {}
  const successGate = new Promise<void>(resolve => { releaseSuccess = resolve })

  await page.route('**/auth/face-login', async route => {
    attempts++
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['x-csrftoken']).toBe(csrf)
    const body = route.request().postDataBuffer()!
    expect(body.includes(Buffer.from('name="image"; filename="capture.jpg"'))).toBe(true)
    expect(body.includes(Buffer.from([0xff, 0xd8, 0xff]))).toBe(true)
    if (attempts === 1) {
      await route.abort('internetdisconnected')
    } else if (attempts < 4) {
      await route.fulfill({ status: 401, json: { ok: false, message: 'Could not verify this sign-in.' } })
    } else {
      await successGate
      await route.fulfill({ json: { ok: true, redirect_url: '/dashboard/staff' } })
    }
  })
  await page.route('**/dashboard/staff', route => route.fulfill({ contentType: 'text/html', body: '<h1>Staff dashboard destination</h1>' }))

  await trigger.click()
  await expect(scanner.getByRole('progressbar')).toHaveAttribute('aria-valuenow', /^(25|50|75)$/)
  await page.screenshot({ path: testInfo.outputPath('scanner-desktop.png') })
  for (let attempt = 1; attempt <= 3; attempt++) {
    await expect(scanner.getByRole('status')).toHaveText('Verification Unsuccessful')
    if (attempt === 1) await expect(scanner.locator('[data-face-login-message]')).toContainText('Check your connection')
    expect(attempts).toBe(attempt)
    expect(await streamStates(page)).toEqual(Array(attempt).fill('ended'))
    if (attempt < 3) await retry.click()
  }
  await expect(retry).toBeHidden()
  await scanner.getByRole('button', { name: 'Back to Sign In' }).click()
  await expect(page).toHaveURL(/role=staff$/)
  await trigger.click()
  await expect(scanner.getByRole('status')).toHaveText('Please wait before trying again')
  expect(attempts).toBe(3)
  await page.clock.fastForward(30_001)
  await scanner.getByRole('button', { name: 'Start Scan' }).click()
  await expect.poll(() => attempts).toBe(4)
  await expect(scanner.getByRole('status')).toHaveText('Verifying Your Identity')

  // Closing the view releases the camera while the already-sent sign-in can complete.
  await scanner.getByRole('button', { name: 'Back to Sign In' }).click()
  await expect(scanner).toBeHidden()
  expect(await streamStates(page)).toEqual(Array(4).fill('ended'))
  releaseSuccess()
  await expect(page).toHaveURL(/\/dashboard\/staff$/)
  await expect(page.getByRole('heading', { name: 'Staff dashboard destination' })).toBeVisible()
})

test('browser history releases camera permission races and returns to the Staff tab', async ({ page }) => {
  await useSyntheticCamera(page, true)
  await page.setViewportSize({ width: 660, height: 350 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/auth/login')
  await page.getByRole('tab', { name: 'Staff' }).click()
  const scanner = page.locator('[data-face-login-camera]')
  const trigger = page.getByRole('button', { name: 'Sign in with Face Recognition' })
  await trigger.click()
  await expect(scanner.getByRole('status')).toHaveText('Allow Camera Access')
  await expect(page.getByRole('heading', { name: 'Face Recognition' })).toBeFocused()
  await expect(page).toHaveURL(/role=staff#face-recognition$/)
  await page.goBack()
  await expect(trigger).toBeFocused()
  await page.evaluate(() => (window as unknown as { faceCameraFixture: CameraFixture }).faceCameraFixture.release())
  await expect.poll(() => streamStates(page)).toEqual(['ended'])
  await expect(page.getByRole('tab', { name: 'Staff' })).toHaveAttribute('aria-selected', 'true')

  await page.goForward()
  await expect(scanner.getByRole('status')).toHaveText('Ready to Scan')
  expect(await streamStates(page)).toEqual(['ended'])
  await scanner.getByRole('button', { name: 'Start Scan' }).click()
  await expect.poll(() => streamStates(page)).toEqual(['ended', 'live'])
  await expect(scanner.locator('.lx-scan__beam')).toHaveCSS('animation-name', 'none')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await scanner.getByRole('button', { name: 'Cancel' }).click()
  await expect(scanner).toBeHidden()
  await expect.poll(() => streamStates(page)).toEqual(['ended', 'ended'])
  await expect(trigger).toBeFocused()
})
