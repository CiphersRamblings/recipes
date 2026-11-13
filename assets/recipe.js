(() => {
  // Tap a step to mark it done
  document.querySelectorAll(".steps li").forEach(li =>
    li.addEventListener("click", () => li.classList.toggle("done")));

  // Keep the screen awake while cooking (where the browser supports it)
  const btn = document.getElementById("wake");
  if (!("wakeLock" in navigator) || !btn) return;
  btn.hidden = false;
  let lock = null;
  const reset = () => { lock = null; btn.textContent = "Keep screen on"; btn.classList.remove("is-on"); };
  btn.addEventListener("click", async () => {
    if (lock) { await lock.release(); return; }
    try {
      lock = await navigator.wakeLock.request("screen");
      btn.textContent = "Screen staying on ✓";
      btn.classList.add("is-on");
      lock.addEventListener("release", reset);
    } catch (_) { reset(); }
  });
})();
