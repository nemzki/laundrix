/* Guide the user through the camera scan and display the sign-in result. */
(function () {
  "use strict";

  var trigger = document.querySelector("[data-face-login-trigger]");
  var shell = document.querySelector("[data-face-login-shell]");
  var panel = document.querySelector("[data-face-login-camera]");
  var heading = document.querySelector("[data-face-login-heading]");
  var backButton = document.querySelector("[data-face-login-back]");
  var video = document.querySelector("[data-face-login-video]");
  var canvas = document.querySelector("[data-face-login-canvas]");
  var title = document.querySelector("[data-face-login-status]");
  var message = document.querySelector("[data-face-login-message]");
  var hint = document.querySelector("[data-face-login-hint]");
  var progress = document.querySelector("[data-face-login-progress]");
  var stage = document.querySelector("[data-face-login-stage]");
  var retryButton = document.querySelector("[data-face-login-start]");
  var cancelButton = document.querySelector("[data-face-login-cancel]");
  var staffPanel = document.querySelector('[data-auth-panel="staff"]');

  if (!trigger || !shell || !panel || !heading || !backButton || !video || !canvas || !title || !message ||
      !progress || !stage || !retryButton || !cancelButton || !staffPanel) {
    return;
  }

  // ---- tuning -------------------------------------------------------------------------------
  var WARMUP_MS = 1200;          // let auto-exposure / focus settle before judging frames
  var TICK_MS = 250;             // quality check interval
  var STEADY_TICKS = 4;          // consecutive good checks (~1 s) before capturing
  var SCAN_TIMEOUT_MS = 30000;   // give up if no good frame is found
  var BURST_FRAMES = 3;          // frames captured once steady; the sharpest is sent
  var BURST_GAP_MS = 200;
  var MIN_LUMA = 70, MAX_LUMA = 205;
  var MIN_SHARPNESS = 12;        // variance of Laplacian on a 160px frame; blur below this
  var MAX_MOTION = 9;            // mean abs frame difference (0-255) allowed while "holding still"
  var MAX_IMAGE_BYTES = 1400 * 1024;
  var MAX_CLIENT_FAILURES = 3;   // then pause (server allows 5 attempts per minute)
  var COOLDOWN_MS = 30000;

  var stream = null;
  var running = false;           // a scan session is active
  var submitting = false;
  var scan = null;
  var tickTimer = null;
  var timeoutTimer = null;
  var failures = 0;
  var cooldownUntil = 0;
  var cooldownTimer = null;
  var detector = null;
  var small = document.createElement("canvas");
  var smallCtx = null;
  var previous = null;

  if ("FaceDetector" in window) {
    try { detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 2 }); }
    catch (e) { detector = null; }
  }

  function setTitle(text) { if (title.textContent !== text) title.textContent = text; }
  function setMessage(text) { if (message.textContent !== text) message.textContent = text; }
  /* Keep the visible progress indicator and its accessible value in sync. */
  function setProgress(fraction) {
    var percent = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
    progress.style.width = percent + "%";
    progress.parentElement.setAttribute("aria-valuenow", percent);
  }
  function setState(name) { stage.setAttribute("data-state", name); }

  /* Check whether this browser can provide camera access. */
  function cameraIsAvailable() {
    return window.isSecureContext && navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === "function";
  }

  function cameraError(error) {
    var n = error && error.name;
    if (n === "NotAllowedError" || n === "SecurityError") {
      return "Camera permission was denied. Allow camera access in your browser settings, then scan again.";
    }
    if (n === "NotFoundError" || n === "DevicesNotFoundError") return "No camera was found on this device.";
    if (n === "NotReadableError") return "The camera is busy. Close other apps using it and try again.";
    return "Unable to start the camera. Check your browser permissions and try again.";
  }

  function clearTimers() {
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
  }

  /* Stop the active camera stream and release its resources. */
  function stopCamera() {
    clearTimers();
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    video.pause();
    video.srcObject = null;
    video.removeAttribute("src");
  }

  function clearCapture() {
    canvas.width = canvas.height = small.width = small.height = 0;
    previous = null;
  }

  function stopScan() {
    if (scan) { scan.abort(); scan = null; }
    running = false;
    stopCamera();
    clearCapture();
  }

  /* Close the panel. */
  function closePanel() {
    stopScan();
    if (cooldownTimer) { clearTimeout(cooldownTimer); cooldownTimer = null; }
    panel.hidden = true;
    shell.hidden = false;
    retryButton.hidden = true;
    setProgress(0);
    setState("idle");
  }

  /* Update the scanner panel while it waits for a usable camera frame. */
  function showWaitingState() {
    var delay = cooldownUntil - Date.now();
    if (delay <= 0) {
      if (cooldownUntil) { failures = 0; cooldownUntil = 0; }
      setTitle("Ready to Scan");
      setMessage("We’ll use your camera to verify your identity.");
      retryButton.textContent = "Start Scan";
      retryButton.hidden = false;
      return;
    }
    setTitle("Please wait before trying again");
    setMessage("Wait for the cooldown to finish or return to Staff Sign In.");
    retryButton.hidden = true;
    clearTimeout(cooldownTimer);
    cooldownTimer = setTimeout(function () {
      cooldownTimer = null;
      if (!panel.hidden) showWaitingState();
    }, delay);
  }

  // ---- frame analysis -----------------------------------------------------------------------
  function analyse() {
    if (!video.videoWidth || !video.videoHeight) return null;
    var w = 160, h = Math.round(160 * video.videoHeight / video.videoWidth);
    small.width = w; small.height = h;
    smallCtx = smallCtx || small.getContext("2d", { willReadFrequently: true });
    smallCtx.drawImage(video, 0, 0, w, h);
    var data = smallCtx.getImageData(0, 0, w, h).data;
    var gray = new Float32Array(w * h), sum = 0, i;
    for (i = 0; i < w * h; i++) {
      var g = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
      gray[i] = g; sum += g;
    }
    var luma = sum / (w * h);

    var lapSum = 0, lapSq = 0, n = 0, x, y, v;
    for (y = 1; y < h - 1; y++) {
      for (x = 1; x < w - 1; x++) {
        i = y * w + x;
        v = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w];
        lapSum += v; lapSq += v * v; n++;
      }
    }
    var sharp = lapSq / n - (lapSum / n) * (lapSum / n);

    var motion = 0;
    if (previous && previous.length === gray.length) {
      for (i = 0; i < gray.length; i += 3) motion += Math.abs(gray[i] - previous[i]);
      motion = motion / Math.ceil(gray.length / 3);
    } else {
      motion = 255;
    }
    previous = gray;
    return { luma: luma, sharp: sharp, motion: motion };
  }

  async function checkFace() {
    // Optional: only where the browser ships the Shape Detection API.
    if (!detector) return { ok: true };
    try {
      var faces = await detector.detect(video);
      if (!faces || faces.length === 0) return { ok: false, hint: "We can't see your face. Look at the camera." };
      if (faces.length > 1) return { ok: false, hint: "Only one person should be in view." };
      var b = faces[0].boundingBox, vw = video.videoWidth, vh = video.videoHeight;
      if (b.width < vw * 0.22) return { ok: false, hint: "Move a little closer." };
      if (b.width > vw * 0.75) return { ok: false, hint: "Move back a little." };
      var cx = (b.x + b.width / 2) / vw, cy = (b.y + b.height / 2) / vh;
      if (Math.abs(cx - 0.5) > 0.2 || Math.abs(cy - 0.5) > 0.22) return { ok: false, hint: "Center your face in the oval." };
      return { ok: true };
    } catch (e) {
      detector = null;   // detector unusable here; fall back to image-quality checks only
      return { ok: true };
    }
  }

  // ---- capture ------------------------------------------------------------------------------
  function frameToBlob() {
    return new Promise(function (resolve, reject) {
      var scale = Math.min(1, 800 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      var ctx = canvas.getContext("2d");
      if (!ctx) { reject(new Error("Unable to prepare the camera image.")); return; }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);   // un-mirrored, as the camera sees you
      var q = analyse();
      canvas.toBlob(function (blob) {
        if (!blob) { reject(new Error("Unable to capture the camera image.")); return; }
        resolve({ blob: blob, sharp: q ? q.sharp : 0 });
      }, "image/jpeg", 0.85);
    });
  }

  function wait(ms, signal) {
    return new Promise(function (resolve, reject) {
      signal.throwIfAborted();
      function abort() { clearTimeout(timer); reject(signal.reason); }
      var timer = setTimeout(function () {
        signal.removeEventListener("abort", abort);
        resolve();
      }, ms);
      signal.addEventListener("abort", abort, { once: true });
    });
  }

  /* Choose a camera frame to send for verification. */
  async function captureBest(signal) {
    var best = null, i;
    for (i = 0; i < BURST_FRAMES; i++) {
      signal.throwIfAborted();
      var shot = await frameToBlob();
      signal.throwIfAborted();
      if (shot.blob.size <= MAX_IMAGE_BYTES && (!best || shot.sharp > best.sharp)) best = shot;
      if (i < BURST_FRAMES - 1) await wait(BURST_GAP_MS, signal);
    }
    if (!best) throw new Error("The captured image is too large. Try again.");
    return best.blob;
  }

  /* Check the destination before sending the user to the next page. */
  function getSafeRedirect(value) {
    if (typeof value !== "string" || value.charAt(0) !== "/") return null;
    try {
      var u = new URL(value, window.location.origin);
      return u.origin === window.location.origin ? u.href : null;
    } catch (e) { return null; }
  }

  /* Attach the captured image and request token before sending the verification request. */
  async function submit(blob) {
    var form = document.querySelector('[data-auth-form="staff"]');
    var csrf = form ? form.querySelector('input[name="csrf_token"]') : null;
    if (!csrf || !csrf.value) throw new Error("Unable to verify this sign-in request. Reload the page.");

    var body = new FormData();
    body.append("image", blob, "capture.jpg");
    // Once sent, the request can establish a session even if the scanner view closes.
    var response;
    try {
      response = await fetch(panel.dataset.faceLoginUrl, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-CSRFToken": csrf.value, "Accept": "application/json" }
      });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new Error("Couldn’t reach the verification service. Check your connection and try again.");
      }
      throw error;
    }
    var result = null;
    try { result = await response.json(); } catch (e) { /* handled below */ }
    if (!response.ok || !result || result.ok !== true) {
      var err = new Error(result && typeof result.message === "string" ? result.message
        : "Face Login could not be completed. Please try again.");
      err.status = response.status;
      throw err;
    }
    return result;
  }

  /* Switch the scanner to its verification state and handle the result of the request. */
  async function verify(signal) {
    submitting = true;
    clearTimers();
    setState("verifying");
    setTitle("Verifying Your Identity");
    setMessage("Please wait while we securely verify your identity.");
    setProgress(1);
    try {
      var blob = await captureBest(signal);
      signal.throwIfAborted();
      stopCamera();
      clearCapture();
      var result = await submit(blob);
      var target = getSafeRedirect(result.redirect_url);
      if (!target) throw new Error("The sign-in response was invalid. Please try again.");
      setState("success");
      setTitle("Identity Verified");
      setMessage("Signing you in…");
      stopScan();
      window.location.assign(target);
    } catch (error) {
      if (error && error.name === "AbortError") return;
      failures += 1;
      var status = error && error.status;
      stopScan();
      if (failures >= MAX_CLIENT_FAILURES) cooldownUntil = Date.now() + COOLDOWN_MS;
      if (panel.hidden) return;
      setState("failed");
      setTitle(status === 503 ? "Face Login Unavailable" : "Verification Unsuccessful");
      setMessage(error instanceof Error ? error.message : "Face Login could not be completed.");
      if (failures >= MAX_CLIENT_FAILURES) {
        retryButton.hidden = true;
        setMessage(message.textContent + " Please wait a moment or use another sign-in method.");
        cooldownTimer = setTimeout(function () {
          cooldownTimer = null;
          if (!panel.hidden) showWaitingState();
        }, COOLDOWN_MS);
      } else {
        retryButton.hidden = false;
        retryButton.focus();
      }
    } finally {
      submitting = false;
    }
  }

  // ---- scan loop ----------------------------------------------------------------------------
  function startScanLoop(signal) {
    var steady = 0, busy = false;
    previous = null;
    setState("scanning");
    setTitle("Position Your Face");
    setMessage("Look directly at the camera and keep your face inside the oval.");
    timeoutTimer = setTimeout(function () {
      if (!running || submitting) return;
      stopScan();
      setState("failed");
      setTitle("Couldn't get a clear view");
      setMessage("Try a brighter spot, remove glasses or a mask, and face the camera.");
      retryButton.hidden = false;
    }, SCAN_TIMEOUT_MS);

    tickTimer = setInterval(async function () {
      if (busy || !running || submitting) return;
      busy = true;
      try {
        var q = analyse();
        if (!q) return;
        var problem = null;
        if (q.luma < MIN_LUMA) problem = "It's too dark. Face a light source.";
        else if (q.luma > MAX_LUMA) problem = "Too bright. Avoid a bright light or window behind you.";
        else if (q.sharp < MIN_SHARPNESS) problem = "The image is blurry. Hold still and wipe the lens.";
        else if (q.motion > MAX_MOTION) problem = "Hold still…";
        if (!problem) {
          var f = await checkFace();
          if (!f.ok) problem = f.hint;
        }
        if (signal.aborted || !running || submitting) return;
        if (problem) {
          steady = 0;
          setTitle("Position Your Face");
          setMessage(problem);
          setProgress(0);
          setState("scanning");
          return;
        }
        steady += 1;
        setState("locked");
        setTitle("Scanning Your Face");
        setMessage("Hold still while we capture a clear image.");
        setProgress(steady / STEADY_TICKS);
        if (steady >= STEADY_TICKS) { clearInterval(tickTimer); tickTimer = null; await verify(signal); }
      } finally {
        busy = false;
      }
    }, TICK_MS);
  }

  async function startCamera() {
    if (running || submitting || panel.hidden || !cameraIsAvailable()) return;
    if (Date.now() < cooldownUntil) { showWaitingState(); return; }
    if (cooldownUntil) { failures = 0; cooldownUntil = 0; }
    stopScan();
    scan = new AbortController();
    var signal = scan.signal;
    running = true;
    if (document.activeElement === retryButton) heading.focus({ preventScroll: true });
    retryButton.hidden = true;
    retryButton.textContent = "Scan again";
    setProgress(0);
    setState("starting");
    setTitle("Allow Camera Access");
    setMessage("Please allow camera access when prompted by your browser.");
    try {
      var s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      if (signal.aborted) { s.getTracks().forEach(function (t) { t.stop(); }); return; }
      stream = s;
      video.srcObject = s;
      await video.play();
      signal.throwIfAborted();
      setTitle("Position Your Face");
      setMessage("Adjusting to the light…");
      await wait(WARMUP_MS, signal);
      startScanLoop(signal);
    } catch (error) {
      if (signal.aborted) return;
      stopScan();
      setState("failed");
      setTitle("Camera unavailable");
      setMessage(cameraError(error));
      retryButton.hidden = false;
    }
  }

  /* Open the panel. */
  function openPanel(startImmediately) {
    shell.hidden = true;
    panel.hidden = false;
    window.scrollTo({ top: 0, behavior: "instant" });
    heading.focus({ preventScroll: true });
    if (startImmediately) startCamera();
    else showWaitingState();
  }

  function returnToSignIn() {
    closePanel();
    hint.textContent = "Face Login cancelled.";
    trigger.focus();
    if (history.state && history.state.staffFaceScanner) history.back();
  }

  trigger.addEventListener("click", function () {
    if (trigger.disabled || submitting || !panel.hidden) return;
    var loginUrl = new URL(window.location.href);
    loginUrl.searchParams.set("role", "staff");
    history.replaceState(history.state, "", loginUrl);
    var scanUrl = new URL(loginUrl);
    scanUrl.hash = "face-recognition";
    history.pushState({ staffFaceScanner: true }, "", scanUrl);
    openPanel(true);
  });
  retryButton.addEventListener("click", startCamera);
  cancelButton.addEventListener("click", returnToSignIn);
  backButton.addEventListener("click", returnToSignIn);

  function restoreView() {
    if (history.state && history.state.staffFaceScanner && cameraIsAvailable()) {
      if (staffPanel.hidden) document.querySelector('[data-auth-role="staff"]').click();
      if (panel.hidden) openPanel(false);
    } else if (!panel.hidden) {
      closePanel();
      trigger.focus();
    }
  }
  /* Restore the page state when the user moves through browser history. */
  window.addEventListener("popstate", restoreView);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden && running && !submitting) {
      stopScan();
      setState("failed");
      setTitle("Camera paused");
      setMessage("The camera stopped while the tab was hidden.");
      retryButton.hidden = false;
    }
  });
  window.addEventListener("pagehide", function () {
    if (!panel.hidden) closePanel();
    else stopScan();
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) restoreView();
  });

  if (!cameraIsAvailable()) {
    trigger.disabled = true;
    hint.textContent = "Face Login needs a secure (HTTPS) connection and a browser with camera support.";
  } else {
    hint.textContent = "";
    restoreView();
  }
})();
