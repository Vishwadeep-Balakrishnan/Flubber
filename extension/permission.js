// Chrome side panels cannot show the microphone prompt, so Flubber asks once from this tab.
// The permission belongs to the extension, so the side panel can use the mic afterwards.
(() => {
  const $ = id => document.getElementById(id);
  async function ask() {
    $('allow').disabled = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      stream.getTracks().forEach(track => track.stop());
      $('title').textContent = 'You’re all set.';
      $('detail').textContent = 'Go back to Flubber and tap the mic. This tab will close by itself.';
      $('allow').hidden = true;
      setTimeout(async () => {
        try { const tab = await chrome.tabs.getCurrent(); if (tab?.id) await chrome.tabs.remove(tab.id); } catch {}
      }, 1800);
    } catch (error) {
      $('title').textContent = 'Microphone is blocked';
      $('detail').textContent = error?.name === 'NotFoundError'
        ? 'No microphone was found. Connect one and try again.'
        : 'Click the icon at the right of the address bar, allow the microphone for Flubber, then try again.';
      $('allow').disabled = false;
    }
  }
  $('allow').addEventListener('click', ask);
  ask();
})();
