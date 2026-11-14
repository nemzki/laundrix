(function () {
  "use strict";

  var trigger = document.querySelector("[data-face-login-trigger]");
  var panel = document.querySelector("[data-face-login-camera]");
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

  if (!trigger || !panel || !video || !canvas || !title || !message ||
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
  var controller = null;
  var tickTimer = null;
  var timeoutTimer = null;
  var failures = 0;
  var detector = null;
  var small = document.createElement("canvas");
  var smallCtx = null;
  var previous = null;

  if ("FaceDetector" in window) {
    try { detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 2 }); }
    catch (e) { detector = null; }
  }

  function setTitle(text) { title.textContent = text; }
  function setMessage(text) { message.textContent = text; }
  function setProgress(fraction) {
    progress.style.width = Math.max(0, Math.min(1, fraction)) * 100 + "%";
  }
  function setState(name) { stage.setAttribute("data-state", name); }

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

  function clearCapture() { canvas.width = 0; canvas.height = 0; previous = null; }

  function closePanel() {
    if (controller) { controller.abort(); controller = null; }
    running = false;
    submitting = false;
    stopCamera();
    clearCapture();
    panel.hidden = true;
    retryButton.hidden = true;
    setProgress(0);
    setState("idle");
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

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function captureBest() {
    var best = null, i;
    for (i = 0; i < BURST_FRAMES; i++) {
      var shot = await frameToBlob();
      if (shot.blob.size <= MAX_IMAGE_BYTES && (!best || shot.sharp > best.sharp)) best = shot;
      if (i < BURST_FRAMES - 1) await wait(BURST_GAP_MS);
    }
    if (!best) throw new Error("The captured image is too large. Try again.");
    return best.blob;
  }

  function getSafeRedirect(value) {
    if (typeof value !== "string" || value.charAt(0) !== "/") return null;
    try {
      var u = new URL(value, window.location.origin);
      return u.origin === window.location.origin ? u.href : null;
    } catch (e) { return null; }
  }

  async function submit(blob) {
    var form = document.querySelector('[data-auth-form="staff"]');
    var csrf = form ? form.querySelector('input[name="csrf_token"]') : null;
    if (!csrf || !csrf.value) throw new Error("Unable to verify this sign-in request. Reload the page.");

    var body = new FormData();
    body.append("image", blob, "capture.jpg");
    controller = new AbortController();
    var response = await fetch(panel.dataset.faceLoginUrl, {
      method: "POST", body: body, credentials: "same-origin", signal: controller.signal,
      headers: { "X-CSRFToken": csrf.value, "Accept": "application/json" }
    });
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

  async function verify() {
    submitting = true;
    clearTimers();
    setState("verifying");
    setTitle("Verifying…");
    setMessage("Hold still while we check your face.");
    setProgress(1);
    try {
      var blob = await captureBest();
      var result = await submit(blob);
      var target = getSafeRedirect(result.redirect_url);
      if (!target) throw new Error("The sign-in response was invalid. Please try again.");
      setState("success");
      setTitle("Face verified");
      setMessage("Signing you in…");
      stopCamera();
      clearCapture();
      window.location.assign(target);
    } catch (error) {
      if (error && error.name === "AbortError") return;
      failures += 1;
      var status = error && error.status;
      stopCamera();
      clearCapture();
      setState("failed");
      setTitle(status === 503 ? "Face Login unavailable" : "Not recognised");
      setMessage(error instanceof Error ? error.message : "Face Login could not be completed.");
      running = false;
      if (failures >= MAX_CLIENT_FAILURES) {
        retryButton.hidden = true;
        setMessage(message.textContent + " Please wait a moment or use another sign-in method.");
        setTimeout(function () { failures = 0; if (!panel.hidden) retryButton.hidden = false; }, COOLDOWN_MS);
      } else {
        retryButton.hidden = false;
        retryButton.focus();
      }
    } finally {
      submitting = false;
      controller = null;
    }
  }

  // ---- scan loop ----------------------------------------------------------------------------
  function startScanLoop() {
    var steady = 0, busy = false, startedAt = Date.now();
    previous = null;
    setState("scanning");
    setTitle("Look straight at the camera");
    timeoutTimer = setTimeout(function () {
      if (!running || submitting) return;
      clearTimers();
      stopCamera();
      running = false;
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
        if (!running || submitting) return;
        if (problem) {
          steady = 0;
          setMessage(problem);
          setProgress(0);
          setState("scanning");
          return;
        }
        steady += 1;
        setState("locked");
        setMessage("Perfect. Keep still…");
        setProgress(steady / STEADY_TICKS);
        if (steady >= STEADY_TICKS) { clearInterval(tickTimer); tickTimer = null; await verify(); }
      } finally {
        busy = false;
      }
    }, TICK_MS);
    void startedAt;
  }

  async function startCamera() {
    if (running || submitting || !cameraIsAvailable() || staffPanel.hidden) return;
    running = true;
    retryButton.hidden = true;
    setProgress(0);
    setState("starting");
    setTitle("Starting camera…");
    setMessage("Allow camera access when your browser asks.");
    stopCamera();
    try {
      var s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      if (panel.hidden || staffPanel.hidden) { s.getTracks().forEach(function (t) { t.stop(); }); running = false; return; }
      stream = s;
      video.srcObject = s;
      await video.play();
      setTitle("Getting ready…");
      setMessage("Adjusting to the light…");
      await wait(WARMUP_MS);
      if (!running || panel.hidden) return;
      startScanLoop();
    } catch (error) {
      running = false;
      stopCamera();
      setState("failed");
      setTitle("Camera unavailable");
      setMessage(cameraError(error));
      retryButton.hidden = false;
    }
  }

  function openPanel() {
    if (trigger.disabled || submitting) return;
    failures = failures >= MAX_CLIENT_FAILURES ? failures : 0;
    panel.hidden = false;
    panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    startCamera();
  }

  trigger.addEventListener("click", openPanel);
  retryButton.addEventListener("click", startCamera);
  cancelButton.addEventListener("click", function () {
    closePanel();
    hint.textContent = "Face Login cancelled.";
    trigger.focus();
  });

  new MutationObserver(function () {
    if (staffPanel.hidden) { closePanel(); hint.textContent = ""; }
  }).observe(staffPanel, { attributes: true, attributeFilter: ["hidden"] });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden && running && !submitting) {
      stopCamera();
      running = false;
      setState("failed");
      setTitle("Camera paused");
      setMessage("The camera stopped while the tab was hidden.");
      retryButton.hidden = false;
    }
  });
  window.addEventListener("pagehide", stopCamera);

  if (!cameraIsAvailable()) {
    trigger.disabled = true;
    hint.textContent = "Face Login needs a secure (HTTPS) connection and a browser with camera support.";
  } else {
    hint.textContent = "";
  }
})();
